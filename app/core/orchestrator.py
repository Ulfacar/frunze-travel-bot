"""Оркестратор: принимает Message, ведёт диалог через нужную воронку, отвечает.

Параллельно ведёт персистентный лог диалога для админ-панели (карточка + сообщения):
входящие пишутся ВСЕГДА (в т.ч. при перехвате — чтобы менеджер видел новые реплики
клиента), исходящие — когда бот отвечает. Сбои лога не должны ронять ответ бота.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.channels.base import ChannelAdapter, Message
from app.config import BotConfig, settings
from app.core.manager_brief import build_manager_brief
from app.core.readiness import compute_readiness
from app.core.observ import record_failure
from app.core.own_outbound import mark_own
from app.core.router import detect_funnel
from app.core.state import get_state_store
from app.funnels import get_funnel
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("orchestrator")

GREETING = (
    "Здравствуйте! 😊 Это Frunze Travel. "
    "Подскажите, что вас интересует — тур, виза или авиабилеты?"
)

# Авто-исход диалога из стадии (ручные won/lost не перетираются — см. store).
_OFFICE_STAGES = {"office", "office_consultation"}
_MANAGER_STAGES = {"manager", "manager_handoff"}


# Сериализация обработки в рамках одного диалога. Два быстрых сообщения клиента подряд —
# это два параллельных запроса FastAPI; без лока оба читают/пишут одно состояние и оба
# отвечают → гонка истории и дубли ответов (видели в проде). Лок на ключ диалога гонит
# их строго по очереди: второй ход видит уже обновлённую историю и состояние.
_key_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    lock = _key_locks.get(key)
    if lock is None:
        lock = _key_locks.setdefault(key, asyncio.Lock())
    return lock


def _auto_outcome(stage: str) -> str:
    if stage in _OFFICE_STAGES:
        return "office"
    if stage in _MANAGER_STAGES:
        return "manager"
    return "in_progress"


def _default_manager_name(bot: BotConfig) -> str:
    if bot.manager_name:
        return bot.manager_name
    if bot.scenario == "visa":
        return "Медина"
    if bot.id.endswith("sezim") or "sezim" in bot.id.lower():
        return "Сезим"
    if bot.scenario == "tours":
        return "Адеми"
    return "Сезим"

NON_TEXT_FALLBACK = (
    "Голосовые сообщения пока не распознаём 🙏 Напишите, пожалуйста, словами — "
    "или скажите «нужен менеджер», и я позову человека."
)
# Второе голосовое/медиа подряд без текста — не мучаем клиента просьбой «напишите словами»,
# а сразу зовём менеджера (решение со встречи 06.07: 2 аудио подряд → человек прослушает).
NON_TEXT_HANDOFF = (
    "Вижу, вам удобнее голосом 🙏 Передаю менеджеру — он прослушает и ответит вам."
)
# Мягкий фолбэк, если ход не удалось обработать (сбой LLM/инструмента) — клиент НЕ
# должен получать тишину или 500. Диалог не роняем, состояние сохраняем.
LLM_ERROR_FALLBACK = (
    "Секундочку, уточню детали и вернусь к вам 🙏"
)


class Orchestrator:
    """Ведёт диалог одного бота. Если `bot` задан, его сценарий жёстко определяет
    воронку (тур-боты не угадывают её по ключевым словам). Без `bot` (дев-демо в
    Telegram) воронка определяется keyword-детектом, как раньше.
    """

    def __init__(self, channel: ChannelAdapter, bot: BotConfig | None = None) -> None:
        self.channel = channel
        self.bot = bot
        # Дебаунс: буфер быстрых реплик клиента и таймер тихого окна на диалог. В пределах
        # процесса (как и _lock_for) — допущение «один воркер / sticky», как у остального стейта.
        self._buffers: dict[str, list[Message]] = {}
        self._timers: dict[str, asyncio.Task] = {}

    @property
    def _bot_id(self) -> str:
        return self.bot.id if self.bot else ""

    def _key(self, msg: Message) -> str:
        """Ключ диалога: <bot_id>:<номер>. Один номер у разных ботов = разные диалоги
        (раздельные состояние/перехват/карточка). В дев-демо без bot — просто номер."""
        return f"{self._bot_id}:{msg.user_id}" if self.bot else msg.user_id

    async def _bots_on(self) -> bool:
        """Рубильник авто-ответов (флаг в БД, переключается из панели).

        Per-bot ключ `bots_enabled:<bot_id>` переопределяет глобальный `bots_enabled`:
        позволяет включить тест-ботов в Telegram, не будя боевой WhatsApp (его боты
        персональный ключ не задают → наследуют глобальный, сейчас OFF).

        Поверх этого — ночной режим: при `night_mode_enabled` бот отвечает ТОЛЬКО в
        ночном окне по Бишкеку (днём менеджеры ведут вручную). Ночь НЕ включает
        выключенного кнопкой бота — только сужает окно уже включённого."""
        from app.core import flags
        global_on = await flags.get_flag("bots_enabled", True)
        if self._bot_id:
            enabled = await flags.get_flag(f"bots_enabled:{self._bot_id}", global_on)
        else:
            enabled = global_on
        if enabled and await self._night_mode_blocks():
            return False
        return enabled

    async def _night_mode_blocks(self) -> bool:
        """True → сейчас ДЕНЬ и ночной режим включён (бот должен молчать).

        Окно [from, to) по Бишкеку, через полночь (22→8). Вне окна = день = блок."""
        from app.core import flags
        if not await flags.get_flag("night_mode_enabled", settings.night_mode_enabled):
            return False
        local_hour = (datetime.now(timezone.utc) + timedelta(hours=6)).hour
        a, b = settings.night_mode_from, settings.night_mode_to
        in_night = (local_hour >= a or local_hour < b) if a > b else (a <= local_hour < b)
        return not in_night

    async def handle(self, msg: Message) -> None:
        if not msg.user_id:
            return  # служебный/пустой апдейт
        key = self._key(msg)

        # Не-текст (голос/фото/медиа): бот не распознаёт — логируем и сразу честный fallback,
        # без дебаунса (склеивать нечего).
        if msg.kind == "non_text":
            async with _lock_for(key):
                await self._handle_non_text(msg)
            return

        if not msg.text:
            return  # пустой апдейт без содержимого

        # Входящее логируем СРАЗУ (вне обработки) — менеджер видит реплику живьём, даже если
        # перехвачено / рубильник off / идёт окно дебаунса.
        await self._log_in(msg, msg.text)

        # Дебаунс выключен (0) — синхронная обработка под локом, как раньше (_run_turn сбросит
        # счётчик голосовых сам).
        if settings.debounce_seconds <= 0:
            async with _lock_for(key):
                await self._run_turn(msg)
            return

        # Текст прерывает серию голосовых СРАЗУ на входе: при дебаунсе _run_turn отработает только
        # после окна тишины, а до него мог прийти 2-й голос и ложно триггернуть хендофф.
        async with _lock_for(key):
            st = await get_state_store().load(key)
            if st.consecutive_audio:
                st.consecutive_audio = 0
                await get_state_store().save(st)

        # Дебаунс включён: копим быстрые реплики клиента и перезапускаем таймер тихого окна.
        # По его истечении обработаем склеенный текст одним ходом LLM (без задвоений ответов).
        self._buffers.setdefault(key, []).append(msg)
        old = self._timers.get(key)
        if old is not None:
            old.cancel()
        self._timers[key] = asyncio.create_task(self._debounce_flush(key))

    async def _handle_non_text(self, msg: Message) -> None:
        """Голос/медиа: бот не распознаёт. 1-е — честный фолбэк; 2-е подряд → зовём менеджера.

        Счётчик `consecutive_audio` живёт в состоянии и сбрасывается в 0 любым текстовым
        сообщением (см. _run_turn). Под локом диалога.
        """
        await self._log_in(msg, "[медиа/голос]")
        key = self._key(msg)
        store = get_state_store()
        state = await store.load(key)
        if self.bot is not None:
            state.bot_id = self.bot.id
            state.manager_name = _default_manager_name(self.bot)
        if state.intercepted or not await self._bots_on():
            return  # перехвачено / рубильник off — лог записали, бот молчит
        state.consecutive_audio += 1
        if state.consecutive_audio >= 2:
            # 2 голосовых/медиа подряд без текста → авто-хендофф: менеджер прослушает.
            state.stage = "manager"
            state.intercepted = True
            await store.save(state)
            await self._sync_card(msg, state)
            await self._reply(msg, NON_TEXT_HANDOFF)
            return
        await store.save(state)
        await self._reply(msg, NON_TEXT_FALLBACK)

    async def _debounce_flush(self, key: str) -> None:
        """По истечении тихого окна склеить буфер и обработать одним ходом."""
        try:
            await asyncio.sleep(settings.debounce_seconds)
        except asyncio.CancelledError:
            return  # пришла новая реплика — этот таймер заменён свежим
        async with _lock_for(key):
            msgs = self._buffers.pop(key, [])
            self._timers.pop(key, None)
            if not msgs:
                return
            combined = "\n".join(m.text for m in msgs if m.text)
            # referral почти всегда на первом сообщении пачки — берём первый непустой,
            # а не из msgs[-1], иначе рекламный контекст потерялся бы при склейке.
            referral = next((m.referral for m in msgs if m.referral), {})
            combined_msg = replace(msgs[-1], text=combined, referral=referral)
            try:
                await self._run_turn(combined_msg)
            except Exception:  # noqa: BLE001 — фон: не роняем процесс, входящие уже в логе
                log.error("debounce flush failed (key=%s)", key, exc_info=True)

    async def _run_turn(self, msg: Message) -> None:
        """Обработать ход (выбор воронки → LLM → ответ) для уже залогированного входящего.

        Вызывается ПОД локом диалога: синхронно из handle (дебаунс off) либо из
        _debounce_flush со склеенным текстом. Входящее в панель уже записано в handle.
        """
        key = self._key(msg)
        store = get_state_store()
        state = await store.load(key)
        if self.bot is not None:
            state.bot_id = self.bot.id
            state.manager_name = _default_manager_name(self.bot)
        if msg.referral and not state.ad_referral:
            state.ad_referral = dict(msg.referral)  # write-once: источник = первое касание
        state.consecutive_audio = 0  # пришёл текст — серия голосовых прервана

        # Главный рубильник: если авто-ответы выключены из панели — бот молчит во всех
        # воронках (сообщение клиента уже в логе, менеджер ведёт диалог вручную).
        if not await self._bots_on():
            return

        # Перехват: бот молчит во всех воронках. НО при авто-хендоффе (stage=manager), пока
        # менеджер не подключился, один раз честно подтверждаем клиенту, что запрос передан и
        # когда ответят — иначе клиент висит в тишине («Алло… когда звонок?» по 15 сообщений).
        if state.intercepted:
            if state.stage == "manager":
                await self._maybe_wait_ack(msg, state, store)
            return

        # Выбор воронки, если ещё не определена.
        if state.funnel is None:
            if self.bot is not None:
                state.funnel = self.bot.scenario  # сценарий бота фиксирует воронку
            else:
                detected = detect_funnel(msg.text)
                if detected is None:
                    await self._reply(msg, GREETING)
                    await store.save(state)
                    return
                state.funnel = detected

        if await self._maybe_persona_greeting(msg, state, store):
            return

        faq_reply = await self._maybe_faq_reply(msg, state, store)
        if faq_reply:
            return

        funnel = get_funnel(state.funnel)
        try:
            reply = await funnel.handle(msg, state)
        except Exception:  # noqa: BLE001 — сбой LLM/инструмента: не роняем вебхук, мягкий фолбэк
            log.error("funnel handle failed (key=%s)", key, exc_info=True)
            record_failure("llm")
            await store.save(state)               # сохраняем то, что успело накопиться в ходе
            await self._reply(msg, LLM_ERROR_FALLBACK)
            return

        # Передача менеджеру = бот замолкает (решение заказчика 23.06.2026): прощальную
        # реплику этого хода ещё отправляем, но дальше в этом чате отвечает только человек.
        # Менеджер видит карточку в «У менеджера» и может «Вернуть боту» из панели.
        auto_handoff = state.stage == "manager"
        if auto_handoff:
            state.intercepted = True

        # Перехват «на лету»: менеджер мог нажать «Перехватить», пока генерировался ответ.
        # Перечитываем свежее состояние; если перехвачено не нами (не хендофф) — не отвечаем.
        fresh = await store.load(key)
        intercepted_midflight = fresh.intercepted and not auto_handoff
        if intercepted_midflight:
            state.intercepted = True

        await store.save(state)
        await self._sync_card(msg, state)
        if reply and not intercepted_midflight:
            await self._reply(msg, reply)
        elif intercepted_midflight:
            log.info("reply dropped: intercepted mid-flight (key=%s)", key)

    async def _maybe_wait_ack(self, msg: Message, state, store) -> None:
        """Разовое подтверждение клиенту после авто-хендоффа, пока менеджер молчит.

        Не вмешиваемся, если менеджер уже подключился (закрепил диалог или ответил) —
        тогда бот молчит, чтобы не говорить поверх человека. Анти-спам: один ack на период
        ожидания; флаг сбрасывается, когда менеджер отвечает (новая пауза → новое ack)."""
        from app.core.branding import wait_ack_for
        try:
            conv = await get_conversation_store().get(self._key(msg))
        except Exception:  # noqa: BLE001 — нет данных панели: лучше промолчать
            return
        manager_engaged = bool(conv and (conv.assigned_to or any(
            m.sender == "manager" for m in conv.messages)))
        if manager_engaged:
            if state.wait_ack_sent:        # менеджер на связи — сбросим, чтобы при новой
                state.wait_ack_sent = False  # паузе подтвердить заново
                await store.save(state)
            return
        if state.wait_ack_sent:
            return  # уже подтвердили — дальше о брошенном клиенте напомнит awaiting-джоба
        await self._reply(msg, wait_ack_for(state.funnel))
        state.wait_ack_sent = True
        await store.save(state)

    # ---- лог панели (сбои глушим, чтобы не ронять бота) ----
    async def _log_in(self, msg: Message, text: str) -> None:
        try:
            panel = get_conversation_store()
            await panel.add_message(self._key(msg), "client", text, channel=msg.channel,
                                    bot_id=self._bot_id, chat_id=msg.chat_id, phone=msg.user_id)
            if self.bot is not None:
                await panel.update_meta(self._key(msg), funnel=self.bot.scenario)
            if msg.referral:
                # Источник виден менеджеру сразу (даже при выключенном боте/перехвате); store — write-once.
                await panel.update_meta(
                    self._key(msg),
                    source=("post" if msg.referral.get("source_type") == "post" else "ad"),
                    source_id=msg.referral.get("source_id", ""),
                    source_headline=msg.referral.get("headline", ""),
                    source_url=msg.referral.get("source_url", ""),
                    source_payload=msg.referral,
                )
            # WP1B shadow bridge (flag-gated, default OFF, fail-safe). Awaited inside
            # this best-effort block; the bridge also swallows its own errors, so a
            # shadow write can never disturb the live dialog.
            from app.domain import shadow_bridge
            await shadow_bridge.mirror_inbound(
                phone=msg.user_id, channel=msg.channel, bot_id=self._bot_id,
                direction=(self.bot.scenario if self.bot is not None else ""))
            # WP2 messaging shadow (separate flag `messaging_shadow_enabled`, default OFF,
            # fail-safe). Records the inbound into the domain ledgers only; NOT wired into
            # live delivery and does NOT touch the Bitrix mirror.
            from app.domain import messaging_shadow
            _ev = str(msg.raw.get("id") or msg.raw.get("message_id")
                      or msg.raw.get("msg_id") or "")
            await messaging_shadow.mirror_inbound_message(
                phone=msg.user_id, channel=msg.channel, bot_id=self._bot_id,
                direction=(self.bot.scenario if self.bot is not None else ""),
                body=text, provider_msg_id=_ev, external_event_id=_ev)
            # Sprint 2: авто-назначение визового лида (флаг visa_autoassign_enabled,
            # default OFF, fail-safe). Закрепляет владельца, бота НЕ перехватывает.
            from app.domain import autoassign
            await autoassign.maybe_autoassign(
                phone=msg.user_id, channel=msg.channel,
                direction=(self.bot.scenario if self.bot is not None else ""),
                user_id=self._key(msg))
        except Exception:  # noqa: BLE001 — лог не критичен для диалога
            log.warning("panel log_in failed", exc_info=True)
        # Зеркало в Bitrix (best-effort, фоном — не блокирует и не роняет обработку).
        from app.integrations.crm import bitrix_mirror
        bitrix_mirror.fire(self._key(msg), sender="client", text=text, phone=msg.user_id,
                           funnel=self.bot.scenario if self.bot else None)

    async def _reply(self, msg: Message, text: str) -> None:
        # Логируем исходящее как pending → шлём → отмечаем доставку (sent/failed).
        panel = get_conversation_store()
        msg_id = 0
        try:
            msg_id = await panel.add_message(self._key(msg), "bot", text,
                                             channel=msg.channel, bot_id=self._bot_id,
                                             status="pending", phone=msg.user_id)
        except Exception:  # noqa: BLE001
            log.warning("panel log_out failed", exc_info=True)
        try:
            provider = await self.channel.send(msg.chat_id, text)
            mark_own(provider)
            if msg_id:
                await panel.mark_message_status(message_id=msg_id, status="sent",
                                                set_provider_msg_id=(provider or None))
            # Зеркало ответа бота в Bitrix — только после успешной отправки клиенту (best-effort, фоном).
            from app.integrations.crm import bitrix_mirror
            bitrix_mirror.fire(self._key(msg), sender="bot", text=text, phone=msg.user_id,
                               funnel=self.bot.scenario if self.bot else None)
            # WP2 messaging shadow outbound (flag `messaging_shadow_enabled`, default OFF,
            # fail-safe). Records the outbound into the domain ledgers only; NOT wired into
            # live delivery and does NOT touch the Bitrix mirror above.
            from app.domain import messaging_shadow
            await messaging_shadow.mirror_outbound_message(
                phone=msg.user_id, channel=msg.channel, bot_id=self._bot_id,
                direction=(self.bot.scenario if self.bot is not None else ""),
                body=text, idempotency_key=(provider or ""),
                provider_msg_id=(provider or ""), status="sent")
        except Exception:  # noqa: BLE001 — сбой канала: помечаем failed, диалог не роняем
            record_failure("send")
            if msg_id:
                try:
                    await panel.mark_message_status(message_id=msg_id, status="failed")
                except Exception:  # noqa: BLE001
                    pass
            log.warning("bot send failed (channel=%s)", msg.channel, exc_info=True)

    async def _sync_card(self, msg: Message, state) -> None:
        try:
            panel = get_conversation_store()
            brief = build_manager_brief(state)
            readiness = compute_readiness(state)
            await panel.update_meta(self._key(msg), funnel=state.funnel, stage=state.stage,
                                    qualification=state.qualification,
                                    outcome=_auto_outcome(state.stage), **brief, **readiness)
        except Exception:  # noqa: BLE001
            log.warning("panel sync_card failed", exc_info=True)

    async def _maybe_persona_greeting(self, msg: Message, state, store) -> bool:
        """Send deterministic persona greeting for a first bare greeting. Fail open."""
        try:
            if state.history:
                return False
            if state.pending_field:
                return False

            from app.core.branding import ad_greeting, persona_greeting
            from app.core.faq import is_bare_greeting

            if not is_bare_greeting(msg.text):
                return False
            # Пришёл по рекламе → контекстное приветствие (подтверждаем оффер, не спрашиваем с нуля).
            greeting = ad_greeting(state.funnel, state.manager_name,
                                   (state.ad_referral or {}).get("headline", "")) \
                or persona_greeting(state.funnel, state.manager_name)
            if not greeting:
                return False

            state.history.append({"role": "user", "content": msg.text})
            state.history.append({"role": "assistant", "content": greeting})
            await store.save(state)
            await self._sync_card(msg, state)
            await self._reply(msg, greeting)
            return True
        except Exception:  # noqa: BLE001
            log.warning("persona greeting failed", exc_info=True)
            return False

    async def _maybe_faq_reply(self, msg: Message, state, store) -> bool:
        """Try deterministic FAQ before LLM/funnel logic. Fail open to the normal flow."""
        if state.funnel == "visa":
            try:
                from app.core.visa_pricing import self_visa_reply, visa_price_reply
                answer = visa_price_reply(msg.text)
                if answer is None:
                    answer = self_visa_reply(
                        msg.text,
                        already_sent=bool(state.qualification.get("self_visa_retention_sent")),
                    )
                    if answer and state.qualification.get("self_visa_retention_sent"):
                        state.stage = "manager"
                        state.intercepted = True
                    elif answer:
                        state.qualification["self_visa_retention_sent"] = True
                if answer:
                    state.history.append({"role": "user", "content": msg.text})
                    state.history.append({"role": "assistant", "content": answer})
                    await store.save(state)
                    await self._sync_card(msg, state)
                    await self._reply(msg, answer)
                    return True
            except Exception:  # noqa: BLE001
                log.warning("visa deterministic reply failed", exc_info=True)

        try:
            from app.core.faq import get_faq_store, match_faq, qualification_question
            faq_store = get_faq_store()
            entries = await faq_store.candidates(state.funnel)
            faq = match_faq(
                msg.text, state.funnel, entries, pending_field=state.pending_field
            )
        except Exception:  # noqa: BLE001
            log.warning("faq lookup failed", exc_info=True)
            return False
        if faq is None:
            return False

        answer = faq.answer
        # При хендоффе бот замолкает — не дописываем вопрос анкеты после прощальной фразы.
        if state.pending_field and faq.allow_during_qualification and not faq.handoff_only:
            pending_question = qualification_question(state.funnel, state.pending_field)
            if pending_question:
                answer = f"{answer}\n\n{pending_question}"

        if faq.handoff_only:
            state.stage = "manager"
            state.intercepted = True

        state.history.append({"role": "user", "content": msg.text})
        state.history.append({"role": "assistant", "content": answer})
        await store.save(state)
        await self._sync_card(msg, state)
        await self._reply(msg, answer)
        return True
