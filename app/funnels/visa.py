"""Воронка «Визы» (бренд Frunze Travel, менеджер Медина).

Этапы: приветствие → опросник → мягкая честная подача → приглашение в офис/онлайн → CRM.
Главная цель — довести клиента до консультации эксперта. БЕЗ обещаний по визе; цены не называем.
Откалибровано по реальным диалогам (см. docs/frunze-dialog-style.md).
"""
from __future__ import annotations

from app.channels.base import Message
from app.config import settings
from app.agent.llm import llm_available
from app.core.branding import GETVISA_OFFICE_ADDRESS, is_english_speaking
from app.core.state import DialogState
from app.funnels.base import collect_qualification
from app.integrations.crm import get_crm

# Опросник Frunze Travel из реальных диалогов Медины.
REQUIRED_FIELDS = [
    "name", "country", "age", "marital_status", "occupation",
    "prior_countries", "companions", "english_level", "dates", "prior_refusal",
]


def _required_fields(qualification: dict) -> list[str]:
    """REQUIRED_FIELDS с учётом страны: по англоязычным визам не спрашиваем про английский.

    `country` в опроснике идёт раньше `english_level`, поэтому к моменту, когда бот дошёл бы
    до вопроса про английский, страна уже собрана — гейтинг срабатывает корректно.
    """
    if is_english_speaking(qualification.get("country")):
        return [f for f in REQUIRED_FIELDS if f != "english_level"]
    return REQUIRED_FIELDS


# Передача человеку по въездному вопросу. Двуязычно, потому что клиент-иностранец
# пишет по-английски, а Б.2 п.2 требует отвечать на языке клиента. Без чисел и сумм:
# цен бот не называет (решение владельца), а сроки без подтверждения — тоже факт.
ENTRY_HANDOVER = (
    "Здравствуйте! Я помощник Frunze Travel — помогаем с визами и пребыванием "
    "в Кыргызстане. Передаю ваш вопрос специалисту: он уточнит условия именно "
    "для вашего гражданства и цели поездки и ответит в рабочее время." + "\n\n" +
    "Hello! I am the Frunze Travel assistant — we help with visas and stays in "
    "Kyrgyzstan. I am passing your question to a specialist: they will confirm the "
    "rules for your citizenship and purpose of travel and reply during working hours."
)


# Уточняющий вопрос о направлении (маршрутизация v2, флаг `kg_entry_routing_v2_enabled`).
# Нужен, потому что на одном номере живут два разных бизнеса: выездные визы для граждан
# КР и въезд иностранцев в КР. Прежде при сомнении диалог молча уходил в выездную
# воронку — и иностранца спрашивали, в какую страну ему нужна виза.
ENTRY_DIRECTION_QUESTION = (
    "Уточню один момент, чтобы не ошибиться: вам нужна виза **в Кыргызстан** — то есть "
    "вы приезжаете к нам, — или виза **из Кыргызстана** в другую страну?"
)
ENTRY_DIRECTION_QUESTION_EN = (
    "One quick question so I get this right: do you need a visa **to Kyrgyzstan** — "
    "that is, you are coming here — or a visa **from Kyrgyzstan** to another country?"
)


# Не разобрали ответ про направление — отдаём человеку, а не угадываем.
ENTRY_DIRECTION_HANDOVER = (
    "Чтобы точно не ошибиться, передаю ваш вопрос специалисту: он уточнит детали и "
    "ответит в рабочее время."
)
ENTRY_DIRECTION_HANDOVER_EN = (
    "To make sure we get this right, I am passing your question to a specialist: "
    "they will check the details and reply during working hours."
)

# Короткие ответы на вопрос про направление. Клиент отвечает не фразой из ТЗ, а
# «сюда», «туда», «к вам», «отсюда» — и прежде это давало `unknown`.
_ANSWER_HERE = (
    "сюда", "к вам", "в кыргыз", "в киргиз", "кыргызстанга", "приеду", "приехать",
    "въезд", "въехать", "у вас", "к тебе", "to kyrgyz", "coming here", "to you",
    "here", "inbound", "entry",
)
_ANSWER_AWAY = (
    "туда", "отсюда", "из кыргыз", "из киргиз", "за границу", "за рубеж", "выезд",
    "выехать", "уехать", "из страны", "from kyrgyz", "abroad", "outbound", "exit",
)


