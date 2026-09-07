"""Память контроллера карточек: что он сделал, что застряло, когда встал.

Зачем это есть. 07.09.2026 догоняющий проход сутки подряд отдавал `moved: 0` при непустой
очереди — 27 карточек, уже уехавших дальше цели, занимали все 25 слотов лимита. Этого не
увидел никто: результат прогона уходил только в `log.info`, и дефект нашёлся лишь тогда,
когда владелец в третий раз пожаловался на карточки, а разработчик полез в логи руками.

Считаем за сутки (день катится в 00:00 по Бишкеку, как у остальных суточных счётчиков):

* `runs` — сколько прогонов контроллера было;
* `moved` / `dossiers` — сколько карточек сдвинуто и в скольких появилась сводка;
* `errors` — сбои при обращении к порталу;
* `waiting` — сколько карточек не влезло в лимит прошлого прогона (длина очереди);
* `conflicts` — расхождения, которые контроллер чинить не вправе и показывает человеку;
* `stall_runs` — сколько прогонов подряд очередь есть, а движения нет. Это и есть тот
  самый дефект, выраженный числом.

Механика (Redis + in-memory фолбэк, суточный ключ, TTL) намеренно повторяет
`tours_health.py` и `quota.py`: одна знакомая форма на все суточные счётчики.
Сбой хранилища молчит и ничего не роняет — счётчик не важнее работы контроллера.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import settings
from app.core.budget import _bishkek_day

log = logging.getLogger("pipeline_metrics")

_REDIS_TTL_SECONDS = 48 * 3600
_CONFLICT_TTL_SECONDS = 7 * 24 * 3600
_CONFLICT_LIMIT = 50            # больше в глазах человека всё равно не помещается
_MEM: dict[str, Any] = {}
_redis_client: Any | None = None

_FIELDS = ("runs", "scanned", "moved", "dossiers", "errors", "conflicts")
# Поля, которые описывают ПОСЛЕДНИЙ прогон, а не сумму за сутки: очередь длиной 30 не
# складывается сама с собой каждые десять минут — она просто такая сейчас.
_LAST_FIELDS = ("waiting", "stall_runs", "last_run_at")


def _key(field: str, day: str | None = None) -> str:
    return f"pipe:ctl:{day or _bishkek_day()}:{field}"


def _redis() -> Any:
    global _redis_client
    if _redis_client is None:
        from redis import asyncio as aioredis
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def _incr(field: str, amount: int = 1) -> None:
    if amount == 0:
        return
    if settings.state_backend == "redis":
        redis = _redis()
        key = _key(field)
        await redis.incrby(key, amount)
        await redis.expire(key, _REDIS_TTL_SECONDS)
    else:
        _MEM[_key(field)] = int(_MEM.get(_key(field), 0)) + amount


async def _set(field: str, value: float) -> None:
    if settings.state_backend == "redis":
        redis = _redis()
        key = _key(field)
        await redis.set(key, value, ex=_REDIS_TTL_SECONDS)
    else:
        _MEM[_key(field)] = value


async def _read(field: str, default: float = 0) -> float:
    if settings.state_backend == "redis":
        raw = await _redis().get(_key(field))
        return float(raw) if raw is not None else default
    return float(_MEM.get(_key(field), default))


async def note_run(stats: dict) -> None:
    """Запомнить один прогон контроллера. Никогда не поднимает исключение."""
    try:
        await _incr("runs")
        for field in ("scanned", "moved", "dossiers", "errors"):
            await _incr(field, int(stats.get(field, 0) or 0))
        waiting = int(stats.get("waiting", 0) or 0)
        moved = int(stats.get("moved", 0) or 0)
        await _set("waiting", waiting)
        await _set("last_run_at", time.time())
        # Очередь есть, а движения нет — считаем, сколько прогонов подряд это длится.
        # Пустая очередь обнуляет счётчик: делать было нечего, это не застревание.
        if waiting > 0 and moved == 0:
            await _incr("stall_runs")
        else:
            await _set("stall_runs", 0)
    except Exception:  # noqa: BLE001 — счётчик не важнее работы контроллера
        log.warning("pipeline_metrics: прогон не записан", exc_info=True)


async def note_conflict(kind: str, conv_key: str, *, detail: str = "") -> None:
    """Запомнить расхождение, которое контроллер чинить не вправе.

    Список держим коротким и с TTL: он нужен человеку «что посмотреть сегодня», а не как
    вечный журнал. Записываем и в суточный счётчик, и в список — счётчик для сторожа,
    список для экрана.
    """
    item = {"kind": kind, "conv_key": conv_key, "detail": detail, "at": time.time()}
    try:
        await _incr("conflicts")
        if settings.state_backend == "redis":
            redis = _redis()
            key = _key("conflict_list")
            await redis.lpush(key, json.dumps(item, ensure_ascii=False))
            await redis.ltrim(key, 0, _CONFLICT_LIMIT - 1)
            await redis.expire(key, _CONFLICT_TTL_SECONDS)
        else:
            items = _MEM.setdefault(_key("conflict_list"), [])
            items.insert(0, item)
            del items[_CONFLICT_LIMIT:]
    except Exception:  # noqa: BLE001
        log.warning("pipeline_metrics: расхождение не записано", exc_info=True)


async def conflicts() -> list[dict]:
    """Последние расхождения — для экрана. Пусто, если хранилище недоступно."""
    try:
        if settings.state_backend == "redis":
            raw = await _redis().lrange(_key("conflict_list"), 0, _CONFLICT_LIMIT - 1)
            return [json.loads(row) for row in raw]
        return list(_MEM.get(_key("conflict_list"), []))
    except Exception:  # noqa: BLE001
        log.warning("pipeline_metrics: список расхождений не прочитан", exc_info=True)
        return []


async def status() -> dict:
    """Снимок за сутки — для экрана и для сторожа."""
    try:
        values = {field: int(await _read(field)) for field in _FIELDS}
        values["waiting"] = int(await _read("waiting"))
        values["stall_runs"] = int(await _read("stall_runs"))
        values["last_run_at"] = await _read("last_run_at", 0.0)
    except Exception:  # noqa: BLE001
        log.warning("pipeline_metrics: снимок не собран", exc_info=True)
        values = {field: 0 for field in (*_FIELDS, *_LAST_FIELDS)}
    values["day"] = _bishkek_day()
    return values


def decide(now: float, snap: dict, state: dict, cfg: Any) -> list[str]:
    """Чистое решение: о чём сказать владельцу. Мутирует `state` (защёлки поводов).

    Поводы независимы и держат отдельные защёлки: застревание не должно заглушить
    сообщение об ошибках портала — про второе мы иначе узнаем постфактум.

    Пустая очередь при нулевом движении — НЕ повод. Контроллеру просто нечего было
    делать, и будить из-за этого значит приучить владельца отключать сторожа: ровно так
    07.08 сгорел сторож каналов, который слал 5.3 ложных тревоги в сутки.
    """
    if not getattr(cfg, "pipeline_controller_alert_enabled", False):
        return []

    cooldown = float(getattr(cfg, "pipeline_alert_cooldown_hours", 12)) * 3600
    out: list[str] = []

    def _fire(reason: str, text: str) -> None:
        last = state.get(reason)
        if last and now - float(last) < cooldown:
            return
        state[reason] = now
        out.append(text)

    waiting = int(snap.get("waiting", 0) or 0)
    stall = int(snap.get("stall_runs", 0) or 0)
    if waiting > 0 and stall >= int(getattr(cfg, "pipeline_stall_runs", 3)):
        _fire("stall", (f"🔴 Контроллер карточек не двигает очередь.\n"
                        f"Ждут движения: {waiting}, прогонов подряд без движения: {stall}.\n"
                        f"Карточки стоят на месте — смотри логи `pipeline catchup stats`."))
    else:
        state.pop("stall", None)        # поехал — защёлка снимается

    last_run = float(snap.get("last_run_at", 0) or 0)
    silence_hours = float(getattr(cfg, "pipeline_silence_hours", 2))
    if last_run and now - last_run > silence_hours * 3600:
        hours = int((now - last_run) // 3600)
        _fire("silent", (f"🔴 Контроллер карточек молчит {hours} ч — не отработал ни разу.\n"
                         f"Похоже, джоба встала. Карточки сейчас не обновляются."))
    else:
        state.pop("silent", None)

    errors = int(snap.get("errors", 0) or 0)
    if errors >= int(getattr(cfg, "pipeline_errors_per_day", 20)):
        _fire("errors", (f"🟡 Контроллер карточек: {errors} ошибок за сутки.\n"
                         f"Портал отвечает сбоями — часть карточек не обновилась."))
    else:
        state.pop("errors", None)

    conflicts_count = int(snap.get("conflicts", 0) or 0)
    if conflicts_count > 0:
        _fire("conflicts", (f"🟡 Расхождения по карточкам: {conflicts_count} за сутки.\n"
                            f"Стадия уехала назад или лид пропал — бот такое не чинит сам. "
                            f"Смотри «Карточки» в админке."))
    else:
        state.pop("conflicts", None)

    return out


async def run() -> None:
    """Точка для планировщика: посмотреть на себя и позвать человека, если встали."""
    from app.core import flags
    if not await flags.get_flag("pipeline_controller_alert_enabled",
                                settings.pipeline_controller_alert_enabled):
        return
    from app.core import ops_alert, wappi_health

    class _Cfg:
        pipeline_controller_alert_enabled = True
        pipeline_stall_runs = settings.pipeline_stall_runs
        pipeline_silence_hours = settings.pipeline_silence_hours
        pipeline_errors_per_day = settings.pipeline_errors_per_day
        pipeline_alert_cooldown_hours = settings.pipeline_alert_cooldown_hours

    # Защёлки поводов живут там же, где у сторожей каналов: одно хранилище на все алерты.
    state = await wappi_health._state_load()
    alerts = decide(time.time(), await status(), state, _Cfg)
    await wappi_health._state_save(state)
    for text in alerts:
        log.error("PIPELINE CONTROLLER: %s", text.splitlines()[0])
        await ops_alert.send(text, key="pipeline:controller")


def _reset_for_tests() -> None:
    _MEM.clear()
