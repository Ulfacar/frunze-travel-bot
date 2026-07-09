"""Агентный цикл: LLM ведёт диалог и вызывает инструменты воронки.

Универсальный `run_turn(state, user_text, spec)` переиспользуется всеми воронками —
без копирования цикла. Конкретика воронки (промпт, набор инструментов, исполнитель
инструментов) живёт в `FunnelSpec`. История диалога — в `DialogState.history`
(внутренний формат сообщений совместим с прежним агентным циклом).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import httpx

from app.agent.llm import client
from app.agent.prompts.tickets import SYSTEM as TICKETS_SYSTEM
from app.agent.prompts.tours import SYSTEM as TOURS_SYSTEM, system_for_manager as tours_system_for_manager
from app.agent.prompts.visa import SYSTEM as VISA_SYSTEM
from app.agent.routing import choose_model, should_escalate_tours_input
from app.agent.tools import tools_for
from app.agent.validator import validate_reply
from app.config import settings
from app.core import budget, observ
from app.core.branding import GETVISA_OFFICE_ADDRESS, PRICE_DISCLAIMER
from app.core.state import DialogState
from app.core.visa_pricing import self_visa_reply, visa_price_reply
from app.funnels.visa import score_visa, visa_category
from app.integrations.crm import get_crm
from app.integrations.tourvisor.client import TourVisorClient, TourVisorError

logger = logging.getLogger("agent.runner")

MAX_TOOL_ITERATIONS = 6
_tourvisor = TourVisorClient()

ToolExec = Callable[[str, dict, DialogState, object], Awaitable[str]]


def _windowed_history(history: list[dict], max_n: int) -> list[dict]:
    """Return a safe history tail that starts at a user text boundary."""
    if max_n <= 0 or len(history) <= max_n:
        return history

    bounds = [
        i for i, message in enumerate(history)
        if message.get("role") == "user" and isinstance(message.get("content"), str)
    ]
    if not bounds:
        return history

    target = len(history) - max_n
    later = [i for i in bounds if i >= target]
    start = later[0] if later else bounds[-1]
    return history[start:]


def _qual_context_message(qual: dict) -> dict | None:
    """Compact known qualification facts as a separate user message."""
    parts = [f"{key}={value}" for key, value in (qual or {}).items() if value]
    if not parts:
        return None
    return {
        "role": "user",
        "content": "[Уже известно от клиента: " + ", ".join(parts) + "]",
    }


def _ad_context_message(referral: dict) -> dict | None:
    """Рекламный контекст (Click-to-WhatsApp Ads) отдельным user-сообщением.

    Клиент пришёл по объявлению — не спрашиваем с нуля «что вас интересует», а
    подтверждаем оффер. Подмешивается на каждый ход (в state.history не пишется)."""
    if not referral:
        return None
    offer = " — ".join(p for p in (referral.get("headline"), referral.get("body")) if p).strip()
    if not offer:
        return None
    return {
        "role": "user",
        "content": (f"[Клиент пришёл по рекламе: «{offer[:300]}». Учитывай это: не спрашивай "
                    f"с нуля, что его интересует — подтверди контекст объявления и веди к деталям.]"),
    }


# Кыргызстан UTC+6, без перехода на летнее время (как в followup.py / budget.py).
_BISHKEK_OFFSET = timedelta(hours=6)
_RU_WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def _date_context_message(now: datetime | None = None) -> dict:
    """Текущая дата (Бишкек) отдельным user-сообщением на каждый ход.

    Без неё модель не знает «какое сегодня» и угадывает месяц/год — на живых
    диалогах угадывала февраль/январь вместо июля (слив доверия клиента).
    В state.history не пишется — только подмешивается в prefix."""
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    local = base.astimezone(timezone.utc) + _BISHKEK_OFFSET
    stamp = f"{local:%d.%m.%Y}, {_RU_WEEKDAYS[local.weekday()]}"
    return {
        "role": "user",
        "content": (f"[Служебная заметка: сегодня {stamp} (время Бишкека). Отсчитывай все "
                    f"относительные даты («этот месяц», «через неделю», «в начале месяца») "
                    f"от сегодняшней. НИКОГДА не угадывай текущий месяц или год.]"),
    }


@dataclass
class FunnelSpec:
    """Описание воронки для агентного цикла."""
    name: str
    system: str
    tools: list[dict]
    exec_tool: ToolExec


async def run_turn(state: DialogState, user_text: str, spec: FunnelSpec) -> str | None:
    """Обработать один ход клиента через LLM-агента (общий цикл для всех воронок)."""
    if state.intercepted:
        return None  # менеджер перехватил диалог — бот молчит
    state.history.append({"role": "user", "content": user_text})
    crm = get_crm()
    escalated = spec.name == "tours" and should_escalate_tours_input(user_text)

    for _ in range(MAX_TOOL_ITERATIONS):
        model = choose_model(spec.name, escalated)
        if await budget.soft_capped():
            model = settings.llm_model_cheap
        window = _windowed_history(state.history, settings.llm_history_max_messages)
        prefix = [m for m in (_date_context_message(),
                              _ad_context_message(state.ad_referral),
                              _qual_context_message(state.qualification)) if m]
        messages = prefix + window
        resp = await client().messages.create(
            model=model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            system=spec.system,
            tools=spec.tools,
            messages=messages,
        )
        await _record_llm_usage(model, resp, state)

        if resp.stop_reason == "tool_use":
            state.history.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    if spec.name == "tours" and block.name == "search_tours":
                        escalated = True
                    out = await spec.exec_tool(block.name, dict(block.input or {}), state, crm)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            state.history.append({"role": "user", "content": results})
            continue

        text = "".join(b.text for b in resp.content if b.type == "text")
        # Валидатор: чиним безопасное (markdown, дисклеймер цен туров), мягко логируем риски.
        text, violations = validate_reply(text, spec.name)
        if violations:
            logger.info("validator (%s): %s", spec.name, ", ".join(violations))
            for v in violations:
                observ.note_validation(v)
        state.history.append({"role": "assistant", "content": text})
        return text or "Расскажите, пожалуйста, подробнее."

    return "Давайте уточню детали ещё раз, чтобы подобрать лучший вариант."


async def _record_llm_usage(model: str, resp: object, state: DialogState) -> None:
    usage = getattr(resp, "usage", None)
    if not usage:
        return
    cost = budget.cost_from_usage(model, usage)
    usage = {**usage, "cost": cost}
    observ.record_usage(
        model,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        cost,
        state.bot_id,
        state.user_id,
        usage=usage,
    )
    await budget.add_spend(cost)


# ---------------- Туры ----------------
async def _tours_exec_tool(name: str, args: dict, state: DialogState, crm) -> str:
    logger.info("tours tool %s args=%s", name, args)

    if name == "search_tours":
        state.qualification.update({k: v for k, v in args.items() if v})
        if not state.deal_id:
            state.deal_id = await crm.create_lead({"user_id": state.user_id}, "tours", state.qualification)
        try:
            tours = await _tourvisor.search(state.qualification)
        except (TourVisorError, httpx.HTTPError):
            return ("Поиск туров сейчас временно недоступен. Я записал ваш запрос — "
                    "менеджер подберёт варианты и свяжется с вами.")
        return "\n".join(tours) if tours else "Подходящих туров не нашлось."

    if name == "handoff_to_manager":
        if state.deal_id:
            await crm.update_stage(state.deal_id, "manager_handoff")
        state.stage = "manager"
        return ("Передано менеджеру. Скажи клиенту КОРОТКО и честно: запрос передал(а) "
                "менеджеру, он ответит в этом чате; НЕ утверждай, что менеджер уже онлайн.")

    if name == "escalate_to_office":
        state.qualification.update({
            k: v for k, v in args.items()
            if k in {"name", "visit_time", "office_visit", "selected_option"} and v
        })
        client_name = args.get("name") or state.qualification.get("name")
        visit_time = (
            args.get("visit_time")
            or state.qualification.get("visit_time")
            or state.qualification.get("office_visit")
        )
        if not client_name:
            return (
                "Клиент хочет в офис, но имя ещё не собрано. НЕ вызывай офис как записанный "
                "визит и НЕ говори «менеджер уже ждёт». Сначала ответь на текущий вопрос клиента "
                "по туру, затем спроси: «Как могу к вам обращаться, чтобы менеджер понимал, "
                "по какой заявке вы придёте?»"
            )
        if not visit_time:
            return (
                "Имя клиента уже есть, но время визита не подтверждено. НЕ говори «менеджер уже "
                "ждёт». Спроси, на какое время завтра/в выбранный день клиенту удобно подойти."
            )
        if state.deal_id:
            await crm.update_stage(state.deal_id, "office_consultation")
        state.stage = "office"
        return (
            "Визит можно подтверждать. Коротко зафиксируй имя, время и выбранный вариант; "
            "дай адрес офиса, если клиент его ещё не получил. Паспорт упомяни мягко: для брони "
            "лучше взять загранпаспорта. Не утверждай, что менеджер уже ждёт."
        )

    return "ok"


TOURS_SPEC = FunnelSpec(
    name="tours",
    system=TOURS_SYSTEM,
    tools=tools_for(["search_tours", "handoff_to_manager", "escalate_to_office"]),
    exec_tool=_tours_exec_tool,
)


async def run_tours_turn(state: DialogState, user_text: str) -> str | None:
    """Один ход клиента в воронке «Туры»."""
    spec = TOURS_SPEC
    if state.manager_name:
        spec = replace(TOURS_SPEC, system=tours_system_for_manager(state.manager_name))
    return await run_turn(state, user_text, spec)


# ---------------- Визы ----------------
async def _visa_exec_tool(name: str, args: dict, state: DialogState, crm) -> str:
    logger.info("visa tool %s args=%s", name, args)

    if name == "score_visa":
        state.qualification.update({k: v for k, v in args.items() if v})
        if not state.deal_id:
            state.deal_id = await crm.create_lead({"user_id": state.user_id}, "visa", state.qualification)
        await crm.update_stage(state.deal_id, "visa_scoring")
        category = visa_category(score_visa(state.qualification))
        # Категория — ВНУТРЕННИЙ ориентир для тона. Клиенту НЕ обещаем визу/процент,
        # всегда ведём на консультацию (escalate_to_office).
        return (f"[внутренний сигнал силы кейса: {category}] Не называй клиенту процент и не "
                f"обещай визу. Подай мягко и честно (грамотная анкета и подготовка к интервью "
                f"решают многое) и пригласи на консультацию в офис или онлайн. Цену услуги "
                f"называй по официальному прайсу только если клиент спросил; депозиты/итоговую "
                f"сумму — не называй.")

    if name == "handoff_to_manager":
        if state.deal_id:
            await crm.update_stage(state.deal_id, "manager_handoff")
        state.stage = "manager"
        return ("Передано менеджеру. Скажи клиенту КОРОТКО и честно: запрос передал(а) "
                "менеджеру, он ответит в этом чате; НЕ утверждай, что менеджер уже онлайн.")

    if name == "escalate_to_office":
        if state.deal_id:
            await crm.update_stage(state.deal_id, "office_consultation")
        state.stage = "office"
        return (f"Пригласи клиента на консультацию. Адрес офиса: {GETVISA_OFFICE_ADDRESS}. "
                f"Можно начать и онлайн. Документы и детали уточнит менеджер. Цену услуги "
                f"называй по официальному прайсу только если клиент спросил; депозиты/итоговую "
                f"сумму — не называй.")

    return "ok"


VISA_SPEC = FunnelSpec(
    name="visa",
    system=VISA_SYSTEM,
    tools=tools_for(["score_visa", "escalate_to_office", "handoff_to_manager"]),
    exec_tool=_visa_exec_tool,
)


async def run_visa_turn(state: DialogState, user_text: str) -> str | None:
    """Один ход клиента в воронке «Визы»."""
    price_reply = visa_price_reply(user_text)
    if price_reply:
        state.history.append({"role": "user", "content": user_text})
        state.history.append({"role": "assistant", "content": price_reply})
        return price_reply

    retention = self_visa_reply(
        user_text,
        already_sent=bool(state.qualification.get("self_visa_retention_sent")),
    )
    if retention:
        state.history.append({"role": "user", "content": user_text})
        state.history.append({"role": "assistant", "content": retention})
        if state.qualification.get("self_visa_retention_sent"):
            state.stage = "manager"
            state.intercepted = True
        else:
            state.qualification["self_visa_retention_sent"] = True
        return retention

    return await run_turn(state, user_text, VISA_SPEC)


# ---------------- Билеты ----------------
async def _tickets_exec_tool(name: str, args: dict, state: DialogState, crm) -> str:
    logger.info("tickets tool %s args=%s", name, args)

    if name == "submit_request":
        state.qualification.update({k: v for k, v in args.items() if v})
        if not state.deal_id:
            state.deal_id = await crm.create_lead({"user_id": state.user_id}, "tickets", state.qualification)
        await crm.update_stage(state.deal_id, "manager_handoff")
        state.stage = "manager"
        return (f"Заявка передана менеджеру на подбор рейса и оплату. Скажи клиенту, что "
                f"менеджер пришлёт варианты и цену. {PRICE_DISCLAIMER} Цену сам не называй.")

    return "ok"


TICKETS_SPEC = FunnelSpec(
    name="tickets",
    system=TICKETS_SYSTEM,
    tools=tools_for(["submit_request"]),
    exec_tool=_tickets_exec_tool,
)


async def run_tickets_turn(state: DialogState, user_text: str) -> str | None:
    """Один ход клиента в воронке «Билеты»."""
    return await run_turn(state, user_text, TICKETS_SPEC)