def _direction_answer(text: str) -> str | None:
    """Ответ клиента на вопрос «в Кыргызстан или из Кыргызстана?».

    `None` — ответ не разобрали. Проверяем «отсюда» ПЕРВЫМ: во фразе «из Кыргызстана»
    есть и «кыргыз», и признак отъезда, и верный ответ — выезд.
    """
    low = (text or "").strip().lower()
    if not low:
        return None
    if any(w in low for w in _ANSWER_AWAY):
        return "outbound"
    if any(w in low for w in _ANSWER_HERE):
        return "kg_entry"
    return None


def is_english_speaking_text(text: str | None) -> bool:
    """Латиница без кириллицы — отвечаем по-английски."""
    from app.core.entry_intent import looks_english
    return looks_english(text or "")


class VisaFunnel:
    name = "visa"

    async def handle(self, msg: Message, state: DialogState) -> str | None:
        entry = await _entry_branch(msg, state)
        if entry is not None:
            return entry

        # Боевой режим: живой AI-диалог через OpenRouter (tool-use).
        if await llm_available():
            from app.agent.runner import run_visa_turn
            return await run_visa_turn(state, msg.text)

        # Fallback без ключа: детерминированный опросник (для тестов/демо офлайн).
        question = collect_qualification(state, msg.text, _required_fields(state.qualification), _ask_for)
        if question is not None:
            return question

        state.stage = "scoring"
        crm = get_crm()
        state.deal_id = state.deal_id or await crm.create_lead(
            contact={"user_id": state.user_id}, funnel=self.name, data=state.qualification
        )
        await crm.update_stage(state.deal_id, "office_consultation")
        # Внутренний сигнал силы кейса влияет только на тон — клиенту % не обещаем.
        return office_invitation(visa_category(score_visa(state.qualification)))


def office_invitation(category: str) -> str:
    """Мягкое честное приглашение на консультацию (без обещаний и без цен)."""
    if category == "высокие":
        opener = "Спасибо! По вашим данным кейс выглядит перспективно 😊"
    elif category == "средние":
        opener = "Спасибо за ответы! С вашим кейсом точно есть с чем работать."
    else:
        opener = "Спасибо за ответы! Случай требует внимательной подготовки — но это решаемо."
    return (
        f"{opener} Многое зависит от грамотно заполненной анкеты и подготовки к интервью — "
        "именно это мы и берём на себя. Давайте пригласим вас на консультацию к эксперту: "
        f"можно подойти к нам в офис ({GETVISA_OFFICE_ADDRESS}) или начать онлайн. "
        "Документы и детали подскажет менеджер. Когда вам удобно? 🙏"
    )


def score_visa(data: dict) -> int:
    """ВНУТРЕННИЙ ориентир силы кейса (0–100) — только для выбора тона бота.

    Клиенту точный процент НЕ показываем и визу не обещаем (см. office_invitation).
    [?] Методика заказчиком не задана — это эвристика, не обещание.
    """
    base = 50
    if data.get("prior_countries"):
        base += 15  # есть история поездок — плюс
    if str(data.get("prior_refusal", "")).strip().lower() in {"", "нет", "не было", "no"}:
        base += 15  # не было отказов — плюс
    else:
        base -= 15  # был отказ — минус
    if data.get("occupation"):
        base += 5
    return max(5, min(95, base))


def visa_category(pct: int) -> str:
    """% → внутренняя категория (для тона; клиенту число не озвучиваем)."""
    if pct >= 70:
        return "высокие"
    if pct >= 45:
        return "средние"
    return "низкие"


def _ask_for(field: str) -> str:
    questions = {
        "name": "Здравствуйте! Меня зовут Медина, я ваш личный визовый эксперт Frunze Travel 😊 Как могу к вам обращаться?",
        "country": "Виза в какую страну вас интересует?",
        "age": "Подскажите, сколько вам лет?",
        "marital_status": "Ваше семейное положение? (в браке / не в браке, есть ли дети)",
        "occupation": "Кем работаете или где учитесь?",
        "prior_countries": "Какие страны посещали ранее? (если были визы — какие)",
        "companions": "Поедете один(одна) или с семьёй?",
        "english_level": "Как у вас с английским — свободно, базово, не владеете?",
        "dates": "На какие даты планируете поездку?",
        "prior_refusal": "Были ли ранее отказы в визе? Если да — в какую страну и в каком году?",
    }
    return questions.get(field, "Расскажите, пожалуйста, подробнее.")


