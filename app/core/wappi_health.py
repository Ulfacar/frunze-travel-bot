"""Детерминированный сторож каналов: спрашиваем Wappi, а не гадаем по тишине.

Сторож тишины (`channel_heartbeat.py`) неустраним по природе: молчащий живой канал и
мёртвый канал по длительности молчания неразличимы. Честная симуляция на 21 сутках
показала 2.5 ложных инцидента в сутки даже на смягчённых порогах 180/420.

А Wappi отвечает точно: `GET /api/sync/get/status` отдаёт `authorized` и `app_status`.
В поле `logouted_at` визового профиля стоит 03.08 09:06 — ровно та авария, которую мы
тогда 12 часов не замечали. Вопрос «авторизован ли профиль» надо задавать, а не выводить.

Два повода для тревоги:
  A. разлогин — `authorized != true` или `app_status != "open"`;
  B. подписка Wappi кончается — `payment_expired_at` ближе порога. Отвалившаяся подписка
     убивает канал молча, это уже было с TourVisor 06.07.

Сторож тишины остаётся предохранителем на 12 часов: статус Wappi не покрывает случай
«профиль жив, но вебхук до нас не доходит».

ТЗ и гейт: `docs/task-wappi-health-v3.md`, `tests/test_wappi_health.py`.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from app.config import settings
from app.core import flags

log = logging.getLogger("wappi_health")

_state: dict[str, float] = {}
_memory_counters: dict[str, tuple] = {}
_STATE_KEY = "wh:alert_state"
_STATE_TTL = 14 * 24 * 3600


def parse_wappi_time(value) -> float | None:
    """Разобрать время из ответа Wappi. Мусор и пустота → None, без исключений.

    Форматы с прода различаются в одном ответе: `payment_expired_at` приходит с `Z`,
    остальные поля — со смещением `+03:00`.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _name(bot_id: str) -> str:
    try:
        from app.core.bots import registry
        bot = next((b for b in registry.all() if b.id == bot_id), None)
        if bot and (bot.manager_name or bot.title):
            return f" ({bot.manager_name or bot.title})"
    except Exception:  # noqa: BLE001 — алерт важнее красивого имени
        pass
    return ""


def classify_gap(counter_now, counter_prev, our_inbound_moved: bool) -> str:
    """Почему по каналу тихо: «webhook» | «no_traffic» | «» (не знаем).

    Различие видно из того же ответа Wappi, что мы и так читаем. 08.08 уведомление по
    каналу Айсины советовало «проверь QR и вебхук», хотя и авторизация, и вебхук были
    в порядке: на номер просто перестали писать. Счётчик Wappi вырос за 19 часов на 9 —
    значит сообщения не терялись по дороге, их не было. Совет уводил в сторону.
    """
    if our_inbound_moved:
        return ""                       # до нас доходит — диагностировать нечего
    if counter_now is None or counter_prev is None:
        return ""                       # нет данных — молчим о причине, а не выдумываем
    return "webhook" if counter_now > counter_prev else "no_traffic"


def _logout_text(bot_id: str, status: dict, *, reminder: bool = False) -> str:
    """Совет обязан соответствовать причине.

    07.08 на `app_status: connecting` бот написал «отвалился, нужно заново отсканировать
    QR», хотя профиль был АВТОРИЗОВАН и просто переподключался. Сканировать было незачем.
    QR помогает ровно в одном случае — когда профиль не авторизован.
    """
    channel = f"{bot_id}{_name(bot_id)}"
    if not status.get("authorized"):
        if reminder:
            return (f"🔁 Напоминаю: канал {channel} так и не авторизован.\n"
                    f"Сообщения клиентов до нас не доходят.")
        return (f"🔴 Канал {channel} не авторизован — сообщения клиентов до нас не доходят.\n"
                f"Нужно заново отсканировать QR в профиле Wappi.")

    state = status.get("app_status")
    if reminder:
        return (f"🔁 Напоминаю: канал {channel} так и не поднялся — приложение всё ещё "
                f"в состоянии «{state}».")
    return (f"🔴 Канал {channel}: приложение в состоянии «{state}» — связь с WhatsApp "
            f"не восстановилась за 15 минут.\nПрофиль при этом авторизован, QR сканировать "
            f"НЕ нужно: он сам переподключается. Если состояние не уйдёт, пишем в Wappi.")


