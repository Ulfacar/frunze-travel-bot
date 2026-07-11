"""Утренний «горячий лист» — Фаза 0 календаря звонков (ночной диспетчер).

Cron-джоба поверх готового readiness-мотора: раз в сутки утром по Бишкеку собирает
green/warm лидов, которые ещё ждут человека, и пушит менеджерам готовый список с
досье. Ноль нового состояния диалогов (карточки не трогаем), ноль LLM — всё из полей
readiness (см. app/core/readiness.py) + квалификации.

Слоты/бронь сюда НЕ входят (это Фаза 1). Здесь только «утром покажи менеджеру, кому
звонить». Экран /admin/morning показывает то же на лету; Telegram-пуш — если задан
managers_telegram_chat_id.

Идемпотентность (грабля рестарта): «уже отправлено сегодня» держим датированным флагом
в app_flags (`morning_brief_sent_YYYYMMDD`) — переживает передеплой, новый день = новый
ключ = дефолт False. Чистые функции (build_brief/render_text) тестируемы без БД и LLM.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import settings

log = logging.getLogger("morning_brief")

BISHKEK_UTC_OFFSET = 6      # Кыргызстан UTC+6 (без перехода на летнее время)
SEND_WINDOW_HOURS = 3       # окно отправки [hour, hour+3): если бот лежал всё утро — не шлём «утренний» лист вечером

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


def _card(conv, tier: str) -> dict:
    return {
        "user_id": getattr(conv, "user_id", ""),
        "name": _name(conv),
        "direction": _direction(conv),
        "tier": tier,
        "value": getattr(conv, "estimated_value", None),
        "currency": getattr(conv, "estimated_value_currency", "") or "",
        "reason": getattr(conv, "readiness_reason", "") or "",
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

    Возвращает готовый лист: green (готовы платить) и warm (дожать), чек desc.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    green, warm = [], []
    for c in convs:
        if not _needs_human(c):
            continue
        tier = getattr(c, "readiness_tier", "") or ""
        if tier == "green":
            green.append(_card(c, "green"))
        elif tier == "warm":
            warm.append(_card(c, "warm"))
    green.sort(key=lambda x: (x["value"] or 0), reverse=True)
    warm.sort(key=lambda x: (x["value"] or 0), reverse=True)
    return {
        "date_label": (now + timedelta(hours=BISHKEK_UTC_OFFSET)).strftime("%d.%m"),
        "green": green,
        "warm": warm,
        "green_count": len(green),
        "warm_count": len(warm),
        "generated_at": now,
    }


def _line(i: int, c: dict) -> str:
    chk = f" · {c['value']:.0f}{c['currency']}" if c["value"] else ""
    reason = f" — {c['reason']}" if c["reason"] else ""
    return f"{i}. {c['name']} · {c['direction']}{chk}{reason}"


def render_text(brief: dict) -> str:
    """Плоский текст листа для Telegram-пуша менеджерам."""
    lines = [
        f"🔥 Горячий лист · {brief['date_label']}",
        f"Готовы 🟢 {brief['green_count']} · Тёплые 🟡 {brief['warm_count']}",
    ]
    if brief["green"]:
        lines += ["", "🟢 ГОТОВЫ К ПОКУПКЕ:"]
        lines += [_line(i, c) for i, c in enumerate(brief["green"], 1)]
    if brief["warm"]:
        lines += ["", "🟡 ТЁПЛЫЕ (дожать):"]
        lines += [_line(i, c) for i, c in enumerate(brief["warm"], 1)]
    if not brief["green"] and not brief["warm"]:
        lines += ["", "Готовых лидов за ночь нет — спокойное утро ☕"]
    return "\n".join(lines)


def _in_send_window(local_hour: int, cfg) -> bool:
    return cfg.morning_brief_hour <= local_hour < cfg.morning_brief_hour + SEND_WINDOW_HOURS


async def _push_telegram(text: str, cfg) -> bool:
    """Отправить лист в группу менеджеров. False, если Telegram не сконфигурирован/сбой."""
    chat_id = (cfg.managers_telegram_chat_id or "").strip()
    # Выделенный токен бота менеджеров; фолбэк на легаси telegram_bot_token, если не задан.
    token = (cfg.managers_telegram_bot_token or cfg.telegram_bot_token or "").strip()
    if not chat_id or not token:
        return False  # chat_id заведут позже — молча пропускаем (экран /admin/morning работает всегда)
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
    delivered = await _push_telegram(render_text(brief), cfg)
    await flags.set_flag(sent_key, True)  # раз в день, даже если Telegram не настроен (экран покрывает)
    log.info("morning brief built: green=%d warm=%d telegram=%s",
             brief["green_count"], brief["warm_count"], delivered)