async def _entry_branch(msg: Message, state: DialogState) -> str | None:
    """Въездные визы в КР: своя тема на том же номере. None — обычный путь воронки.

    Воронка остаётся `visa`, режим помечается двумя ключами в анкете. Так сделано
    осознанно: значение воронки продублировано примерно в десяти местах (аналитика,
    брифы, FAQ, дожим, админка) и зашито констрейнтом БД
    `direction IN ('tours','visa','tickets')`. Новое значение падало бы на уровне базы,
    а два ключа не трогают ни один из этих списков. Ключей именно два, а не три:
    `derive_stage` считает непустые поля, и порог «подбора» не должен перескакиваться
    первой же репликой.

    Пока речь бота не разрешена (модуль C ядра), исход один: передать человеку. Это не
    заглушка, а требование Б.2 п.6 «в любой неуверенности — уточню у менеджера».
    """
    from app.core import flags
    from app.core.entry_intent import detect

    # Персональный ключ по боту: `kg_entry_enabled:<bot_id>`. Так ветку включают в
    # песочнице Telegram, не будя боевой номер GetVisa с живыми клиентами.
    if not await flags.get_bot_flag("kg_entry_enabled", state.bot_id,
                                    settings.kg_entry_enabled):
        return None

    sticky = state.qualification.get("entry_mode")
    routing_v2 = await flags.get_bot_flag("kg_entry_routing_v2_enabled", state.bot_id,
                                          settings.kg_entry_routing_v2_enabled)
    intent = detect(msg.text or "", sticky=sticky, routing_v2=routing_v2)

    # Вопрос про направление уже задан — разбираем ОТВЕТ, прежде чем решать что-либо
    # ещё. Без этого «туда», «сюда», «не знаю» и смайлик давали `unknown`, и клиент
    # молча уезжал в выездную воронку: ровно то, чего быть не должно. Найдено
    # независимым ревью 28.10 последовательными вызовами этой функции.
    if routing_v2 and state.qualification.get("entry_direction_asked") \
            and not state.qualification.get("entry_mode"):
        answered = _direction_answer(msg.text or "")
        if answered == "kg_entry":
            intent = "kg_entry"
        elif answered == "outbound":
            return None                       # выездной клиент, прежний путь воронки
        elif intent not in ("kg_entry", "outbound"):
            # Ответ не разобрали. Угадывать нельзя, спрашивать второй раз бессмысленно —
            # отдаём человеку.
            state.stage = "manager"
            return (ENTRY_DIRECTION_HANDOVER_EN if is_english_speaking_text(msg.text)
                    else ENTRY_DIRECTION_HANDOVER)

    if intent == "ambiguous":
        # Кыргызстан назван либо клиент назвал своё иностранное гражданство, а
        # направление неясно. Прежде такой диалог молча уезжал в выездную воронку, и
        # бот спрашивал иностранца «в какую страну вам нужна виза?». Спрашиваем прямо.
        #
        # Режим НЕ запоминаем: ответ разбирает блок выше и сильный маркер детектора.
        if state.qualification.get("entry_direction_asked"):
            state.stage = "manager"
            return (ENTRY_DIRECTION_HANDOVER_EN if is_english_speaking_text(msg.text)
                    else ENTRY_DIRECTION_HANDOVER)
        state.qualification["entry_direction_asked"] = True
        return ENTRY_DIRECTION_QUESTION_EN if is_english_speaking_text(msg.text) \
            else ENTRY_DIRECTION_QUESTION

    if intent != "kg_entry":
        return None

    state.qualification["entry_mode"] = "kg_entry"
    state.qualification.setdefault("kg_entry", {})

    if await llm_available():
        from app.agent.runner import run_kg_entry_turn
        return await run_kg_entry_turn(state, msg.text)

    # Без ключа модели диалог вести нечем: честно передаём человеку.
    state.stage = "manager"
    return ENTRY_HANDOVER
