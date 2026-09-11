"""Алерт «клиент ждёт живого менеджера».

После хендоффа/перехвата бот в диалоге молчит (решение заказчика). Но если менеджер не
подключается, а клиент продолжает писать — лид тихо теряется. В проде это наблюдали:
серьёзные клиенты (билеты Бишкек→Милан, виза в Германию) писали по 15+ сообщений в пустоту
и не получали ответа. Эта джоба замечает такие диалоги и пингует команду в WhatsApp, чтобы
человек подключился. Анти-дребезг — cooldown по диалогу.

`select_awaiting_targets` — чистая функция отбора (тестируемо). `run` — джоба планировщика.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone

from app.channels import outbound
from app.config import settings
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("awaiting")

# Стадии «у человека»: бот здесь молчит, ответить должен менеджер.
_HANDOFF_STAGES = {"manager", "manager_handoff"}
_TERMINAL_OUTCOMES = {"won", "lost"}

# Время последнего алерта по диалогу (in-memory; сбрасывается при рестарте — ок).
# Словарь общий для обоих адресатов намеренно: менеджер должен получить одно
# напоминание на диалог, а не по одному от каждого канала доставки.
_alerted: dict[str, float] = {}

FLAG = "awaiting_telegram_enabled"

# Прощание — не ожидание ответа. Живой прогон 11.09: в первом же тике 3 из 8
# напоминаний были ложными («Удачи вам», «Спасибо 🌸🌸🌸», автоответ чужой фирмы).
# Фильтр намеренно узкий: реплика должна СОСТОЯТЬ из вежливости, а не содержать её.
# «Спасибо, а на 5 ночей есть?» — живой разговор, и промолчать тут дороже, чем
# лишний раз дёрнуть менеджера.
_CLOSING = re.compile(
    r"^(?:спасибо\w*|благодар\w+|удачи|всего\s+добр\w+|до\s+свидан\w+|пока|"
    r"хорошо\s+спасибо|"
    r"хорошо|ок|окей|ладно|понятн\w*|понял\w*|поняла|ясно|принял\w*|"
    r"thanks?|thank\s+you|ok|okay)(?:\s+(?:вам|тебе|большое|огромное))*$",
    re.IGNORECASE,
)
# Автоответ чужой компании: наш номер написал в другую фирму (или клиент переслал).
# Это не клиент, который ждёт, — менеджеру там делать нечего.
_FOREIGN_BOT = re.compile(
    r"спасибо\s+за\s+обращение|ваше\s+обращение\s+принято|чем\s+могу\s+помочь\s*\?*$|"
    r"мы\s+ответим\s+вам|оператор\s+ответит",
    re.IGNORECASE,
)


def _is_closing(text: str) -> bool:
    """Реплика закрывает разговор, а не ждёт ответа."""
    clean = str(text or "").strip()
    if not clean:
        return False                      # голосовое/картинка без текста — это ожидание
    if _FOREIGN_BOT.search(clean):
        return True
    # Снимаем эмодзи и знаки, чтобы «Спасибо 🌸🌸🌸» и «Спасибо!» считались одинаково.
    bare = re.sub(r"[^\w\s]", " ", clean, flags=re.UNICODE)
    bare = re.sub(r"\s+", " ", bare).strip()
    return bool(_CLOSING.match(bare))
# Сколько диалогов поднимаем за тик. Замер 11.09: в хвосте 196 ждущих клиентов, и
# первое же включение вывалило бы их менеджеру пачкой. «Главное, чтобы их это не
# доставало» (встреча 29.07) — ограничение того же рода, что CATCHUP_CAP у заявок.
TELEGRAM_CAP = 8


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def select_awaiting_targets(convs: list, now: datetime, cfg) -> list:
    """Диалоги, где клиент ждёт ответа человека дольше порога.

    Условие: диалог передан человеку (стадия manager/handoff ИЛИ менеджер перехватил),
    последним писал КЛИЕНТ (никто не ответил), исход не финальный, и с последнего
    сообщения прошло больше cfg.alert_awaiting_minutes.
    """
    now = _aware(now)
    cutoff = now - timedelta(minutes=cfg.alert_awaiting_minutes)
    out = []
    for c in convs:
        handed_off = (c.stage in _HANDOFF_STAGES) or c.intercepted
        if not handed_off:
            continue
        if c.last_sender != "client":
            continue                       # уже ответил бот/менеджер — клиент не ждёт
        if c.outcome in _TERMINAL_OUTCOMES:
            continue
        last = _aware(c.last_message_at)
        if last is None or last > cutoff:
            continue                       # ещё не намолчался
        out.append(c)
    return out


def select_telegram_targets(convs: list, now: datetime, cfg) -> list:
    """То же, что `select_awaiting_targets`, но с двумя границами под личный пуш.

    Личный телеграм менеджера — канал дорогой: он звонит в кармане. Поэтому сюда
    попадает только то, по чему ещё есть смысл звонить:

    * не старше `awaiting_max_age_hours` — недельный лид уже мёртв, напоминание по
      нему только злит (то же правило, что в догоняющей отправке заявок);
    * не больше `TELEGRAM_CAP` за тик, самые свежие первыми — накопленный хвост
      разбирается за несколько тиков, а не одним залпом.
    """
    targets = select_awaiting_targets(convs, now, cfg)
    max_age = timedelta(hours=float(getattr(cfg, "awaiting_max_age_hours", 24)))
    fresh = [c for c in targets
             if _aware(c.last_message_at) is not None
             and _aware(c.last_message_at) >= _aware(now) - max_age
             and not _is_closing(getattr(c, "last_text", ""))
             and not _pinged_recently(c, now, cfg)]
    fresh.sort(key=lambda c: _aware(c.last_message_at), reverse=True)
    return fresh[:TELEGRAM_CAP]


def _pinged_recently(conv, now: datetime, cfg) -> bool:
    """Напоминали недавно? Отметка лежит в карточке и переживает рестарт."""
    last = _aware(getattr(conv, "awaiting_pinged_at", None))
    if last is None:
        return False
    cooldown = timedelta(minutes=float(getattr(cfg, "alert_cooldown_minutes", 60)))
    return last > _aware(now) - cooldown


async def _remember_ping(user_id: str, moment: datetime) -> None:
    """Записать отметку. Сбой записи не должен ронять рассылку — но и молчать нельзя:
    без отметки клиент получит второе напоминание, и это видно в логе."""
    try:
        await get_conversation_store().update_meta(user_id, awaiting_pinged_at=moment)
    except Exception:  # noqa: BLE001
        log.warning("awaiting: отметка о напоминании не записана (key=%s)", user_id,
                    exc_info=True)


async def _all_conversations() -> list:
    """Отдельной функцией — это шов для теста (хранилище в тесте не поднимаем)."""
    return await get_conversation_store().all_conversations()


def render_awaiting_text(conv, minutes: int) -> str:
    """Текст пуша. Сколько ждёт и что спросил — чтобы менеджер решал, не открывая панель."""
    from app.core.calendar_brief import _client_link, _phone_display
    who = _phone_display(getattr(conv, "phone", "") or conv.user_id)
    name = ((getattr(conv, "qualification", None) or {}).get("name") or "").strip()
    head = f"⏳ Клиент ждёт вас {minutes} мин"
    lines = [head, " · ".join(x for x in (name, who) if x) or "клиент без имени"]
    last = (getattr(conv, "last_text", "") or "").strip().replace("\n", " ")
    if last:
        lines.append(f"Последнее от клиента: «{last[:180]}»")
    link = _client_link(conv.user_id, settings.admin_base_url)
    if link:
        lines.append(f"👉 открыть диалог: {link}")
    return "\n".join(lines)


async def _push_owner(login: str, text: str, conv) -> bool:
    """Личный телеграм владельца диалога; ничей диалог — копия владельцу бизнеса.

    Переиспользуем доставку мгновенной заявки: она проверена живьём, медиана реакции
    по ней 19 минут за последние 28 дней. Заводить второй путь ради того же адресата
    незачем.
    """
    from app.core.calendar_brief import _push_telegram, _token
    from app.core.instant_handoff import _chat_id_for, _send_cc

    token = _token()
    if not token:
        return False
    chat_id = _chat_id_for(login) if login else ""
    if chat_id:
        return await _push_telegram(token, chat_id, text)
    # Владельца нет — молчать нельзя: именно ничейные диалоги и теряются.
    return await _send_cc(text, owner_login=login or "—")


async def run_telegram(*, now: datetime | None = None, cfg=None) -> int:
    """Джоба: напомнить владельцу о клиенте, который ждёт живого человека.

    Возвращает число отправленных напоминаний. Никогда не поднимает исключение:
    сторож не имеет права ронять тик планировщика.
    """
    try:
        from app.core import flags
        cfg = cfg or settings
        if not await flags.get_flag("alerts_enabled", True):
            return 0
        if not await flags.get_flag(FLAG, getattr(cfg, "awaiting_telegram_enabled", False)):
            return 0
        now_dt = _aware(now) or datetime.now(timezone.utc)
        targets = select_telegram_targets(await _all_conversations(), now_dt, cfg)
        cooldown = float(getattr(cfg, "alert_cooldown_minutes", 60)) * 60
        stamp = now_dt.timestamp()
        sent = 0
        for c in targets:
            if stamp - _alerted.get(c.user_id, 0.0) < cooldown:
                continue
            minutes = int((now_dt - _aware(c.last_message_at)).total_seconds() // 60)
            login = (getattr(c, "assigned_to", "") or "").strip()
            try:
                if await _push_owner(login, render_awaiting_text(c, minutes), c):
                    _alerted[c.user_id] = stamp
                    await _remember_ping(c.user_id, now_dt)
                    sent += 1
                    log.warning("awaiting: напомнили %s по диалогу %s (%d мин)",
                                login or "владельцу бизнеса", c.user_id, minutes)
            except Exception:  # noqa: BLE001 — один сбой не останавливает рассылку
                log.error("awaiting: напоминание не ушло (key=%s)", c.user_id, exc_info=True)
        return sent
    except Exception:  # noqa: BLE001
        log.warning("awaiting telegram failed", exc_info=True)
        return 0


async def run() -> None:
    """Джоба планировщика: пингнуть команду по брошенным после хендоффа клиентам."""
    from app.core import flags
    if not await flags.get_flag("alerts_enabled", True):
        return  # выключено тумблером в админке
    if not settings.alert_whatsapp_to or not settings.alert_bot_id:
        return  # алерты не настроены (нет номера/бота)

    now_dt = datetime.now(timezone.utc)
    targets = select_awaiting_targets(
        await get_conversation_store().all_conversations(), now_dt, settings)
    now = time.time()
    cooldown = settings.alert_cooldown_minutes * 60
    for c in targets:
        if now - _alerted.get(c.user_id, 0.0) < cooldown:
            continue                       # уже пинговали недавно по этому диалогу
        mins = int((now_dt - _aware(c.last_message_at)).total_seconds() // 60)
        who = c.phone or c.user_id
        text = (f"⏳ Клиент {who} ждёт ответа менеджера ~{mins} мин "
                f"(воронка: {c.funnel or '—'}). Зайдите в панель и ответьте, "
                f"чтобы не потерять лид.")
        try:
            await outbound.send_to_client("whatsapp", settings.alert_bot_id,
                                          settings.alert_whatsapp_to, text)
            _alerted[c.user_id] = now
            log.warning("awaiting alert sent for %s (%d min)", c.user_id, mins)
        except Exception:  # noqa: BLE001 — один сбой не должен останавливать рассылку
            log.error("awaiting alert send failed for %s", c.user_id, exc_info=True)
