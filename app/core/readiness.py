"""Мотор готовности лида («Покупатели сегодня»).

Детерминированный пасс (как manager_brief): из уже собранной квалификации
(`state.qualification`) + ключевых слов последнего сообщения клиента считает
сигналы готовности платить и тир. LLM НЕ вызывается — ноль токенов и ноль
галлюцинаций. Тир — чистая функция сигналов (аудируемо, юнит-тестируемо).

Тиры: green (готов платить) | warm (тёплый, дожать) | noise (шум) |
insufficient (мало данных). Порядок проверки в compute_tier важен.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.state import DialogState

# Пороги — стартовые константы, калибруются по реальным исходам без деплоя кода.
READINESS_THRESHOLDS = {
    "noise_min_negatives": 2,     # столько негативных сигналов при нуле позитивных → шум
    "min_client_messages": 2,     # меньше — «мало данных», боту не с чего судить
    "ghost_noise_hours": 24,      # неготовый + клиент пропал после нас дольше → шум
}

# --- ключевые слова (по последнему сообщению клиента) ---
_KW_PAYMENT = ("оплат", "реквизит", "куда плат", "как плат", "предоплат",
               "депозит", "счёт", "счет", "внести", "перевести", "перевод")
_KW_BOOKING = ("брон", "заброн", "оформ", "берём", "берем", "бронир")
_KW_MANAGER = ("менеджер", "с человеком", "живой человек", "перезвон",
               "свяжитесь", "соедините", "позвоните")
_KW_DEADLINE = ("вылет", "когда лететь", "дата вылета", "срочно", "горит",
                "успе", "до конца", "на этой неделе")
_KW_DOCS = ("паспорт", "документы готов", "готовы документ", "справк", "загранпаспорт")
# негативные
_KW_PRICE_OBJ = ("дорого", "дороговат", "не потяну", "дешевле нет", "слишком")
_KW_BROWSING = ("просто смотрю", "пока думаю", "на будущее", "просто интересуюсь",
                "приценива", "пока прицен")
_KW_COMPARE = ("у других", "в другом агент", "друг агентств", "сравнива", "у конкурент")

# safety-триггер: транзакционные слова → мгновенно green, вне LLM-прогона
_KW_SAFETY = _KW_PAYMENT + _KW_BOOKING + ("когда вылет", "готов оплат", "готов оформ")

_POS_KEYS = (
    "explicit_payment_intent", "explicit_booking_request", "manager_requested",
    "deadline_mentioned", "budget_stated", "contact_shared",
    "destination_confirmed", "travel_dates_narrowed", "pax_count_stated",
    "country_in_scope", "travel_purpose_stated", "document_readiness_mentioned",
)
_NEG_KEYS = (
    "price_objection_only", "info_only_browsing",
    "comparing_multiple_agencies", "single_word_replies_only",
)

_SIGNAL_LABELS = {
    "explicit_payment_intent": "спросил про оплату",
    "explicit_booking_request": "просит оформить/забронировать",
    "manager_requested": "просит менеджера",
    "deadline_mentioned": "назвал сроки/вылет",
    "budget_stated": "назвал бюджет",
    "contact_shared": "оставил имя/контакт",
    "destination_confirmed": "выбрал направление",
    "travel_dates_narrowed": "назвал даты",
    "pax_count_stated": "назвал число туристов",
    "country_in_scope": "назвал страну визы",
    "travel_purpose_stated": "назвал цель поездки",
    "document_readiness_mentioned": "документы готовы",
    "price_objection_only": "жалуется на цену",
    "info_only_browsing": "просто смотрит",
    "comparing_multiple_agencies": "сравнивает с другими",
    "single_word_replies_only": "односложные ответы",
}


def _has(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def _truthy(value: Any) -> bool:
    return value not in (None, "", [], {}, 0)


def _client_message_count(state: DialogState) -> int:
    return sum(1 for h in state.history
               if h.get("role") == "user" and isinstance(h.get("content"), str))


def _latest_user_text(state: DialogState) -> str:
    for item in reversed(state.history):
        if item.get("role") == "user" and isinstance(item.get("content"), str):
            return item["content"]
    return ""


def _all_user_text(state: DialogState) -> str:
    return " ".join(
        h["content"] for h in state.history
        if h.get("role") == "user" and isinstance(h.get("content"), str)
    ).lower()


def _replies_missing(state: DialogState) -> bool:
    """В истории одни клиентские реплики: разговор либо не начат, либо идёт мимо нас.

    Второе — не гипотеза: замер прода 19.08.2026 показал 385 таких диалогов из 681 на
    визовом канале, причём клиент в них отвечает на заданные вопросы, то есть менеджер с
    ним работал, а эхо ответа с телефона до нас не долетело. Судить о готовности по
    половине разговора нельзя: «Шум» спрятал бы из ленты живого клиента.
    """
    # Порог тот же, что у `leadstate.UNSEEN_MIN_CLIENT_MSGS`: одно-два сообщения без ответа
    # бывают и в честно брошенном диалоге, а вот третье подряд означает, что человеку
    # отвечает кто-то мимо нас.
    if _client_message_count(state) < 3:
        return False
    return not any(h.get("role") != "user" for h in state.history)


def _signals(state: DialogState) -> dict[str, Any]:
    q = state.qualification or {}
    # ПОЗИТИВ — стики: сканируем ВСЮ историю. Раз клиент показал намерение платить,
    # оно не забывается на следующем сообщении (иначе «дороговато» топит покупателя).
    all_text = _all_user_text(state)
    # НЕГАТИВ — транзиентный: только последнее сообщение. Колебание вслух ≠ приговор.
    latest = _latest_user_text(state).lower()
    words = latest.split()
    return {
        # позитив по тексту (стики, по всей истории)
        "explicit_payment_intent": _has(all_text, _KW_PAYMENT),
        "explicit_booking_request": _has(all_text, _KW_BOOKING),
        "manager_requested": _has(all_text, _KW_MANAGER),
        "document_readiness_mentioned": _has(all_text, _KW_DOCS),
        # позитив по собранной квалификации (и так копится в state.qualification)
        "deadline_mentioned": _truthy(q.get("dates")) or _has(all_text, _KW_DEADLINE),
        "budget_stated": _truthy(q.get("budget")),
        "contact_shared": _truthy(q.get("name")),
        "destination_confirmed": _truthy(q.get("destination")),
        "travel_dates_narrowed": _truthy(q.get("dates")),
        "pax_count_stated": _truthy(q.get("tourists")),
        "country_in_scope": _truthy(q.get("country")),
        "travel_purpose_stated": _truthy(q.get("occupation")),
        # негатив по текущему сообщению
        "price_objection_only": _has(latest, _KW_PRICE_OBJ),
        "info_only_browsing": _has(latest, _KW_BROWSING),
        "comparing_multiple_agencies": _has(latest, _KW_COMPARE),
        "single_word_replies_only": bool(latest) and len(words) <= 1 and len(latest) < 12,
        # контекст
        "message_count_client": _client_message_count(state),
        # safety — тоже стики (по всей истории)
        "keyword_safety_trigger_matched": _has(all_text, _KW_SAFETY),
    }


def _pos(sig: dict) -> int:
    return sum(1 for k in _POS_KEYS if sig.get(k))


def _neg(sig: dict) -> int:
    return sum(1 for k in _NEG_KEYS if sig.get(k))


def compute_tier(sig: dict) -> str:
    """Детерминированный тир по сигналам. Первое совпадение побеждает."""
    if sig.get("keyword_safety_trigger_matched"):
        return "green"
    if (sig.get("message_count_client", 0) < READINESS_THRESHOLDS["min_client_messages"]
            or (_pos(sig) == 0 and _neg(sig) == 0)):
        return "insufficient"
    if (sig.get("explicit_payment_intent") or sig.get("explicit_booking_request")
            or sig.get("manager_requested")):
        return "green"
    if (sig.get("deadline_mentioned") and sig.get("budget_stated")
            and (sig.get("destination_confirmed") or sig.get("country_in_scope"))):
        return "green"
    if _neg(sig) >= READINESS_THRESHOLDS["noise_min_negatives"] and _pos(sig) == 0:
        return "noise"
    return "warm"


def _reason(tier: str, sig: dict) -> str:
    if tier == "insufficient":
        return "Мало данных: клиент почти ничего не написал, рано судить."
    fired = [_SIGNAL_LABELS[k] for k in (_POS_KEYS if tier != "noise" else _NEG_KEYS)
             if sig.get(k) and k in _SIGNAL_LABELS]
    head = {"green": "Готов платить", "warm": "Тёплый, дожать", "noise": "Шум"}[tier]
    body = ", ".join(fired[:4]) if fired else "нет явных сигналов"
    return f"{head}: {body}."[:150]


def _estimate_value(qualification: dict) -> tuple[float | None, str]:
    """Грубая нормализация бюджета в число+валюту. Пусто/непарсибельно → (None, '')."""
    raw = str((qualification or {}).get("budget") or "").strip()
    if not raw:
        return None, ""
    low = raw.lower().replace(",", "")
    currency = ""
    if any(x in low for x in ("$", "usd", "долл", "бакс")):
        currency = "$"
    elif any(x in low for x in ("€", "eur", "евро")):
        currency = "€"
    elif any(x in low for x in ("сом", "kgs", "kgz")):
        currency = "сом"
    mult = 1000 if any(x in low for x in ("тыс", "тис")) else 1
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", low.replace(" ", ""))]
    vals = [n * mult for n in nums]
    if not vals:
        return None, currency
    val = round(sum(vals) / len(vals))  # диапазон «800-1000» → среднее
    # Валюту НЕ выдумываем (spec): нет явного маркера → пусто, Phase 2 покажет как «?».
    return float(val), currency


def ghost_downgrade(tier: str, signals: dict, ghost_hours: float | None,
                    last_sender: str) -> str:
    """Застоявшийся неготовый диалог (клиент пропал ПОСЛЕ нас) → noise.

    Ловит «спросил цену и исчез»: на момент сообщения тир был insufficient/warm,
    но клиент не ответил на наш последний ход дольше порога. Покупателя (green или
    со стики buy-сигналом) НЕ трогаем — false-negative дороже.
    """
    if tier not in ("insufficient", "warm"):
        return tier
    if (last_sender or "") == "client":       # клиент ждёт НАС — это не ghost
        return tier
    if signals and (signals.get("keyword_safety_trigger_matched")
                    or signals.get("explicit_payment_intent")
                    or signals.get("explicit_booking_request")):
        return tier                            # стики buy-сигнал → не в шум
    if ghost_hours is not None and ghost_hours >= READINESS_THRESHOLDS["ghost_noise_hours"]:
        return "noise"
    return tier


def compute_readiness(state: DialogState) -> dict[str, Any]:
    """Главный вход: сигналы → тир → причина + денежная оценка. Ноль LLM."""
    sig = _signals(state)
    tier = compute_tier(sig)
    reason = _reason(tier, sig)
    if tier == "noise" and _replies_missing(state):
        # Негативные сигналы без единого нашего ответа — половина разговора, а не портрет
        # клиента. Честный тир здесь «мало данных», иначе прячем в шум того, кого ведут.
        tier = "insufficient"
        reason = "Мало данных: наших ответов в диалоге нет — клиента могут вести мимо нас."
    value, currency = _estimate_value(state.qualification or {})
    return {
        "readiness_tier": tier,
        "readiness_reason": reason,
        "readiness_signals": sig,
        "estimated_value": value,
        "estimated_value_currency": currency,
    }
