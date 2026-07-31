"""Подтягиваем ответы менеджеров, отправленные с телефона, в панель.

Зачем. 31.07.2026 Гриша спросил: «если диалог перехватили, почему он до сих пор ждёт
ответа?». Разбор: колонка «ждёт ответа» снимается ответом менеджера — но за неделю в базе
оказалось НОЛЬ сообщений с `sender='manager'` при 980 клиентских. Менеджеры отвечают со
своих телефонов, а профиль Wappi подписан только на `incoming_message` (проверено:
`webhook_types = [incoming_message, delivery_status, authorization_status]`), поэтому эхо
исходящих до нас не долетает. Последствия: перехваченный диалог висит «ждёт ответа» вечно,
алерт «клиент ждёт живого менеджера» дёргает впустую, а в панели переписка неполная —
виден вопрос клиента, но не виден ответ.

Правильное лечение — включить тип вебхука в кабинете Wappi. Этот модуль решает две задачи,
которых галочка не закрывает: **чинит уже накопившееся прошлое** (галочка работает только
вперёд) и страхует, если её забудут проставить на новом профиле.

Как отличаем ответ менеджера от сообщения бота — без эвристик по тексту:
берём только исходящие, которые НОВЕЕ последнего сообщения в диалоге. Диалог попадает в
обработку, лишь когда последним писал клиент, — значит после него мы не записали ничего,
и любое исходящее позже этой отметки написал человек. Свои отправки бот пишет сам и с
`provider_msg_id`, так что перепутать нечего.

Повторный запуск безопасен: каждое подтянутое сообщение помечается ключом `wappi:<id>`,
дедуп идёт по нему.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.channels.wappi import WappiAdapter, is_manager_reply, message_time
from app.config import settings

log = logging.getLogger("manager_sync")

# Стадии «у человека»: здесь бот молчит и отвечать должен менеджер (как в awaiting.py).
_HANDOFF_STAGES = ("manager", "manager_handoff")
# Глубина разбора: старее — уже не рабочая лента, а архив.
LOOKBACK_DAYS = 14
# Сколько диалогов обрабатываем за прогон: у Wappi суточный лимит запросов, а джоба
# крутится каждые 5 минут — незачем выгребать всё подряд.
BATCH = 25
# Один и тот же ждущий диалог не опрашиваем чаще этого: пока менеджер не ответил, он
# остаётся в выборке, и без кулдауна мы дёргали бы Wappi по нему каждые 5 минут.
# In-memory (как `_alerted` в awaiting.py): сброс при рестарте безвреден.
RECHECK_MINUTES = 30
_checked: dict[int, datetime] = {}

FLAG = "manager_sync_enabled"


def _adapters() -> dict[str, WappiAdapter]:
    """Свой адаптер на каждого бота: profile_id у каждого номера собственный."""
    return {b.id: WappiAdapter(bot=b) for b in settings.bots if b.wappi_profile_id}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def select_missing_replies(raw_messages: list[dict], *, after: datetime,
                           known_ids: set[str]) -> list[dict]:
    """Исходящие человека новее отметки `after`, которых у нас ещё нет. Старое → новое."""
    cutoff = int(_aware(after).timestamp()) if after else 0
    out = []
    for raw in raw_messages:
        if not is_manager_reply(raw):
            continue
        if message_time(raw) <= cutoff:
            continue                       # не новее последнего сообщения клиента
        if str(raw.get("id") or "") in known_ids:
            continue                       # уже записано (наше или подтянутое раньше)
        out.append(raw)
    return sorted(out, key=message_time)


async def sync_conversation(session, conv, adapter: WappiAdapter) -> int:
    """Подтянуть пропущенные ответы менеджера в один диалог. Вернуть, сколько добавлено."""
    from app.integrations.crm.db import ConvMessage

    phone = (conv.phone or conv.user_id or "").split(":")[-1]
    if not phone:
        return 0
    raw_messages = await adapter.fetch_chat_messages(phone)
    if not raw_messages:
        return 0

    known = {row for row in (await session.execute(
        select(ConvMessage.provider_msg_id).where(ConvMessage.conversation_id == conv.id)
    )).scalars().all() if row}
    known |= {row.split("wappi:", 1)[1] for row in (await session.execute(
        select(ConvMessage.idempotency_key).where(ConvMessage.conversation_id == conv.id)
    )).scalars().all() if row and row.startswith("wappi:")}

    missing = select_missing_replies(raw_messages, after=_aware(conv.last_message_at),
                                     known_ids=known)
    if not missing:
        return 0

    for raw in missing:
        msg_id = str(raw.get("id") or "")
        session.add(ConvMessage(
            conversation_id=conv.id,
            sender="manager",
            text=str(raw.get("body") or "").strip(),
            provider_msg_id=msg_id,
            idempotency_key=f"wappi:{msg_id}",
            # Время настоящее, а не «сейчас»: иначе в панели ответ недельной давности
            # всплывёт как свежий и перепутает сортировку рабочих списков.
            created_at=datetime.fromtimestamp(message_time(raw), tz=timezone.utc),
        ))

    newest = missing[-1]
    conv.last_sender = "manager"
    conv.last_text = str(newest.get("body") or "").strip()
    conv.last_message_at = datetime.fromtimestamp(message_time(newest), tz=timezone.utc)
    return len(missing)


async def run(*, sessionmaker=None, limit: int = BATCH, force: bool = False) -> dict:
    """Разобрать диалоги, которые числятся ждущими ответа. Точка для планировщика.

    `force` снимает кулдаун — для разового разбора накопившегося прошлого.
    """
    from app.core import flags
    from app.integrations.crm.db import Conversation, get_sessionmaker

    if not force and not await flags.get_flag(FLAG, True):
        return {"checked": 0, "fixed": 0, "added": 0}

    adapters = _adapters()
    if not adapters:
        return {"checked": 0, "fixed": 0, "added": 0}

    sm = sessionmaker or get_sessionmaker()
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    checked = fixed = added = 0
    async with sm() as session:
        convs = (await session.execute(
            select(Conversation)
            .where(Conversation.last_sender == "client",
                   Conversation.last_message_at >= since,
                   Conversation.bot_id.in_(list(adapters)))
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
        )).scalars().all()
        # Ждут ответа только те, кого забрал человек: либо перехват, либо стадия хендоффа.
        convs = [c for c in convs if c.intercepted or (c.stage or "") in _HANDOFF_STAGES]

        now = datetime.now(timezone.utc)
        cooldown = timedelta(minutes=RECHECK_MINUTES)
        for conv in convs:
            if not force and now - _checked.get(conv.id, datetime.min.replace(
                    tzinfo=timezone.utc)) < cooldown:
                continue                   # недавно смотрели, менеджер ещё не ответил
            _checked[conv.id] = now
            checked += 1
            try:
                n = await sync_conversation(session, conv, adapters[conv.bot_id])
            except Exception:  # noqa: BLE001 — один битый диалог не должен ронять прогон
                log.warning("manager_sync: диалог %s не разобран", conv.id, exc_info=True)
                continue
            if n:
                fixed += 1
                added += n
        await session.commit()

    if fixed:
        log.info("manager_sync: подтянуто %s ответов в %s диалогов (проверено %s)",
                 added, fixed, checked)
    return {"checked": checked, "fixed": fixed, "added": added}
