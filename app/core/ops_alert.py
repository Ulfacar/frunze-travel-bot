"""Технические Telegram-алерты владельцу и заказчику, отдельно от клиентских карточек.

## Почему заказчику реже, чем владельцу (21.08.2026)

Заказчик попросил уведомлять его самого — «так проще». Простое «добавить второй chat_id»
дало бы ему порядка тридцати сообщений в месяц: замер августа показал два разлогина
Wappi, но каналы стояли 10 и 6 суток, а напоминание уходит раз в сутки — это 16 повторов
про два события, плюс до 15 про подписки трёх профилей.

Закон 5 `venom-v2`: шумного сторожа выключают, и тогда он хуже отсутствующего. Поэтому
первое сообщение о поводе получают все, а повторные — владелец по прежнему суточному
ритму, заказчик не чаще `owner_reminder_hours`. Первый id в `ops_alert_chat_ids` —
владелец, остальные — заказчики.

Вызов без `key` шлёт всем: это разовые события, у которых нет «повторов».
"""
from __future__ import annotations

import logging
import time

from app.config import settings

log = logging.getLogger("ops_alert")

_STATE_KEY = "ops:digest_state"


async def _push(token: str, chat_id: str, text: str) -> bool:
    """Одна отправка. Вынесено отдельной функцией — точка подмены в тестах."""
    from app.core.calendar_brief import _push_telegram
    return await _push_telegram(token, chat_id, text)


def _recipients() -> list[str]:
    return [str(item).strip() for item in settings.ops_alert_chat_ids if str(item).strip()]


def _due(state: dict, key: str, chat_id: str, now: float) -> bool:
    """Пора ли повторять этому заказчику по этому поводу."""
    hours = float(getattr(settings, "owner_reminder_hours", 72) or 0)
    if hours <= 0:
        return True
    last = state.get(f"{key}:{chat_id}")
    return not last or now - float(last) >= hours * 3600


async def _load_state() -> dict:
    from app.core.wappi_health import _state_load
    return await _state_load()


async def _save_state(state: dict) -> None:
    from app.core.wappi_health import _state_save
    await _state_save(state)


async def send(text: str, *, key: str = "", now: float | None = None,
               state: dict | None = None) -> bool:
    """Отправить техсообщение; сбой алерта не влияет на боевой поток.

    `key` — идентификатор повода (`logout:frunze_tours`, `balance:openrouter`). Задан —
    включается щадящий ритм для заказчиков. Не задан — сообщение уходит всем.
    """
    try:
        from app.core.calendar_brief import _token
        token = _token()
        recipients = _recipients()
        if not token or not recipients:
            return False

        moment = time.time() if now is None else float(now)
        external = state is not None
        digest = state if external else (await _load_state() if key else {})

        owner, customers = recipients[0], recipients[1:]
        targets = [owner]
        for chat_id in customers:
            if not key or _due(digest, key, chat_id, moment):
                targets.append(chat_id)

        sent = False
        for chat_id in targets:
            ok = await _push(token, chat_id, text)
            sent = ok or sent
            if ok and key and chat_id != owner:
                digest[f"{key}:{chat_id}"] = moment

        if key and not external:
            await _save_state(digest)
        if sent:
            log.info("ops alert sent")
        return sent
    except Exception:  # noqa: BLE001 — мониторинг не имеет права уронить обработку клиента
        log.warning("ops alert failed", exc_info=True)
        return False
