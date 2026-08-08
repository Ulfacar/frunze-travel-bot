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

v2 (07.08): закрыта слепая зона. Отметка живости писалась только в момент входящего, и
канал, умерший ДО старта процесса, не проверялся вообще — сторож был слеп ровно к тому
состоянию, которое ищет. Теперь пустая отметка достраивается историей из БД
(`merge_baseline` + `_db_baseline`), защёлка переживает рестарт, пороги подняты по
замеру пауз за 14 дней. Разбор: `docs/task-channel-heartbeat-v2.md`.

Гейт: `tests/test_channel_heartbeat.py` (v1) + `tests/test_channel_heartbeat_v2.py`.
"""
from __future__ import annotations

import json
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
# Здесь оно только зеркалится: источник правды — Redis (см. _state_load/_state_save),
# иначе деплой посреди длящейся аварии давал бы владельцу дубль по тому же инциденту.
_state: dict[str, float] = {}

_STATE_KEY = "hb:alert_state"

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
           *, bishkek_hour: int, reported=frozenset(),
           diagnoses: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Чистое решение: по каким каналам пора бить тревогу. Мутирует state.

    Возвращает список `(bot_id, текст)`. Пустой список — всё в порядке.

    `reported` — каналы, про которые уже сказал детектор Wappi. Разлогин профиля это
    одновременно и «Wappi говорит: отвалился», и «входящих нет»; факт один, и сообщение
    про него должно быть одно.
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

        if bot_id in reported:
            continue        # про этот канал уже сказал детектор Wappi — не дублируем

        # Один инцидент — одно сообщение; напоминание не чаще cooldown (сутки). Иначе
        # при тике в 5 минут суточный простой дал бы 288 сообщений, и сторожа отключат.
        last_alert = state.get(f"alerted:{bot_id}")
        if last_alert and now - last_alert < cooldown:
            continue
        state[f"alerted:{bot_id}"] = now

        alerts.append((bot_id, _text(bot_id, silent_minutes,
                                     reminder=last_alert is not None,
                                     diagnosis=(diagnoses or {}).get(bot_id, ""))))

    return alerts


def _advice(diagnosis: str) -> str:
    """Совет по факту, а не один на все случаи.

    08.08 по каналу Айсины ушло «проверь профиль в Wappi: авторизация (QR) и адрес
    вебхука», хотя оба были в порядке — на номер просто перестали писать (новые диалоги
    13 → 4 → 8 → 3 → 1 → 0 при ровных соседних каналах). Совет увёл в сторону от
    настоящей причины, а она была не техническая.
    """
    if diagnosis == "webhook":
        return ("Сообщения в Wappi приходят, а до нас не доходят — смотри адрес вебхука "
                "у этого профиля.")
    if diagnosis == "no_traffic":
        return ("В Wappi по этому номеру тоже тихо — значит дело не в технике. "
                "Проверь, куда ведёт реклама, и не ограничен ли сам номер в WhatsApp.")
    return "Проверь профиль в Wappi: авторизация (QR) и адрес вебхука."


def _text(bot_id: str, silent_minutes: float, *, reminder: bool = False,
          diagnosis: str = "") -> str:
    name = ""
    try:
        from app.core.bots import registry
        bot = next((b for b in registry.all() if b.id == bot_id), None)
        name = f" ({bot.manager_name or bot.title})" if bot and (bot.manager_name or bot.title) else ""
    except Exception:  # noqa: BLE001 — алерт важнее красивого имени
        pass
    # Повтор обязан читаться как напоминание, а не как новое событие: иначе это то же
    # самое сообщение второй раз, а владелец просил ровно обратного.
    if reminder:
        return (f"🔁 Напоминаю: канал {bot_id}{name} так и молчит — уже "
                f"{_human(silent_minutes)}, входящих нет.\n{_advice(diagnosis)}")
    return (f"🔴 Канал {bot_id}{name} молчит {_human(silent_minutes)} — входящих нет.\n"
            f"{_advice(diagnosis)}")


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


def merge_baseline(last_seen: dict[str, float | None], baseline: dict[str, float],
                   now: float, max_age_seconds: float) -> dict[str, float | None]:
    """Дозаполнить пустые отметки историей из БД. Чистая функция.

    Отметка живости пишется только в момент входящего, поэтому канал, по которому с
    момента старта процесса не пришло ни одного сообщения, оставался без отметки — а
    `decide()` такие каналы пропускает. Итог: **сторож был слеп ровно к тому состоянию,
    которое ищет** — к каналу, который уже лежит. 07.08 в этой слепой зоне был
    `frunze_tours_sezim` с 641 входящим за неделю.

    Живую отметку baseline не трогает: она настоящая и свежее любой записи в логе.
    Слишком старую — игнорирует: канал без трафика неделю не «внезапно лёг», он выведен
    из работы, и вечный алерт по нему — тот же алерт-фатиг, от которого сторожа отключают.
    """
    merged = dict(last_seen)
    for bot_id, seen_at in merged.items():
        if seen_at:
            continue
        candidate = baseline.get(bot_id)
        if candidate and now - candidate <= max_age_seconds:
            merged[bot_id] = candidate
    return merged


def _sessionmaker_for_baseline():
    """Источник сессий для базовой отметки. Отдельной функцией — чтобы гейт мог подменить."""
    if settings.panel_backend != "postgres":
        return None
    from app.integrations.crm.db import get_sessionmaker
    return get_sessionmaker()


def _epoch(value) -> float | None:
    if not isinstance(value, datetime):
        return None
    # SQLite отдаёт наивную дату; считаем её UTC, иначе на сервере в CEST отметка
    # уехала бы на два часа и превратилась в ложную тревогу.
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.timestamp()


async def _db_baseline(bot_ids) -> dict[str, float]:
    """Время последнего КЛИЕНТСКОГО сообщения по каналам — база для пустых отметок.

    Сбой БД → пустой словарь (fail-open, молчим). Тревога «канал мёртв», вызванная
    падением нашего же запроса, обесценила бы все остальные.
    """
    ids = [bot_id for bot_id in bot_ids if bot_id]
    if not ids:
        return {}
    try:
        sessionmaker = _sessionmaker_for_baseline()
        if sessionmaker is None:
            return {}
        from sqlalchemy import func, select

        from app.integrations.crm.db import Conversation, ConvMessage
        stmt = (select(Conversation.bot_id, func.max(ConvMessage.created_at))
                .join(ConvMessage, ConvMessage.conversation_id == Conversation.id)
                .where(ConvMessage.sender == "client", Conversation.bot_id.in_(ids))
                .group_by(Conversation.bot_id))
        async with sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
    except Exception:  # noqa: BLE001 — сторож не имеет права шуметь из-за своей же БД
        log.warning("baseline из БД не прочитан", exc_info=True)
        return {}

    result: dict[str, float] = {}
    for bot_id, last_at in rows:
        moment = _epoch(last_at)
        if bot_id and moment:
            result[str(bot_id)] = moment
    return result


async def _remember(bot_id: str, moment: float) -> None:
    """Записать восстановленную отметку, чтобы не ходить в БД каждый тик."""
    _memory_last_seen[bot_id] = moment
    if settings.state_backend != "redis":
        return
    try:
        from app.core.stt_metrics import _redis
        await _redis().set(f"hb:last_inbound:{bot_id}", str(moment), ex=_LAST_SEEN_TTL)
    except Exception:  # noqa: BLE001
        return


async def _load_last_seen() -> dict[str, float | None]:
    """Отметки по всем известным каналам. Redis приоритетнее памяти: переживает рестарт."""
    from app.core.bots import registry
    result: dict[str, float | None] = {
        bot.id: _memory_last_seen.get(bot.id) for bot in registry.all()}
    if settings.state_backend == "redis":
        try:
            from app.core.stt_metrics import _redis
            client = _redis()
            for bot_id in list(result):
                raw = await client.get(f"hb:last_inbound:{bot_id}")
                if raw:
                    result[bot_id] = float(raw)
        except Exception:  # noqa: BLE001
            pass

    # Каналы, о которых мы пока ничего не знаем, — это и есть слепая зона. Спрашиваем БД.
    unknown = [bot_id for bot_id, seen_at in result.items() if not seen_at]
    if not unknown:
        return result

    max_age = getattr(settings, "channel_heartbeat_baseline_max_age_hours", 168) * 3600
    merged = merge_baseline(result, await _db_baseline(unknown), time.time(), max_age)
    for bot_id in unknown:
        recovered = merged.get(bot_id)
        if recovered:
            log.info("baseline восстановлен из БД: %s", bot_id)
            await _remember(bot_id, recovered)
    return merged


async def _state_load() -> dict:
    """Защёлка из хранилища. Копия: мутирует её `decide`, сохраняет `_state_save`."""
    if settings.state_backend != "redis":
        return dict(_state)
    try:
        from app.core.stt_metrics import _redis
        raw = await _redis().get(_STATE_KEY)
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                return {str(k): float(v) for k, v in loaded.items()}
    except Exception:  # noqa: BLE001 — без защёлки сторож шумит, но не слепнет
        log.warning("защёлка не прочитана, беру из памяти", exc_info=True)
    return dict(_state)


async def _state_save(state: dict) -> None:
    _state.clear()
    _state.update(state)
    if settings.state_backend != "redis":
        return
    try:
        from app.core.stt_metrics import _redis
        await _redis().set(_STATE_KEY, json.dumps(state), ex=_LAST_SEEN_TTL)
    except Exception:  # noqa: BLE001
        return


async def run() -> None:
    """Джоба планировщика: проверить каналы и при необходимости позвать владельца."""
    if not await flags.get_flag("channel_heartbeat_enabled", settings.channel_heartbeat_enabled):
        return
    now = time.time()
    if now - _started_at < _STARTUP_GRACE_SECONDS:
        return      # после деплоя даём каналам показать трафик, иначе алерт на пустом месте

    local = datetime.now(timezone.utc) + timedelta(hours=BISHKEK_UTC_OFFSET)
    state = await _state_load()
    # Про каналы, по которым Wappi уже сообщил о разлогине, молчим: факт один.
    from app.core import wappi_health
    reported = await wappi_health.open_incidents()
    # Почему тихо — спрашиваем у Wappi, а не советуем «проверь QR и вебхук» наугад.
    diagnoses = await wappi_health.diagnoses()
    alerts = decide(now, await _load_last_seen(), state, settings,
                    bishkek_hour=local.hour, reported=reported, diagnoses=diagnoses)
    # Сохраняем ДО проверки на пустоту: `decide` снимает защёлку с ожившего канала, и
    # эту отмену нужно записать не меньше, чем сам факт алерта.
    await _state_save(state)
    if not alerts:
        return

    from app.core import ops_alert
    for bot_id, text in alerts:
        log.error("CHANNEL DOWN: %s", bot_id)
        await ops_alert.send(text)
