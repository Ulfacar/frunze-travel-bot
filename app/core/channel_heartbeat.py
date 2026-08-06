"""Сторож живости КАЖДОГО канала по отдельности.

03.08 визовый WhatsApp лежал разлогиненным 12 часов, и алерта не было. Существующий
`watchdog.decide()` смотрит `observ.last_inbound_ago()` — агрегат по всем каналам:
пока хоть один жив, тишина не срабатывает. **Агрегат маскирует смерть части.**

Здесь — обратный детектор: смотрим на каждый `bot_id` отдельно. Старый сторож ловит
«легло ВСЁ», этот — «легла ЧАСТЬ». Один другого не заменяет, поэтому старый не тронут.

Человека в контуре нет вообще: сторож смотрит на факт входящих, а не на чью-то
дисциплину. По наблюдению из docs/venom-v2.md это единственный класс проверки,
который в этой организации замыкается сам — контур, требующий отдельного действия
менеджера, разомкнут по умолчанию (128 автозадач, закрытых ноль).

Гейт: `tests/test_channel_heartbeat.py`.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.core import flags

log = logging.getLogger("channel_heartbeat")

BISHKEK_UTC_OFFSET = 6

# Ключ в Redis живёт дольше самого долгого мыслимого простоя: отметка «когда канал
# был жив в последний раз» не должна протухать раньше, чем мы успеем её прочитать.
_LAST_SEEN_TTL = 14 * 24 * 3600

# Фолбэк для дева и тестов (state_backend != redis). В проде читаем из Redis, чтобы
# отметка пережила рестарт: иначе каждый деплой обнулял бы историю.
_memory_last_seen: dict[str, float] = {}

# Состояние между тиками планировщика: защёлка и время последнего алерта по каналу.
_state: dict[str, float] = {}

# Сколько молчим после старта процесса, прежде чем судить о каналах. Без этого первый
# же тик после деплоя объявил бы мёртвыми все каналы, по которым ещё не было трафика.
_STARTUP_GRACE_SECONDS = 15 * 60
_started_at = time.time()


def _is_night(bishkek_hour: int, cfg) -> bool:
    start = getattr(cfg, "channel_heartbeat_quiet_from", 22)
    end = getattr(cfg, "channel_heartbeat_quiet_to", 9)
    if start > end:                                  # окно через полночь
        return bishkek_hour >= start or bishkek_hour < end
    return start <= bishkek_hour < end


def _human(minutes: float) -> str:
    return f"{int(minutes)} мин" if minutes < 120 else f"{int(minutes // 60)} ч"


def decide(now: float, last_seen: dict[str, float | None], state: dict, cfg,
           *, bishkek_hour: int) -> list[tuple[str, str]]:
    """Чистое решение: по каким каналам пора бить тревогу. Мутирует state.

    Возвращает список `(bot_id, текст)`. Пустой список — всё в порядке.
    """
    if not getattr(cfg, "channel_heartbeat_enabled", True):
        return []

    limit_minutes = (cfg.channel_silence_night_minutes if _is_night(bishkek_hour, cfg)
                     else cfg.channel_silence_minutes)
    cooldown = getattr(cfg, "channel_alert_cooldown_minutes", 180) * 60
    alerts: list[tuple[str, str]] = []

    for bot_id, seen_at in sorted(last_seen.items()):
        if not seen_at:
            continue        # истории нет (новый бот / первые минуты) — судить не о чем
        silent_minutes = (now - seen_at) / 60

        if silent_minutes < limit_minutes:
            state.pop(f"alerted:{bot_id}", None)     # ожил → защёлка снимается
            continue

        # Один инцидент — один алерт; напоминание не чаще cooldown. Иначе при тике
        # в 5 минут суточный простой дал бы 288 сообщений, и сторожа отключат.
        last_alert = state.get(f"alerted:{bot_id}")
        if last_alert and now - last_alert < cooldown:
            continue
        state[f"alerted:{bot_id}"] = now

        alerts.append((bot_id, _text(bot_id, silent_minutes)))

    return alerts


def _text(bot_id: str, silent_minutes: float) -> str:
    name = ""
    try:
        from app.core.bots import registry
        bot = next((b for b in registry.all() if b.id == bot_id), None)
        name = f" ({bot.manager_name or bot.title})" if bot and (bot.manager_name or bot.title) else ""
    except Exception:  # noqa: BLE001 — алерт важнее красивого имени
        pass
    return (f"🔴 Канал {bot_id}{name} молчит {_human(silent_minutes)} — входящих нет.\n"
            f"Проверь профиль в Wappi: авторизация (QR) и адрес вебхука.")


async def note_inbound(bot_id: str) -> None:
    """Отметить, что по каналу пришло входящее. Никогда не роняет обработку клиента."""
    if not bot_id:
        return
    now = time.time()
    _memory_last_seen[bot_id] = now
    if settings.state_backend != "redis":
        return
    try:
        from app.core.stt_metrics import _redis
        await _redis().set(f"hb:last_inbound:{bot_id}", str(now), ex=_LAST_SEEN_TTL)
    except Exception:  # noqa: BLE001 — сторож не важнее ответа клиенту
        return


async def _load_last_seen() -> dict[str, float | None]:
    """Отметки по всем известным каналам. Redis приоритетнее памяти: переживает рестарт."""
    from app.core.bots import registry
    result: dict[str, float | None] = {
        bot.id: _memory_last_seen.get(bot.id) for bot in registry.all()}
    if settings.state_backend != "redis":
        return result
    try:
        from app.core.stt_metrics import _redis
        client = _redis()
        for bot_id in list(result):
            raw = await client.get(f"hb:last_inbound:{bot_id}")
            if raw:
                result[bot_id] = float(raw)
    except Exception:  # noqa: BLE001
        pass
    return result


async def run() -> None:
    """Джоба планировщика: проверить каналы и при необходимости позвать владельца."""
    if not await flags.get_flag("channel_heartbeat_enabled", settings.channel_heartbeat_enabled):
        return
    now = time.time()
    if now - _started_at < _STARTUP_GRACE_SECONDS:
        return      # после деплоя даём каналам показать трафик, иначе алерт на пустом месте

    local = datetime.now(timezone.utc) + timedelta(hours=BISHKEK_UTC_OFFSET)
    alerts = decide(now, await _load_last_seen(), _state, settings, bishkek_hour=local.hour)
    if not alerts:
        return

    from app.core import ops_alert
    for bot_id, text in alerts:
        log.error("CHANNEL DOWN: %s", bot_id)
        await ops_alert.send(text)
