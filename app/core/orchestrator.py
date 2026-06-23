"""Оркестратор: принимает Message, ведёт диалог через нужную воронку, отвечает.

Параллельно ведёт персистентный лог диалога для админ-панели (карточка + сообщения):
входящие пишутся ВСЕГДА (в т.ч. при перехвате — чтобы менеджер видел новые реплики
клиента), исходящие — когда бот отвечает. Сбои лога не должны ронять ответ бота.
"""
from __future__ import annotations

import logging

from app.channels.base import ChannelAdapter, Message
from app.config import BotConfig
from app.core.manager_brief import build_manager_brief
from app.core.router import detect_funnel
from app.core.state import get_state_store
from app.funnels import get_funnel
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("orchestrator")

GREETING = (
    "Здравствуйте! 😊 Это Frunze Travel. "
    "Подскажите, что вас интересует — тур, виза или авиабилеты?"
)

NON_TEXT_FALLBACK = (
    "Пока я понимаю только текстовые сообщения 🙏 Напишите, пожалуйста, словами — "
    "или скажите «нужен менеджер», и я позову человека."
)


class Orchestrator:
    """Ведёт диалог одного бота. Если `bot` задан, его сценарий жёстко определяет
    воронку (тур-боты не угадывают её по ключевым словам). Без `bot` (дев-демо в
    Telegram) воронка определяется keyword-детектом, как раньше.
    """

    def __init__(self, channel: ChannelAdapter, bot: BotConfig | None = None) -> None:
        self.channel = channel
        self.bot = bot

    @property
    def _bot_id(self) -> str:
        return self.bot.id if self.bot else ""

    async def handle(self, msg: Message) -> None:
        if not msg.user_id:
            return  # служебный/пустой апдейт

        store = get_state_store()
        state = await store.load(msg.user_id)

        # Не-текст (голос/фото/медиа): бот пока не умеет — честный fallback.
        if msg.kind == "non_text":
            await self._log_in(msg, "[медиа/голос]")
            if state.intercepted:
                return  # перехвачено — лог записали, бот молчит
            await self._reply(msg, NON_TEXT_FALLBACK)
            return

        if not msg.text:
            return  # пустой апдейт без содержимого

        # Входящее логируем ВСЕГДА — даже если перехвачено (менеджер должен видеть).
        await self._log_in(msg, msg.text)

        # Перехват: бот молчит во всех воронках (сообщение клиента уже в логе).
        if state.intercepted:
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

        funnel = get_funnel(state.funnel)
        reply = await funnel.handle(msg, state)

        # Передача менеджеру = бот замолкает (решение заказчика 23.06.2026): прощальную
        # реплику этого хода ещё отправляем, но дальше в этом чате отвечает только человек.
        # Менеджер видит карточку в «У менеджера» и может «Вернуть боту» из панели.
        auto_handoff = state.stage == "manager"
        if auto_handoff:
            state.intercepted = True

        # Перехват «на лету»: менеджер мог нажать «Перехватить», пока генерировался ответ.
        # Перечитываем свежее состояние; если перехвачено не нами (не хендофф) — не отвечаем.
        fresh = await store.load(msg.user_id)
        intercepted_midflight = fresh.intercepted and not auto_handoff
        if intercepted_midflight:
            state.intercepted = True

        await store.save(state)
        await self._sync_card(msg, state)
        if reply and not intercepted_midflight:
            await self._reply(msg, reply)
        elif intercepted_midflight:
            log.info("reply dropped: intercepted mid-flight (user=%s)", msg.user_id)

    # ---- лог панели (сбои глушим, чтобы не ронять бота) ----
    async def _log_in(self, msg: Message, text: str) -> None:
        try:
            panel = get_conversation_store()
            await panel.add_message(msg.user_id, "client", text,
                                    channel=msg.channel, bot_id=self._bot_id, chat_id=msg.chat_id)
            if self.bot is not None:
                await panel.update_meta(msg.user_id, funnel=self.bot.scenario)
        except Exception:  # noqa: BLE001 — лог не критичен для диалога
            log.warning("panel log_in failed", exc_info=True)

    async def _reply(self, msg: Message, text: str) -> None:
        # Логируем исходящее как pending → шлём → отмечаем доставку (sent/failed).
        panel = get_conversation_store()
        msg_id = 0
        try:
            msg_id = await panel.add_message(msg.user_id, "bot", text,
                                             channel=msg.channel, bot_id=self._bot_id,
                                             status="pending")
        except Exception:  # noqa: BLE001
            log.warning("panel log_out failed", exc_info=True)
        try:
            provider = await self.channel.send(msg.chat_id, text)
            if msg_id:
                await panel.mark_message_status(message_id=msg_id, status="sent",
                                                set_provider_msg_id=(provider or None))
        except Exception:  # noqa: BLE001 — сбой канала: помечаем failed, диалог не роняем
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
            await panel.update_meta(msg.user_id, funnel=state.funnel, stage=state.stage,
                                    qualification=state.qualification, **brief)
        except Exception:  # noqa: BLE001
            log.warning("panel sync_card failed", exc_info=True)
