"""Утренний «горячий лист» — Фаза 0 календаря звонков (ночной диспетчер).

Cron-джоба поверх готового readiness-мотора: раз в сутки утром по Бишкеку собирает
green/warm лидов, которые ещё ждут человека, и пушит менеджерам готовый список. Ноль
нового состояния диалогов, ноль LLM — всё из полей readiness + квалификации.

Приоритет звонков (трио менеджеров Codex/Fable): первичный ключ — ВРЕМЯ ОЖИДАНИЯ
(кто дольше висит без ответа с ночи), как в buyers.py; чек — лишь тайбрейк и нормализуется
сом→$ фикс-курсом ТОЛЬКО для сортировки (хранимое estimated_value не трогаем — оно честно
«как сказал клиент»). Валюту не выдумываем: неизвестная → «?».

Идемпотентность: датированный флаг app_flags (`morning_brief_sent_YYYYMMDD`) переживает
рестарт. Флаг ставится только при УСПЕШНОЙ доставке (или если Telegram не настроен) —
иначе упавший пуш «съедал» бы весь день без ретрая. Экран /admin/morning работает всегда.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import settings

log = logging.getLogger("morning_brief")

BISHKEK_UTC_OFFSET = 6      # Кыргызстан UTC+6 (без перехода на летнее время)
SEND_WINDOW_HOURS = 3       # окно отправки [hour, hour+3): бот лежал всё утро → не шлём вечером
TELEGRAM_LEAD_CAP = 20      # Telegram-лимит 4096 симв.: в пуше не больше N лидов, хвост → «ещё N»

_FUNNEL_LABEL = {"visa": "Визы", "tours": "Туры", "tickets": "Билеты"}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _name(conv) -> str:
    name = (getattr(conv, "qualification", None) or {}).get("name")
    if name:
        return str(name)
    phone = getattr(conv, "phone", "") or getattr(conv, "user_id", "")
    tail = phone[-4:] if phone else "—"
    return f"Без имени · {tail}"


def _direction(conv) -> str:
    q = getattr(conv, "qualification", None) or {}
    label = _FUNNEL_LABEL.get(getattr(conv, "funnel", "") or "", "—")
    dest = q.get("destination") or q.get("country")
    return f"{label} · {dest}" if dest else label


def _wait_minutes(conv, now: datetime) -> float:
    """Сколько клиент ждёт ответа. 0, если последним писал не клиент (мяч не у нас)."""
    if (getattr(conv, "last_sender", "") or "") != "client":
        return 0.0
    dt = _aware(getattr(conv, "last_message_at", None))
    if dt is None:
        return 0.0
    return max(0.0, (_aware(now) - dt).total_seconds() / 60)


def _fmt_wait(minutes: int) -> str:
    if minutes <= 0:
        return ""
    return f"ждёт {minutes // 60} ч" if minutes >= 60 else f"ждёт {minutes} мин"


def _fmt_check(value, currency: str) -> str:
    """Чек как сказал клиент. Неизвестную валюту метим «?» — не выдаём сом за доллары."""
    if not value:
        return ""
    return f"{value:.0f} {currency or '?'}"


def _norm_value(value, currency: str) -> float:
    """Грубая нормализация в $ ТОЛЬКО для тайбрейка сортировки (не для отображения)."""
    if not value:
        return 0.0
    if currency == "сом":
        return value * settings.som_to_usd_rate
    return float(value)   # $/€/неизвестно → как есть (последний ключ, влияние мало)


def _card(conv, tier: str, now: datetime) -> dict:
    q = getattr(conv, "qualification", None) or {}
    value = getattr(conv, "estimated_value", None)
    currency = getattr(conv, "estimated_value_currency", "") or ""
    wait = int(_wait_minutes(conv, now))
    return {
        "user_id": getattr(conv, "user_id", ""),
        "name": _name(conv),
        "direction": _direction(conv),
        "tier": tier,
        "value": value,
        "currency": currency,
        "check": _fmt_check(value, currency),
        "dates": str(q.get("dates") or "").strip(),
        "wait": wait,
        "wait_label": _fmt_wait(wait),
        "reason": getattr(conv, "readiness_reason", "") or "",
        "_norm": _norm_value(value, currency),
    }


def _needs_human(conv) -> bool:
    """Лид достоин утреннего звонка: не закрыт и ещё НЕ взят живым менеджером."""
    if (getattr(conv, "outcome", "") or "") in ("won", "lost"):
        return False
    if getattr(conv, "assigned_to", "") or getattr(conv, "intercepted", False):
        return False
    return True


def build_brief(convs: list, now: datetime | None = None) -> dict:
    """convs — non-archived, scope-фильтрованные ConversationView с readiness_*.

    green (готовы) + warm (дожать). Порядок: ждёт дольше → выше; чек (норм. в $) — тайбрейк.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    green, warm = [], []
    for c in convs:
        if not _needs_human(c):
            continue
        tier = getattr(c, "readiness_tier", "") or ""
        if tier == "green":
            green.append(_card(c, "green", now))
        elif tier == "warm":
            warm.append(_card(c, "warm", now))
    key = lambda x: (x["wait"], x["_norm"])   # noqa: E731 — ожидание первично, чек тайбрейк
    green.sort(key=key, reverse=True)
    warm.sort(key=key, reverse=True)
    return {
        "date_label": (now + timedelta(hours=BISHKEK_UTC_OFFSET)).strftime("%d.%m"),
        "green": green,
        "warm": warm,
        "green_count": len(green),
        "warm_count": len(warm),
        "generated_at": now,
    }


