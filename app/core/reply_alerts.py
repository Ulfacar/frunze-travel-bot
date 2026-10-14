"""Личное напоминание владельцу диалога: клиент ждёт ответа дольше X (B2c, 14.10.2026).

Правило Гриши — «главное, чтобы их это не доставало»: одно напоминание на эпизод ожидания,
без повторов каждые 5 минут. Эпизод — с момента, когда клиент ждёт человека, до первого
ответа менеджера или бота. Отметка `conversations.reply_alert_at` ставится условным UPDATE
(дедуп в БД, переживает рестарт и гонку двух воркеров), а снимается хранилищем панели,
когда в диалог пишет не клиент (`add_message` с sender != client) — так следующее ожидание
становится новым эпизодом.

Ночью не шлём: ожидание считается в рабочих минутах (`reply_sla`), ночь не копится.
Ничьи диалоги (без владельца) не трогаем: адресата нет — это очередь `/admin/overdue`.
Флаг `pilot_reply_alert_enabled`, дефолт OFF. Текст без номера телефона клиента.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.config import settings
from app.core import reply_sla

log = logging.getLogger("reply_alerts")
FLAG = "pilot_reply_alert_enabled"


def _sm(sessionmaker=None):
    if sessionmaker is not None:
        return sessionmaker
    from app.integrations.crm.db import get_sessionmaker
    return get_sessionmaker()


def render(name: str, waited_minutes: float, user_id: str) -> str:
    from urllib.parse import quote
    base = (settings.admin_base_url or "").rstrip("/")
    link = f"{base}/admin?open={quote(user_id, safe='')}" if base else ""
    who = name or "Клиент"
    text = f"⏳ {who} ждёт вашего ответа уже {int(waited_minutes)} мин."
    return text + (f"\n{link}" if link else "")


async def _send(login: str, text: str) -> bool:
    from app.core.instant_handoff import _send as push
    return await push(login, text)


async def run(*, now: datetime | None = None, sessionmaker=None) -> int:
    """Один проход. Возвращает число отправленных напоминаний."""
    from app.core.flags import get_flag
    if not await get_flag(FLAG, settings.pilot_reply_alert_enabled):
        return 0
    from app.integrations.crm.db import Conversation
    now = now or datetime.now(timezone.utc)
    sm = _sm(sessionmaker)
    async with sm() as session:
        rows = (await session.execute(select(Conversation).where(
            Conversation.archived.is_not(True), Conversation.last_sender == "client",
            Conversation.reply_alert_at.is_(None), Conversation.assigned_to != ""))).scalars().all()
    from app.core.instant_handoff import _chat_id_for
    sent = 0
    for conv in rows:
        if not _chat_id_for(conv.assigned_to):
            continue                                  # адресата нет — не крутим отметку зря
        waited = reply_sla.waiting_minutes(conv, now)
        if waited is None or waited < settings.pilot_reply_sla_minutes:
            continue
        async with sm() as session:
            claimed = await session.execute(update(Conversation).where(
                Conversation.id == conv.id, Conversation.reply_alert_at.is_(None),
                Conversation.last_sender == "client", Conversation.last_message_at == conv.last_message_at,
            ).values(reply_alert_at=now))
            await session.commit()
        if not claimed.rowcount:
            continue                                  # уже напомнили или клиенту ответили
        name = (conv.qualification or {}).get("name") if isinstance(conv.qualification, dict) else ""
        ok = False
        try:
            ok = await _send(conv.assigned_to, render(name or "", waited, conv.user_id))
        except Exception:  # noqa: BLE001
            log.warning("reply alert send failed", exc_info=True)
        if ok:
            sent += 1
            continue
        # Не дошло (нет chat_id, Telegram недоступен) — отметку снимаем, попробуем позже.
        async with sm() as session:
            await session.execute(update(Conversation).where(Conversation.id == conv.id,
                                                             Conversation.reply_alert_at == now)
                                  .values(reply_alert_at=None))
            await session.commit()
    if sent:
        log.info("reply alerts sent=%d", sent)
    return sent
