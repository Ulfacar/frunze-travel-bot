"""Ответы Марселя от 13.11.2026: сбор за e-Visa в КР и деловая поездка в США за 600$.

Оба изменения — цена клиенту, поэтому главный предмет проверки здесь не новые ответы,
а то, что при ВЫКЛЮЧЕННЫХ флагах бот говорит ровно то же, что до 19.11.2026.

Суммы в тесте переписаны из сообщения Марселя, а не из кода: «турист виза-52 … 155;
Бизнес виза 1 месяц стандарт-52 … 155$, 2 месяца стандарт-78$-срочная виза-232$,
3 месяца стандарт-93$ срочная виза-279$», «стандарт рас-е 5 раб дней», «срочное рас-е
2 рабочих дня», «туризм 250 доларов деловая 600 долларов».

Путь — настоящий: `run_kg_entry_turn` и `run_visa_turn` с фейковой моделью и
`Orchestrator.handle` для выездного прайса. Живой моделью не мерилось.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

import app.agent.runner as runner
import app.config
from app.channels.base import Message
from app.core import flags
from app.core.state import DialogState
from app.core.visa_pricing import visa_price_reply
from app.knowledge.entry_fees import FEES, REPLY_EN, REPLY_RU, entry_fee_reply

BOT = "getvisa"
USA_BEFORE = ("По США: сопровождение 250$, консульский сбор 185$ с человека оплачивается "
              "отдельно. Итоговую сумму по типу визы и записи подтвердит менеджер.")


@pytest.fixture(autouse=True)
def clean_flags():
    flags.reset()
    yield
    flags.reset()


class FakeBlock:
    def __init__(self, text):
        self.type, self.text, self.name, self.input, self.id = "text", text, None, {}, None

    def model_dump(self):
        return {"type": "text", "text": self.text}


class FakeResp:
    def __init__(self, text):
        self.stop_reason, self.content, self.usage = "end_turn", [FakeBlock(text)], None


def _fake_model(monkeypatch, text="Уточню у специалиста."):
    fake = AsyncMock()
    fake.messages.create = AsyncMock(return_value=FakeResp(text))
    monkeypatch.setattr(runner, "client", lambda: fake)
    return fake


def _entry_state():
    s = DialogState(user_id=f"{BOT}:996700000077", funnel="visa", bot_id=BOT)
    s.qualification["entry_mode"] = "kg_entry"
    s.qualification["kg_entry"] = {}
    return s


# --- A. Таблица сборов — дословно из сообщения Марселя --------------------------

def test_fee_table_matches_the_message():
    assert FEES == (("tourist", 1, 52, 155), ("business", 1, 52, 155),
                    ("business", 2, 78, 232), ("business", 3, 93, 279))


@pytest.mark.parametrize("reply", [REPLY_RU, REPLY_EN])
def test_reply_carries_every_confirmed_sum_and_nothing_else(reply):
    import re
    sums = sorted({int(a or b) for a, b in re.findall(r"\$(\d+)|(\d+)\$", reply)})
    assert sums == [52, 78, 93, 155, 232, 279]
    # Ставки постановления без комиссии и чужие строки таблицы PDF произноситься не должны.
    for foreign in ("50$", "$50", "150$", "$150", "60$", "$60", "225", "270", "25$", "$25"):
        assert foreign not in reply


def test_reply_does_not_claim_single_or_multiple_entry():
    """Марсель кратность не назвал — бот её не выдумывает."""
    for word in ("однократн", "многократн", "single", "multiple"):
        assert word not in REPLY_RU.lower() and word not in REPLY_EN.lower()


def test_reply_does_not_tell_a_visa_free_citizen_to_pay():
    assert REPLY_RU.startswith("Если по вашему гражданству виза нужна")
    assert REPLY_EN.startswith("If your citizenship requires a visa")


# --- B. Когда сбор называется, а когда нет --------------------------------------

@pytest.mark.parametrize("line", [
    "Сколько стоит виза в Кыргызстан?",
    "сколько будет стоить туристическая виза",
    "какая цена деловой визы на 2 месяца?",
    "Какой сбор за электронную визу?",
    "стоимость визы для гражданина Индии",
])
def test_price_of_a_visa_is_answered_in_russian(line):
    assert entry_fee_reply(line) == REPLY_RU


@pytest.mark.parametrize("line", [
    "How much is a visa to Kyrgyzstan?",
    "what is the e-visa fee for a tourist",
    "business visa cost for 3 months please",
])
def test_price_of_a_visa_is_answered_in_english(line):
    assert entry_fee_reply(line) == REPLY_EN


@pytest.mark.parametrize("line", [
    "",
    "виза",
    "Сколько дней можно находиться по визе?",          # срок, не цена
    "сколько делается виза?",                           # срок, не цена
    "стоит ли мне получать визу заранее?",             # «стоит» не о деньгах
    "какой сбор документов нужен для визы?",           # сбор — не деньги
    "Сколько стоит?",                                   # виза не названа
    "Сколько стоит рабочая виза?",                      # сумм по рабочим нет
    "сколько стоит виза и разрешение на работу",
    "сколько стоит студенческая виза",
    "какой штраф за просрочку визы, сколько стоит",
    "сколько стоит продление визы",
    "сколько стоит транзитная виза",
    "Сколько будет стоить виза и ваши услуги?",         # цену услуг не знаем
    "how much is the fine for overstaying my visa",
    "how much is a work visa",
    "how much is a visa extension",
    "what is your agency fee for the visa",
    # Находки ревью 19.11: липкий въездной режим и вопрос про ДРУГУЮ страну.
    "how much is visa to Turkey",
    "price of visa to Dubai",
    "how much is a US visa",
    "сколько стоит виза в Турцию",
    # Срок и кратность вне таблицы, вопрос за другого человека, наши услуги.
    "сколько стоит годовая виза",
    "сколько стоит виза на 6 месяцев",
    "сколько стоит многократная виза",
    "сколько стоит виза за ребёнка",
    "how much is a visa for my wife",
    "how much is a multiple entry visa for 6 months",
    "сколько стоит эл виза для индусов, и сколько стоит ваша помощь",
    "what is the price of kyrgyz visa and your commission",
    # Кыргызский и опечатки не распознаём — ход идёт обычным путём, без сумм.
    "виза канча турат?",
    "визанын баасы канча",
    "сколко стоит виза",
])
def test_everything_outside_the_table_is_left_to_the_normal_path(line):
    assert entry_fee_reply(line) is None


# --- C. Въездная ветка: настоящий путь через run_kg_entry_turn ------------------

def test_flag_off_the_entry_turn_goes_to_the_model_and_names_no_sum(monkeypatch):
    fake = _fake_model(monkeypatch)
    state = _entry_state()
    reply = asyncio.run(runner.run_kg_entry_turn(state, "Сколько стоит виза в Кыргызстан?"))
    assert fake.messages.create.await_count == 1, "при OFF ход обязан идти в модель"
    assert reply is not None and "$" not in reply


def test_flag_on_the_entry_turn_answers_from_the_table_without_the_model(monkeypatch):
    fake = _fake_model(monkeypatch)
    state = _entry_state()

    async def go():
        await flags.set_flag(f"kg_entry_fees_reply_enabled:{BOT}", True)
        return await runner.run_kg_entry_turn(state, "Сколько стоит виза в Кыргызстан?")

    assert asyncio.run(go()) == REPLY_RU
    assert fake.messages.create.await_count == 0
    assert state.history[-2:] == [
        {"role": "user", "content": "Сколько стоит виза в Кыргызстан?"},
        {"role": "assistant", "content": REPLY_RU}]


def test_flag_on_for_another_bot_does_not_leak(monkeypatch):
    fake = _fake_model(monkeypatch)
    state = _entry_state()

    async def go():
        await flags.set_flag("kg_entry_fees_reply_enabled:getvisa_tg", True)
        return await runner.run_kg_entry_turn(state, "Сколько стоит виза в Кыргызстан?")

    reply = asyncio.run(go())
    assert fake.messages.create.await_count == 1 and "$" not in (reply or "")


def test_flag_on_out_of_scope_question_still_goes_to_the_model(monkeypatch):
    fake = _fake_model(monkeypatch)
    state = _entry_state()

    async def go():
        await flags.set_flag(f"kg_entry_fees_reply_enabled:{BOT}", True)
        return await runner.run_kg_entry_turn(state, "Сколько стоит рабочая виза?")

    reply = asyncio.run(go())
    assert fake.messages.create.await_count == 1 and "$" not in (reply or "")


def test_flag_on_intercepted_dialogue_stays_silent(monkeypatch):
    fake = _fake_model(monkeypatch)
    state = _entry_state()
    state.intercepted = True

    async def go():
        await flags.set_flag(f"kg_entry_fees_reply_enabled:{BOT}", True)
        return await runner.run_kg_entry_turn(state, "Сколько стоит виза в Кыргызстан?")

    assert asyncio.run(go()) is None
    assert fake.messages.create.await_count == 0


def test_model_still_cannot_name_a_sum_in_the_entry_branch(monkeypatch):
    """Флаг открывает таблицу, а не ремень: сумму от модели валидатор по-прежнему режет."""
    _fake_model(monkeypatch, "Виза стоит 52$ и ещё 100$ за наши услуги.")
    state = _entry_state()

    async def go():
        await flags.set_flag(f"kg_entry_fees_reply_enabled:{BOT}", True)
        return await runner.run_kg_entry_turn(state, "А что по деньгам в итоге выйдет?")

    reply = asyncio.run(go())
    assert "$" not in reply
    from app.agent.entry_guards import SAFE_PRICE_REPLY
    assert SAFE_PRICE_REPLY in reply, "заменой должен быть ответ ремня, а не пустота"


def test_follow_up_after_the_table_cannot_make_the_model_repeat_a_sum(monkeypatch):
    """Суммы остаются в истории, но повторить их модель не может: ремень прежний.

    «А срочная сколько?» без слова «виза» в таблицу не попадает и идёт в модель. Даже
    верное «155$» от модели режется — клиент получит «уточнит специалист». Это цена
    того, что ремень не ослаблен; поведение закреплено, чтобы не изменилось молча.
    """
    _fake_model(monkeypatch, "Срочная обойдётся в 155$.")
    state = _entry_state()

    async def go():
        await flags.set_flag(f"kg_entry_fees_reply_enabled:{BOT}", True)
        first = await runner.run_kg_entry_turn(state, "Сколько стоит виза в Кыргызстан?")
        second = await runner.run_kg_entry_turn(state, "А срочная сколько?")
        return first, second

    first, second = asyncio.run(go())
    assert first == REPLY_RU
    assert "$" not in second


# --- D. США: деловая поездка 600$ ------------------------------------------------

@pytest.mark.parametrize("line", [
    "Сколько стоит виза в США?",
    "Сколько стоит деловая виза в США?",
    "цена бизнес визы в америку",
])
def test_usa_reply_is_unchanged_without_the_flag(line):
    assert visa_price_reply(line) == USA_BEFORE


@pytest.mark.parametrize("line", [
    "Сколько стоит деловая виза в США?",
    "цена бизнес визы в америку",
    "еду на конференцию в Штаты, сколько стоит виза",
    "сколько стоит виза B1 в США",
])
def test_usa_business_purpose_gets_600(line):
    reply = visa_price_reply(line, usa_business=True)
    assert "600$" in reply and "185$" in reply and "250$" not in reply


@pytest.mark.parametrize("line", [
    # Находки ревью 19.11: отрицание и туристические слова рядом с деловым маркером.
    "сколько стоит виза в США для туризма, не бизнес",
    "цена визы в США, у меня нет бизнеса, еду отдыхать",
    "сколько стоит виза в США на выставку и потом отдых",
    "США виза цена B1/B2",
    "цена визы в США: бизнес или туризм?",
])
def test_usa_doubtful_purpose_gets_both_rates_never_600_alone(line):
    reply = visa_price_reply(line, usa_business=True)
    assert "250$" in reply and "600$" in reply


def test_usa_without_a_purpose_gets_both_rates():
    reply = visa_price_reply("Сколько стоит виза в США?", usa_business=True)
    assert "250$" in reply and "600$" in reply and "185$" in reply


@pytest.mark.parametrize("line,marks", [
    ("Цена шенген визы?", ("100€", "90€", "30€")),
    ("сколько стоит деловая виза в Китай", ("300$",)),
    ("сколько стоит бизнес виза в Канаду", ("300$",)),
])
def test_other_countries_do_not_change_with_the_flag(line, marks):
    assert visa_price_reply(line, usa_business=True) == visa_price_reply(line)
    assert "600" not in visa_price_reply(line, usa_business=True)
    for mark in marks:
        assert mark in visa_price_reply(line)


def test_non_price_message_is_still_not_captured_with_the_flag():
    assert visa_price_reply("Хочу деловую визу в США", usa_business=True) is None


def _visa_state():
    return DialogState(user_id=f"{BOT}:996700000078", funnel="visa", bot_id=BOT)


def test_run_visa_turn_reads_the_flag(monkeypatch):
    _fake_model(monkeypatch)
    line = "Сколько стоит деловая виза в США?"

    async def go(on):
        flags.reset()
        if on:
            await flags.set_flag("visa_usa_business_price_enabled", True)
        return await runner.run_visa_turn(_visa_state(), line)

    assert asyncio.run(go(False)) == USA_BEFORE
    assert "600$" in asyncio.run(go(True))


def test_model_gets_the_usa_note_only_with_the_flag(monkeypatch):
    line = "Расскажите про деловую поездку в Штаты"     # не вопрос о цене → идёт в модель

    async def go(on):
        flags.reset()
        fake = _fake_model(monkeypatch)
        if on:
            await flags.set_flag("visa_usa_business_price_enabled", True)
        await runner.run_visa_turn(_visa_state(), line)
        sent = fake.messages.create.await_args.kwargs
        return str(sent["messages"]), sent["system"]

    off_messages, off_system = asyncio.run(go(False))
    on_messages, on_system = asyncio.run(go(True))
    assert "600$" not in off_messages
    assert "600$" in on_messages
    assert on_system == off_system, "системный промпт от флага зависеть не должен: кэш"


def test_usa_note_is_not_attached_when_usa_was_never_mentioned(monkeypatch):
    fake = _fake_model(monkeypatch)

    async def go():
        await flags.set_flag("visa_usa_business_price_enabled", True)
        await runner.run_visa_turn(_visa_state(), "Хочу деловую визу в Канаду")
        return str(fake.messages.create.await_args.kwargs["messages"])

    assert "600$" not in asyncio.run(go())


def test_entry_branch_never_gets_the_usa_note(monkeypatch):
    fake = _fake_model(monkeypatch)

    async def go():
        await flags.set_flag("visa_usa_business_price_enabled", True)
        await runner.run_kg_entry_turn(_entry_state(), "Я из Индии, хочу приехать туристом")
        return str(fake.messages.create.await_args.kwargs["messages"])

    assert "600$" not in asyncio.run(go())


def test_orchestrator_quotes_600_only_with_the_flag(monkeypatch):
    """Прайс стреляет в оркестраторе раньше воронки — проверяем именно этот вызов."""
    from app.config import BotConfig
    from app.core.orchestrator import Orchestrator

    class Collect:
        channel = "telegram"

        def __init__(self):
            self.sent = []

        async def parse(self, raw):
            raise NotImplementedError

        async def send(self, chat_id, text, **kw):
            self.sent.append(text)
            return "1"

    async def go(on, uid):
        flags.reset()
        await flags.set_flag("bots_enabled", True)
        await flags.set_flag("night_mode_enabled", False)
        if on:
            await flags.set_flag("visa_usa_business_price_enabled", True)
        monkeypatch.setattr(app.config.settings, "openrouter_api_key", "", raising=False)
        channel = Collect()
        orch = Orchestrator(channel=channel, bot=BotConfig(id=BOT, scenario="visa"))
        user = f"{BOT}:{uid}"
        await orch.handle(Message(channel="telegram", user_id=user, chat_id=user,
                                  text="Сколько стоит деловая виза в США?"))
        return "\n".join(channel.sent)

    off = asyncio.run(go(False, "996700000081"))
    on = asyncio.run(go(True, "996700000082"))
    assert "250$" in off and "600" not in off
    assert "600$" in on and "250$" not in on


def test_both_flags_default_off():
    assert app.config.settings.kg_entry_fees_reply_enabled is False
    assert app.config.settings.visa_usa_business_price_enabled is False