def _line(i: int, c: dict) -> str:
    parts = [f"{i}. {c['name']} · {c['direction']}"]
    if c["check"]:
        parts.append(f"· {c['check']}")
    if c["dates"]:
        parts.append(f"· вылет {c['dates']}")
    if c["wait_label"]:
        parts.append(f"· {c['wait_label']}")
    return " ".join(parts)


def render_text(brief: dict, limit: int | None = None) -> str:
    """Плоский текст листа для Telegram. limit — потолок лидов в пуше (хвост → «ещё N»)."""
    green, warm = brief["green"], brief["warm"]
    overflow = 0
    if limit is not None and brief["green_count"] + brief["warm_count"] > limit:
        green = brief["green"][:limit]
        warm = brief["warm"][: max(0, limit - len(green))]
        overflow = (brief["green_count"] + brief["warm_count"]) - (len(green) + len(warm))

    lines = [
        f"🔥 Горячий лист · {brief['date_label']}",
        f"Готовы 🟢 {brief['green_count']} · Тёплые 🟡 {brief['warm_count']}",
    ]
    if green:
        lines += ["", "🟢 ГОТОВЫ К ПОКУПКЕ:"]
        lines += [_line(i, c) for i, c in enumerate(green, 1)]
    if warm:
        lines += ["", "🟡 ТЁПЛЫЕ (дожать):"]
        lines += [_line(i, c) for i, c in enumerate(warm, 1)]
    if not green and not warm:
        lines += ["", "Готовых лидов за ночь нет — спокойное утро ☕"]
    if overflow:
        lines += ["", f"…и ещё {overflow} — весь список в /admin/morning"]
    return "\n".join(lines)


def _in_send_window(local_hour: int, cfg) -> bool:
    return cfg.morning_brief_hour <= local_hour < cfg.morning_brief_hour + SEND_WINDOW_HOURS


def _telegram_configured(cfg) -> bool:
    chat_id = (cfg.managers_telegram_chat_id or "").strip()
    token = (cfg.managers_telegram_bot_token or cfg.telegram_bot_token or "").strip()
    return bool(chat_id and token)


async def _push_telegram(text: str, cfg) -> bool:
    """Отправить лист в группу менеджеров. Возвращает True при успешной доставке."""
    token = (cfg.managers_telegram_bot_token or cfg.telegram_bot_token or "").strip()
    chat_id = (cfg.managers_telegram_chat_id or "").strip()
    try:
        from app.channels.telegram import TelegramAdapter
        await TelegramAdapter(token).send(chat_id, text)
        return True
    except Exception:  # noqa: BLE001 — пуш не должен ронять планировщик
        log.warning("morning brief telegram push failed", exc_info=True)
        return False


async def run(now: datetime | None = None) -> None:
    """Джоба планировщика: раз в сутки утром по Бишкеку собрать и отправить горячий лист.

    now — только для тестов (инъекция времени); планировщик зовёт без аргумента.
    """
    from app.core import flags
    from app.integrations.panel.store import get_conversation_store

    cfg = settings
    if not await flags.get_flag("morning_brief_enabled", cfg.morning_brief_enabled):
        return  # авто-режим выключен (рантайм-флаг из админки; дефолт — из env)

    now = _aware(now) or datetime.now(timezone.utc)
    local = now + timedelta(hours=BISHKEK_UTC_OFFSET)
    if not _in_send_window(local.hour, cfg):
        return  # ещё рано или уже поздно — ждём следующего утра

    sent_key = f"morning_brief_sent_{local:%Y%m%d}"
    if await flags.get_flag(sent_key, False):
        return  # уже слали сегодня (флаг переживает рестарт)

    brief = build_brief(await get_conversation_store().all_conversations_light(), now)

    if not _telegram_configured(cfg):
        # Telegram ещё не заведён (chat_id возьмут позже) — слать некуда, экран покрывает.
        await flags.set_flag(sent_key, True)
        log.info("morning brief built (telegram off): green=%d warm=%d",
                 brief["green_count"], brief["warm_count"])
        return

    if await _push_telegram(render_text(brief, limit=TELEGRAM_LEAD_CAP), cfg):
        await flags.set_flag(sent_key, True)   # флаг ТОЛЬКО при успехе — иначе ретрай на след. тике
        log.info("morning brief sent: green=%d warm=%d", brief["green_count"], brief["warm_count"])
    else:
        log.warning("morning brief telegram failed — повтор на следующем тике (окно ещё открыто)")
