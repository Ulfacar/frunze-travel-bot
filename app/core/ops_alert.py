"""Технические Telegram-алерты владельцу, отдельно от клиентских карточек."""
from __future__ import annotations

import logging

from app.config import settings

log = logging.getLogger("ops_alert")


async def send(text: str) -> bool:
    """Отправить техсообщение всем адресатам; сбой алерта не влияет на боевой поток."""
    try:
        from app.core.calendar_brief import _push_telegram, _token
        token = _token()
        recipients = [str(item).strip() for item in settings.ops_alert_chat_ids if str(item).strip()]
        if not token or not recipients:
            return False
        sent = False
        for chat_id in recipients:
            sent = await _push_telegram(token, chat_id, text) or sent
        if sent:
            log.info("ops alert sent")
        return sent
    except Exception:  # noqa: BLE001 — мониторинг не имеет права уронить обработку клиента
        return False
