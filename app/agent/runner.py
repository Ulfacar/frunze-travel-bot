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
from app.agent.prompts.common import DOZHIM_AND_PRICE_FORK
from app.agent.prompts.tickets import SYSTEM as TICKETS_SYSTEM
from app.agent.prompts.tours import SYSTEM as TOURS_SYSTEM, system_for_manager as tours_system_for_manager
from app.agent.prompts.visa import SYSTEM as VISA_SYSTEM
from app.agent.routing import choose_model, should_escalate_tours_input
from app.agent.tools import tools_for
from app.agent.validator import validate_reply
from app.config import settings
from app.core import budget, flags, observ, tours_health
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


def _schedule_context_message(bot_id: str, now: datetime | None = None) -> dict | None:
    """График приёма отдельным служебным сообщением — рядом с датой, на каждый ход.

    06.08 бот записал клиента на консультацию в воскресенье вечером, хотя по визам
    пн–сб до 19:00. График лежал в знаниях строкой, и что из неё следует, решала модель:
    в ночь на 07.08 она отвечала правильно, а сутками раньше — нет. С датой была ровно
    та же болезнь и то же лекарство (см. `_date_context_message`).
    """
    if not bot_id:
        return None
    try:
        from app.core.schedule import schedule_note
        base = now or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        local = base.astimezone(timezone.utc) + _BISHKEK_OFFSET
        return {"role": "user", "content": schedule_note(bot_id, local)}
    except Exception:  # noqa: BLE001 — без заметки ответим как раньше, но ответим
        return None


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
    system_prompt = spec.system
    if await flags.get_flag("dozhim_enabled", settings.dozhim_enabled):
        system_prompt = spec.system + "\n\n" + DOZHIM_AND_PRICE_FORK

    for _ in range(MAX_TOOL_ITERATIONS):
        model = choose_model(spec.name, escalated)
        if await budget.soft_capped():
            model = settings.llm_model_cheap
        window = _windowed_history(state.history, settings.llm_history_max_messages)
        prefix = [m for m in (_date_context_message(),
                              _schedule_context_message(state.bot_id),
                              _ad_context_message(state.ad_referral),
                              _qual_context_message(state.qualification)) if m]
        messages = prefix + window
        resp = await client().messages.create(
            model=model,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            system=system_prompt,
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
        text = _attach_tour_cards(state, text)
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
def _render_cards_for_state(found, state: DialogState) -> list[str]:
    """Карточки подборки из сырых отелей. Любой сбой рендера гасим: ход важнее формата."""
    try:
        from app.integrations.tourvisor.cards import render_cards
        return render_cards(found.hotels, departure=found.departure)
    except Exception:  # noqa: BLE001
        logger.warning("tour cards render failed (key=%s)", state.user_id, exc_info=True)
        return []


def _cards_places_for(found) -> list[str]:
    """Курорты из реально отобранных карточек. Сбой рендера не должен ронять ход."""
    try:
        from app.integrations.tourvisor.cards import picked_places
        return picked_places(found.hotels)
    except Exception:  # noqa: BLE001
        return []


async def _offer_url(found, state: DialogState) -> str:
    """Ссылка на страницу подборки. Пусто — карточки уйдут без неё, это не авария."""
    try:
        from app.web.offers import create_offer
        # Повторный поиск в том же ходу переписывает УЖЕ выданную страницу, а не заводит
        # новую: клиенту всё равно уйдёт одна ссылка, остальные остались бы сиротами.
        return await create_offer(found, state, reuse=state.pending_offer_url)
    except Exception:  # noqa: BLE001
        logger.warning("tour offer page failed (key=%s)", state.user_id, exc_info=True)
        return ""


def _attach_tour_cards(state: DialogState, text: str) -> str:
    """Дописать подборку к ответу модели — ПОСЛЕ валидатора.

    Валидатор нужен диалогу: он режет выдуманные моделью URL и markdown. Но карточки собрал
    код, их разметка — WhatsApp (`*жирный*`), и `strip_markdown` уничтожил бы её вместе со
    ссылкой на нашу же страницу. Поэтому валидируется только текст модели, а блок карточек
    приклеивается после и в неизменном виде.
    """
    cards, url = state.pending_tour_cards, state.pending_offer_url
    state.pending_tour_cards, state.pending_offer_url = [], ""
    if not cards:
        return text
    from app.integrations.tourvisor.cards import render_block
    block = render_block(cards, offer_url=url)
    from app.integrations.crm import bitrix_pipeline
    bitrix_pipeline.fire(state.user_id, "offer_sent", dict(state.qualification))
    return f"{text.rstrip()}\n\n{block}" if text.strip() else block


def _is_qualified(state: DialogState) -> bool:
    """Whether the minimum manager-ready facts have been collected."""
    q = state.qualification or {}
    present = lambda key: bool(str(q.get(key) or "").strip())
    if state.funnel == "visa":
        return (present("country") or present("visa_country")) and (
            present("trip_purpose") or present("purpose"))
    if state.funnel == "tours":
        return (present("destination") or present("country")) and present("dates") and (
            present("tourists") or present("adults"))
    return False


def _sync_qualified_if_ready(state: DialogState) -> None:
    if _is_qualified(state):
        from app.integrations.crm import bitrix_pipeline
        bitrix_pipeline.fire(state.user_id, "qualified", dict(state.qualification))


def _tours_search_report(found, *, cards_mode: bool = False,
                         cards_places: list[str] | None = None) -> str:
    """Результат подбора для агента — С ПРИЧИНОЙ, а не голым списком.

    Раньше на пустой выдаче наверх уходило «Подходящих туров не нашлось», агент причины не
    знал и придумывал её сам («август дорогой, поднимите бюджет»). Клиент поднимал бюджет
    впустую и уходил. Теперь причина машинная и агент обязан назвать именно её.
    """
    if found.reason == "no_destination":
        return ("НАПРАВЛЕНИЕ НЕ РАСПОЗНАНО. Поиск НЕ выполнялся. Переспроси у клиента страну "
                "или курорт (например «Турция», «Анталья», «Дубай») и вызови поиск заново. "
                "Не показывай варианты и не называй причину «нет туров» — их просто не искали.")

    if found.reason == "nothing_found":
        where = f" (вылет {found.departure})" if found.departure else ""
        return (f"НИЧЕГО НЕ НАЙДЕНО{where} — проверены оба города вылета, Бишкек и Алматы. "
                "Скажи клиенту ЧЕСТНО: на эти даты по этому направлению туров у операторов "
                "нет. НЕ ссылайся на бюджет и не проси его поднять — дело не в деньгах. "
                "Предложи сменить даты или направление, либо передай менеджеру.")

    head = [f"Найдено вариантов: {found.found}. Вылет из: {found.departure}."]
    if found.min_price:
        head.append(f"Минимальная цена: {found.min_price}.")
    if found.fallback_departure:
        head.append(
            "ВАЖНО: из Бишкека по этому направлению туров нет, это варианты ИЗ АЛМАТЫ. "
            "Обязательно предупреди клиента об этом — не выдавай их за вылет из Бишкека."
        )
    if found.budget_fit_count is not None:
        head.append(f"В бюджет клиента вписалось вариантов: {found.budget_fit_count}.")
        if found.budget_fit_count == 0:
            head.append(
                "НИ ОДИН вариант не вписался в бюджет клиента. Назови честно минимальную "
                "реальную цену и СРАЗУ предложи три конкретных хода на выбор, коротко, одним "
                "сообщением: 1) сдвинуть даты — конец августа или сентябрь обычно дешевле пика; "
                "2) сократить ночи — 7 вместо 10; 3) сменить курорт или звёздность на более "
                "доступные. Спроси, какой вариант попробовать, и после ответа вызови поиск заново "
                "с новыми параметрами. НЕ заканчивай сообщение на отказе и НЕ проси клиента "
                "поднять бюджет."
            )
    if cards_mode:
        # Карточки уже собраны кодом и уйдут клиенту сразу под репликой модели. Если модель
        # ещё раз перечислит те же отели словами, клиент получит одно и то же дважды.
        head.append(
            "Карточки вариантов клиенту отправит КОД — сразу под твоим сообщением, в том же "
            "виде, в каком их шлют менеджеры. Твоя часть: короткая подводка и ОДИН следующий "
            "шаг. Сам отели не перечисляй, цены и даты не называй — они уже будут в карточках. "
            "Список ниже дан тебе, чтобы отвечать на уточняющие вопросы (порядок совпадает)."
        )
        if cards_places:
            # Подводка обязана совпасть с содержимым: в карточки идут пять самых дешёвых, а
            # найдено бывает больше и по другим курортам. 14.08 модель пообещала «Кемер и
            # Аланью», а во всех пяти карточках была Аланья.
            head.append(
                "В КАРТОЧКИ ПОПАЛИ ТОЛЬКО: " + "; ".join(cards_places) + ". Называй в подводке "
                "исключительно эти курорты — другие найденные направления клиенту не обещай, "
                "иначе он не найдёт их в карточках и перестанет верить всему сообщению."
            )
    else:
        head.append(
            "Цены называй ровно как в строках, вместе с валютой (USD/EUR) — не переводи в другую "
            "валюту и не меняй знак. Дату вылета озвучивай: она может отличаться от запрошенной."
        )
    return " ".join(head) + "\n" + "\n".join(found.lines)


async def _tours_exec_tool(name: str, args: dict, state: DialogState, crm) -> str:
    logger.info("tours tool %s args=%s", name, args)

    if name == "search_tours":
        # Прежнее направление читаем ДО обновления досье: ниже по нему решаем, пережил ли
        # смену страны названный ранее курорт.
        prev_destination = str(state.qualification.get("destination") or "").strip().lower()
        state.qualification.update({k: v for k, v in args.items() if v})
        _sync_qualified_if_ready(state)
        if not state.deal_id:
            state.deal_id = await crm.create_lead({"user_id": state.user_id}, "tours", state.qualification)
        # Пустое поле из повторного tool-вызова не должно стирать уже названную клиентом дату.
        # Иначе модель могла передать dates="" и снова включить опасный дефолт длительности.
        merged = {**state.qualification, **{k: v for k, v in args.items() if v}}
        # ...но курорт живёт ВНУТРИ страны. Клиент передумал «Турция, Белек» → «Египет», модель
        # прислала только destination — и в запрос уходил Белек в Египте, то есть гарантированно
        # пустая выдача с честным «ничего не нашлось». Меняется страна — забываем прежний курорт,
        # если новый не назвали. Остальное досье (бюджет, состав, звёзды) переживает смену страны.
        new_destination = str(args.get("destination") or "").strip().lower()
        if (new_destination and prev_destination and new_destination != prev_destination
                and not str(args.get("region") or "").strip()):
            merged.pop("region", None)
            state.qualification.pop("region", None)
        if not str(merged.get("dates") or "").strip() and not str(merged.get("nights") or "").strip():
            # В августовский пик случайные 7–10 ночей меняют чек на сотни евро. Такой вызов
            # не является пустой выдачей: клиенту сначала нужно задать один точный вопрос.
            await tours_health.note("no_duration")
            return (
                "ДЛИТЕЛЬНОСТЬ НЕ ИЗВЕСТНА. Поиск не выполнялся. Спроси у клиента, на сколько "
                "ночей или на какие даты он планирует, и вызови поиск заново. Не показывай "
                "варианты и не придумывай сроки сам: в пик сезона разница между 7 и 10 ночами — "
                "сотни евро."
            )
        try:
            # Текущий непустой аргумент уточняет накопленное досье, а пропущенный сохраняет
            # уже известное: модель часто повторно вызывает поиск только с изменённым полем.
            found = await _tourvisor.search_detailed(merged)
        except (TourVisorError, httpx.HTTPError):
            return ("Поиск туров сейчас временно недоступен. Я записал ваш запрос — "
                    "менеджер подберёт варианты и свяжется с вами.")
        # Считаем ИСХОД подбора: сломанный поиск месяц жил незамеченным ровно потому, что
        # мерили расход API, а не результат.
        await tours_health.note(
            found.reason,
            fallback=found.fallback_departure,
            has_dates=bool((found.query or {}).get("datefrom")),
        )
        # Подборку клиенту собирает КОД, а не модель: в «1–2 фразы, ~300 знаков» из общего
        # промпта влезает ровно один отель, и клиент получал именно его. Флаг читаем здесь,
        # в одном месте: тогда текст для модели и текст для клиента не могут разъехаться.
        cards_on = await flags.get_flag("tours_cards_enabled", settings.tours_cards_enabled)
        if cards_on:
            cards = _render_cards_for_state(found, state)
            # Повторный поиск в том же ходу перетирает прежние карточки — клиенту уходит
            # подборка по последнему запросу, а не склейка двух.
            state.pending_tour_cards = cards
            state.pending_offer_url = await _offer_url(found, state) if cards else ""
        has_cards = cards_on and bool(state.pending_tour_cards)
        return _tours_search_report(
            found,
            cards_mode=has_cards,
            cards_places=_cards_places_for(found) if has_cards else None,
        )

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
    # Ход мог упасть после поиска — тогда карточки остались в сохранённом состоянии. Без
    # этой чистки они приклеились бы к следующей, совсем другой реплике.
    state.pending_tour_cards, state.pending_offer_url = [], ""
    spec = TOURS_SPEC
    if state.manager_name:
        spec = replace(TOURS_SPEC, system=tours_system_for_manager(state.manager_name))
    return await run_turn(state, user_text, spec)


# ---------------- Визы ----------------
async def _visa_exec_tool(name: str, args: dict, state: DialogState, crm) -> str:
    logger.info("visa tool %s args=%s", name, args)

    if name == "score_visa":
        state.qualification.update({k: v for k, v in args.items() if v})
        _sync_qualified_if_ready(state)
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