def _payment_text(bot_id: str, expires_at: float, now: float) -> str:
    when = datetime.fromtimestamp(expires_at, timezone.utc).strftime("%d.%m")
    days = int((expires_at - now) // 86400)
    tail = f"через {days} дн. ({when})" if days > 0 else f"уже истекла ({when})"
    return (f"🟡 Подписка Wappi по каналу {bot_id}{_name(bot_id)} {tail}.\n"
            f"Когда она кончится, канал умрёт молча — продлить заранее.")


def decide(now: float, statuses: dict[str, dict | None], state: dict, cfg) -> list[tuple[str, str]]:
    """Чистое решение: по каким каналам бить тревогу. Мутирует state.

    `statuses`: bot_id → ответ Wappi, либо None, если запрос не удался. None — молчим:
    тревога, вызванная нашей же сетевой ошибкой, обесценила бы все остальные.
    """
    if not getattr(cfg, "wappi_health_enabled", True):
        return []

    cooldown = getattr(cfg, "wappi_health_cooldown_minutes", 360) * 60
    warn_ahead = getattr(cfg, "wappi_payment_warn_days", 5) * 86400
    # Сколько нездоровых проб ПОДРЯД считаем аварией. 07.08 профиль getvisa провалился
    # на одной пробе и переавторизовался сам через 34 секунды; `authorized_at` у всех
    # профилей меняется по нескольку раз в сутки, то есть короткие провалы — штатное
    # поведение Wappi. Настоящий разлогин держится часами (03.08 — двенадцать).
    confirm = max(1, int(getattr(cfg, "wappi_health_confirm_ticks", 1)))
    alerts: list[tuple[str, str]] = []

    for bot_id, status in sorted(statuses.items()):
        if not isinstance(status, dict):
            continue

        reasons: dict[str, str] = {}
        streak_key = f"streak:{bot_id}"
        if not status.get("authorized") or str(status.get("app_status") or "") != "open":
            streak = state.get(streak_key, 0) + 1
            state[streak_key] = streak
            if streak >= confirm:
                reasons["logout"] = _logout_text(
                    bot_id, status, reminder=state.get(f"logout:{bot_id}") is not None)
        else:
            state.pop(streak_key, None)     # одна здоровая проба обнуляет счётчик
        expires_at = parse_wappi_time(status.get("payment_expired_at"))
        if expires_at is not None and expires_at - now <= warn_ahead:
            reasons["payment"] = _payment_text(bot_id, expires_at, now)

        # Поводы независимы: защёлка на разлогин не смеет заглушить подписку, иначе
        # про второй повод мы узнаем постфактум.
        for reason in ("logout", "payment"):
            key = f"{reason}:{bot_id}"
            if reason not in reasons:
                state.pop(key, None)          # повода нет → защёлка снимается
                continue
            last_alert = state.get(key)
            if last_alert and now - last_alert < cooldown:
                continue
            state[key] = now
            alerts.append((bot_id, reasons[reason]))

    return alerts


def open_incidents_from_state(state: dict) -> set[str]:
    """Каналы с открытой защёлкой разлогина — про них уже сказано.

    Счётчики проб (`streak:`) и предупреждения о подписке (`payment:`) сюда не входят:
    первое ещё не тревога, второе — не повод глушить сторожа тишины.
    """
    return {key.split(":", 1)[1] for key in state
            if key.startswith("logout:") and key.split(":", 1)[1]}


async def diagnoses() -> dict[str, str]:
    """Почему по каждому каналу тихо — для текста алерта сторожа тишины.

    Снимок счётчика Wappi храним между тиками и сравниваем заодно с нашей отметкой
    последнего входящего: выросло у них, но не у нас — теряется по дороге; не выросло
    нигде — на номер просто не пишут.
    """
    out: dict[str, str] = {}
    try:
        from app.core.bots import registry
        from app.core.channel_heartbeat import _load_last_seen
        last_seen = await _load_last_seen()
        for bot in registry.all():
            if not bot.wappi_profile_id:
                continue
            status = await fetch_status(bot.wappi_profile_id)
            counter = status.get("message_count") if isinstance(status, dict) else None
            prev_counter, prev_seen = await _counter_snapshot(bot.id)
            await _remember_counter(bot.id, counter, last_seen.get(bot.id))
            moved = bool(prev_seen and last_seen.get(bot.id) and last_seen[bot.id] > prev_seen)
            verdict = classify_gap(counter, prev_counter, moved)
            if verdict:
                out[bot.id] = verdict
    except Exception:  # noqa: BLE001 — без диагноза алерт уйдёт с нейтральным текстом
        log.warning("диагноз каналов не собран", exc_info=True)
    return out


async def _counter_snapshot(bot_id: str) -> tuple[int | None, float | None]:
    if settings.state_backend != "redis":
        return _memory_counters.get(bot_id, (None, None))
    try:
        from app.core.stt_metrics import _redis
        raw = await _redis().get(f"wh:msgcount:{bot_id}")
        if raw:
            counter, seen = json.loads(raw)
            return (int(counter) if counter is not None else None,
                    float(seen) if seen else None)
    except Exception:  # noqa: BLE001
        pass
    return (None, None)


async def _remember_counter(bot_id: str, counter, last_seen) -> None:
    _memory_counters[bot_id] = (counter, last_seen)
    if settings.state_backend != "redis":
        return
    try:
        from app.core.stt_metrics import _redis
        await _redis().set(f"wh:msgcount:{bot_id}",
                           json.dumps([counter, last_seen]), ex=_STATE_TTL)
    except Exception:  # noqa: BLE001
        return


async def open_incidents() -> set[str]:
    """То же, но из хранилища — чтобы сторож тишины не дублировал уже сказанное."""
    try:
        return open_incidents_from_state(await _state_load())
    except Exception:  # noqa: BLE001 — в худшем случае получим лишнее сообщение, не тишину
        return set()


async def fetch_status(profile_id: str) -> dict | None:
    """Статус профиля у Wappi. Любой сбой → None (сторож молчит, а не выдумывает)."""
    if not profile_id or not settings.wappi_token or not settings.wappi_base_url:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=settings.wappi_health_timeout_seconds) as client:
            resp = await client.get(
                f"{settings.wappi_base_url}/api/sync/get/status",
                params={"profile_id": profile_id},
                # Токен только в заголовке и никогда в лог.
                headers={"Authorization": settings.wappi_token},
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception:  # noqa: BLE001 — недоступность Wappi не повод для тревоги
        log.warning("статус профиля не прочитан (profile=%s)", profile_id)
        return None
    return payload if isinstance(payload, dict) else None


async def _state_load() -> dict:
    if settings.state_backend != "redis":
        return dict(_state)
    try:
        from app.core.stt_metrics import _redis
        raw = await _redis().get(_STATE_KEY)
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return {str(k): float(v) for k, v in loaded.items()}
    except Exception:  # noqa: BLE001
        log.warning("защёлка не прочитана, беру из памяти", exc_info=True)
    return dict(_state)


async def _state_save(state: dict) -> None:
    _state.clear()
    _state.update(state)
    if settings.state_backend != "redis":
        return
    try:
        from app.core.stt_metrics import _redis
        await _redis().set(_STATE_KEY, json.dumps(state), ex=_STATE_TTL)
    except Exception:  # noqa: BLE001
        return


async def run() -> None:
    """Джоба планировщика: спросить статус каждого профиля и позвать владельца."""
    if not await flags.get_flag("wappi_health_enabled", settings.wappi_health_enabled):
        return

    from app.core.bots import registry
    profiles = {bot.id: bot.wappi_profile_id for bot in registry.all() if bot.wappi_profile_id}
    if not profiles:
        return

    statuses: dict[str, dict | None] = {}
    for bot_id, profile_id in profiles.items():
        status = await fetch_status(profile_id)
        statuses[bot_id] = status
        # Пишем КАЖДУЮ нездоровую пробу, даже ту, что не дошла до тревоги: иначе разбирать
        # короткие провалы можно только по скриншоту из Telegram. Токена и телефона тут нет.
        if isinstance(status, dict) and (not status.get("authorized")
                                         or str(status.get("app_status") or "") != "open"):
            log.warning("проба нездорова: %s authorized=%s app_status=%s authorized_at=%s",
                        bot_id, status.get("authorized"), status.get("app_status"),
                        status.get("authorized_at"))

    state = await _state_load()
    alerts = decide(time.time(), statuses, state, settings)
    await _state_save(state)
    if not alerts:
        return

    from app.core import ops_alert
    for bot_id, text in alerts:
        log.error("WAPPI UNHEALTHY: %s", bot_id)
        await ops_alert.send(text)
