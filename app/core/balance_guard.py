"""Сторож денег и доступности: баланс OpenRouter и живость портала Битрикса.

21.08.2026 бот замолчал на исходе баланса OpenRouter, и узнали об этом постфактум — от
клиента, а не от системы. Мониторинга не было вовсе: ключ есть, счёт есть, а спросить
остаток никто не догадался.

Устройство повторяет `wappi_health` намеренно: чистая функция решения отдельно от
запроса наружу. Так частоту срабатываний можно замерить на истории, не дёргая чужой API,
и так тревога не зависит от нашей же сетевой удачи.

## Два правила, оба выстраданы

**Порог считается в ДНЯХ остатка, а не в долларах.** «Осталось $5» ничего не говорит:
при визовом трафике это две недели, при туровом — четыре дня (туровый ход дороже
примерно вдесятеро, контекст длиннее). Человеку нужно знать, сколько у него времени.

**Сбой чужого API — молчание.** Тревога, вызванная нашей же сетевой ошибкой, обесценивает
все остальные: сторож, который кричит на каждый таймаут, выключается через неделю. Этот
закон унаследован от сторожа каналов, где он стоил трёх выкаток за сутки.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("balance_guard")

OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/auth/key"

# Пол суточного расхода: без него деление даёт бесконечный запас на мёртвом счёте, и
# тревога не приходит никогда. Ноль трат сутки — не повод считать, что денег хватит вечно.
_MIN_DAILY = 0.01


def _days_left(remaining: float, daily: float) -> float:
    return remaining / max(float(daily or 0.0), _MIN_DAILY)


def _balance_text(remaining: float, days: float) -> str:
    """Что человек с этим СДЕЛАЕТ — важнее, чем что случилось.

    Отрицательный остаток у OpenRouter возможен (овердрафт), но «осталось $-5.00, хватит
    на -5 дн.» человек читать не должен: у уже потраченного счёта запаса нет, так и пишем.
    """
    if remaining <= 0:
        return "\n".join([
            "OpenRouter: деньги закончились — бот сейчас не отвечает клиентам.",
            "Пополнить: openrouter.ai → Credits.",
        ])
    return "\n".join([
        f"OpenRouter: осталось ${remaining:.2f} — при нынешнем расходе "
        f"хватит примерно на {max(0, int(days))} дн.",
        "Когда закончится, бот перестанет отвечать клиентам.",
        "Пополнить: openrouter.ai → Credits.",
    ])


def decide(now: float, snapshot: dict | None, state: dict, cfg: Any) -> list[str]:
    """Чистое решение по балансу. Мутирует `state` (защёлка живёт в Redis).

    `snapshot`: `{"remaining": float, "daily": float}` либо None, если спросить не вышло.
    """
    if not getattr(cfg, "openrouter_balance_check_enabled", False):
        return []
    if not isinstance(snapshot, dict):
        return []                       # не спросили — не тревожим
    try:
        remaining = float(snapshot.get("remaining"))
        daily = float(snapshot.get("daily") or 0.0)
    except (TypeError, ValueError):
        return []

    min_days = float(getattr(cfg, "openrouter_balance_min_days", 7))
    days = _days_left(remaining, daily)
    key = "balance:openrouter"
    if days > min_days:
        state.pop(key, None)            # выздоровел — защёлка снимается
        return []

    cooldown = float(getattr(cfg, "openrouter_balance_cooldown_hours", 24)) * 3600
    last = state.get(key)
    if last and now - float(last) < cooldown:
        return []
    state[key] = now
    return [_balance_text(remaining, days)]


def decide_crm(now: float, reachable: bool, state: dict, cfg: Any) -> list[str]:
    """Портал недоступен N тиков подряд → одна тревога.

    Одиночный провал молчит намеренно: Битрикс моргает, и будить человека на один
    таймаут — тот же шум, что и на 34-секундный разлогин Wappi.
    """
    if not getattr(cfg, "bitrix_health_enabled", False):
        return []
    streak_key = "crm:streak"
    latch_key = "crm:down"
    if reachable:
        state.pop(streak_key, None)
        state.pop(latch_key, None)
        return []

    streak = int(state.get(streak_key, 0)) + 1
    state[streak_key] = streak
    confirm = max(1, int(getattr(cfg, "bitrix_health_confirm_ticks", 3)))
    if streak < confirm:
        return []
    # Повторяем, а не замолкаем навсегда: портал может лежать сутками, а единственное
    # сообщение в начале простоя теряется в переписке. Ритм тот же, что у сторожа каналов.
    cooldown = float(getattr(cfg, "bitrix_health_cooldown_hours", 24)) * 3600
    last = state.get(latch_key)
    if last and now - float(last) < cooldown:
        return []
    state[latch_key] = now
    return ["\n".join([
        "Битрикс не отвечает на запросы бота.",
        "Карточки и переписка сейчас в портал не попадают — они копятся у нас "
        "и уедут, когда портал вернётся.",
        "Проверить: оплачен ли тариф портала и жив ли вебхук.",
    ])]


async def fetch_openrouter() -> dict | None:
    """Остаток и суточный расход. None — если спросить не удалось (тревоги не будет)."""
    key = (settings.openrouter_api_key or "").strip()
    if not key:
        return None
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            credits_response = await http.get(OPENROUTER_CREDITS_URL, headers=headers)
            usage_response = await http.get(OPENROUTER_KEY_URL, headers=headers)
    except Exception:  # noqa: BLE001 — сторож не имеет права ронять приложение
        log.warning("openrouter: не удалось получить баланс", exc_info=True)
        return None
    # Статус проверяем ЯВНО. На протухшем ключе, рейт-лимите и 5xx OpenRouter отвечает
    # валидным JSON вида `{"error": {...}}` — без ключа `data`. Без этой проверки остаток
    # схлопнулся бы в ноль и человек получил бы «осталось $0.00, хватит на 0 дн.» на ровном
    # месте: ложная тревога от чужого сбоя, ровно то, что этот модуль обязан не делать.
    if credits_response.status_code != 200 or usage_response.status_code != 200:
        log.warning("openrouter: ответ не 200 (credits=%s key=%s)",
                    credits_response.status_code, usage_response.status_code)
        return None
    try:
        data = (credits_response.json() or {}).get("data")
        key_data = (usage_response.json() or {}).get("data")
        if not isinstance(data, dict) or not isinstance(key_data, dict):
            log.warning("openrouter: в ответе нет data")
            return None
        remaining = float(data["total_credits"]) - float(data["total_usage"])
        weekly = float(key_data.get("usage_weekly") or 0.0)
        daily = max(float(key_data.get("usage_daily") or 0.0), weekly / 7.0)
    except (TypeError, ValueError, KeyError, AttributeError):
        log.warning("openrouter: непонятный ответ", exc_info=True)
        return None
    return {"remaining": remaining, "daily": daily}


async def crm_reachable() -> bool:
    """Дешёвый живой вызов портала. Тот же метод, что уже используется в проекте."""
    url = (settings.bitrix24_webhook_url or "").rstrip("/")
    if not url:
        return True                     # портал не настроен — не наше дело сторожить
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.get(f"{url}/crm.status.list.json",
                                      params={"filter[ENTITY_ID]": "STATUS"})
        return response.status_code == 200 and "result" in response.json()
    except Exception:  # noqa: BLE001
        return False


async def run() -> None:
    """Джоба планировщика: спросить, решить, разбудить человека при поводе.

    Оба сторожа сидят в одном тике намеренно: они редкие, дешёвые и оба про «работает ли
    вообще», а не про диалог. Флаги проверяются рантайм-значением — тумблер в админке
    действует без рестарта.
    """
    import time

    from app.core import flags, ops_alert
    from app.core.wappi_health import _state_load, _state_save

    balance_on = await flags.get_flag("openrouter_balance_check_enabled",
                                      settings.openrouter_balance_check_enabled)
    crm_on = await flags.get_flag("bitrix_health_enabled", settings.bitrix_health_enabled)
    if not balance_on and not crm_on:
        return

    # Решающим функциям отдаём конфиг с УЖЕ разрешёнными флагами: рантайм-тумблер обязан
    # перевешивать env-дефолт, иначе включённая кнопка в админке молча ничего не делает.
    class _Cfg:
        openrouter_balance_check_enabled = balance_on
        openrouter_balance_min_days = settings.openrouter_balance_min_days
        openrouter_balance_cooldown_hours = settings.openrouter_balance_cooldown_hours
        bitrix_health_enabled = crm_on
        bitrix_health_confirm_ticks = settings.bitrix_health_confirm_ticks
        bitrix_health_cooldown_hours = settings.bitrix_health_cooldown_hours

    state = await _state_load()
    now = time.time()

    alerts: list[tuple[str, str]] = []
    if balance_on:
        for text in decide(now, await fetch_openrouter(), state, _Cfg):
            alerts.append(("balance:openrouter", text))
    if crm_on:
        for text in decide_crm(now, await crm_reachable(), state, _Cfg):
            alerts.append(("crm:down", text))

    await _state_save(state)
    for key, text in alerts:
        log.error("BALANCE/CRM ALERT: %s", key)
        await ops_alert.send(text, key=key, now=now)
