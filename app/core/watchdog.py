"""Watchdog-алерты: уведомляет админа в WhatsApp при тишине вебхуков или всплеске
сбоев (LLM/отправка). Запускается планировщиком раз в тик.

Решение о том, слать ли алерт, вынесено в чистую `decide()` (тестируемо). `run()`
обвязывает её состоянием и отправкой через outbound. Анти-дребезг — cooldown по типу.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from app.channels import outbound
from app.config import settings
from app.core import observ
from app.core.channel_heartbeat import _is_night
from app.core.morning_brief import BISHKEK_UTC_OFFSET

log = logging.getLogger("watchdog")

# Состояние между тиками: время последнего алерта по типу + база счётчика сбоев.
_state: dict[str, float] = {"alert_silence_ts": 0.0, "alert_fail_ts": 0.0, "fail_baseline": 0.0}


def decide(now: float, last_inbound_ago: float | None, snapshot: dict,
           state: dict, cfg, *, night: bool = False) -> list[tuple[str, str]]:
    """Чистое решение: какие алерты пора слать. Мутирует state (cooldown/база сбоев).

    `night` глушит только тишину вебхуков. Порог тишины — 30 минут, cooldown — час, а
    ночью клиенты не пишут часами: ожив сторож как есть, мы получали бы до десяти
    сообщений «бот не получал сообщений» каждую ночь. Шумного сторожа выключают, и тогда
    он хуже отсутствующего. Ночную смерть канала ловит сторож v3 (`wappi_health`): он
    спрашивает у Wappi статус профиля, а не считает молчание, и потому в темноте точнее.
    Всплеск сбоев ночью не глушим — это реальные ошибки, а не отсутствие трафика.
    """
    alerts: list[tuple[str, str]] = []
    cooldown = cfg.alert_cooldown_minutes * 60

    # 1) Тишина вебхуков: давно не было входящих.
    silence_limit = cfg.alert_silence_minutes * 60
    if not night and last_inbound_ago is not None and last_inbound_ago >= silence_limit:
        if now - state.get("alert_silence_ts", 0.0) >= cooldown:
            mins = int(last_inbound_ago // 60)
            alerts.append(("silence",
                           f"⚠️ Бот не получал сообщений ~{mins} мин. Проверьте Wappi/вебхуки."))
            state["alert_silence_ts"] = now

    # 2) Всплеск сбоев (LLM + отправка) за период.
    total = snapshot.get("llm_failures", 0) + snapshot.get("send_failures", 0)
    delta = total - state.get("fail_baseline", 0.0)
    if delta >= cfg.alert_fail_threshold and now - state.get("alert_fail_ts", 0.0) >= cooldown:
        alerts.append(("failures",
                       f"⚠️ {int(delta)} сбоев бота за период (LLM/отправка). "
                       f"Проверьте OpenRouter/Wappi."))
        state["alert_fail_ts"] = now
    state["fail_baseline"] = total  # база сдвигается каждый тик → измеряем дельту за тик

    return alerts


async def _telegram_enabled() -> bool:
    """Слать ли алерты сторожа в Telegram, когда WhatsApp-адресат не задан."""
    from app.core import flags
    return await flags.get_flag("watchdog_telegram_enabled",
                                settings.watchdog_telegram_enabled)


async def run() -> None:
    """Джоба планировщика: оценить состояние и при необходимости отправить алерт админу.

    Доставка. Замер 15.09: `ALERT_WHATSAPP_TO` и `ALERT_BOT_ID` на проде ПУСТЫ, поэтому
    сторож выходил первой же строкой и молчал — при живом Telegram-канале с двумя
    получателями, куда уже ходят balance_guard и сторож карточек. WhatsApp остаётся
    приоритетным адресом, если его когда-нибудь настроят; иначе — Telegram за тумблером.
    """
    from app.core import flags
    if not await flags.get_flag("alerts_enabled", True):
        return  # выключено тумблером в админке
    to_whatsapp = bool(settings.alert_whatsapp_to and settings.alert_bot_id)
    to_telegram = (not to_whatsapp) and await _telegram_enabled()
    if not to_whatsapp and not to_telegram:
        return  # адресата нет ни там, ни там — молчим, как и раньше
    hour = (datetime.now(timezone.utc) + timedelta(hours=BISHKEK_UTC_OFFSET)).hour
    alerts = decide(time.time(), observ.last_inbound_ago(), observ.snapshot(), _state,
                    settings, night=_is_night(hour, settings))
    for reason, text in alerts:
        try:
            if to_whatsapp:
                await outbound.send_to_client("whatsapp", settings.alert_bot_id,
                                              settings.alert_whatsapp_to, text)
            else:
                from app.core import ops_alert
                await ops_alert.send(text, key=f"watchdog:{reason}")
            log.error("ALERT[%s]: %s", reason, text)
        except Exception:  # noqa: BLE001
            log.error("watchdog alert send failed", exc_info=True)
