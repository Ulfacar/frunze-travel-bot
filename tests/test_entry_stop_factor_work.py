"""ГЕЙТ: стоп-фактор 4.1 — клиент просит туристическую визу, чтобы по ней работать.

ТЗ 4.1, с. 30, строка «Цель — работа, а просит TS/B».

Написан ДО правки и исполнителем не редактируется по ходу.

Что доказываем, и почему именно это. История `stop_work_on_tourist` помечена
`covered: false` с самого начала; `ai/STATE.md` от 23.10 называет причину: на живой
модели бот задавал уточняющий вопрос вместо ответа, слова «нельзя» клиент не слышал.
Поэтому тест проверяет ПУТЬ целиком через `run_kg_entry_turn` с фейковой моделью,
которая ведёт себя так же плохо: болтает, не зовёт инструменты и называет передачу
словами вместо вызова `kg_entry_handoff`.

Почему тест, а не прогон историй. В этой среде нет `OPENROUTER_API_KEY`, и воронка
уходит в `visa.ENTRY_HANDOVER` ещё до `run_turn` — прогон `run_entry_stories.py`
локально этот код не задевает вообще и зелёным быть не может. Замер на живой модели
остаётся непроверенным, и это сказано в отчёте, а не спрятано.

Урок 21.10, записанный в этом каталоге: тест, подогнанный под мой код вместо реального
пути, бывает зелёным при сломанной функции.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

import app.agent.runner as runner
import app.config
from app.agent import entry_guards as g
from app.agent.validator import validate_reply
from app.core.state import DialogState


class FakeBlock:
    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type, self.text, self.name = type, text, name
        self.input, self.id = input or {}, id

    def model_dump(self):
        return {"type": self.type, "text": self.text, "name": self.name,
                "input": self.input, "id": self.id}


class FakeResp:
    def __init__(self, stop_reason, content, usage=None):
        self.stop_reason, self.content, self.usage = stop_reason, content, usage


def _text(text):
    return FakeResp("end_turn", [FakeBlock("text", text=text)])


def _patch(monkeypatch, *responses):
    fake = AsyncMock()
    fake.messages.create = AsyncMock(side_effect=list(responses))
    monkeypatch.setattr(runner, "client", lambda: fake)
    return fake


@pytest.fixture()
def state():
    s = DialogState(user_id="getvisa:996700000098", funnel="visa")
    s.qualification["entry_mode"] = "kg_entry"
    s.qualification["kg_entry"] = {}
    return s


@pytest.fixture()
def flag_on(monkeypatch):
    """Флаг включаем явно. Дефолт OFF — это тоже предмет проверки, см. ниже."""
    monkeypatch.setattr(app.config.settings, "kg_entry_stop_factors_enabled", True,
                        raising=False)


# --- A. Распознавание реплики клиента -------------------------------------------

@pytest.mark.parametrize("line", [
    "Я из Индии, оформите мне туристическую визу, а я по ней поработаю пару месяцев на стройке.",
    "мне нужна туристическая виза, хочу работать в Бишкеке",
    "можно по гостевой визе подработать?",
    "я без визы на 60 дней, успею поработать на заводе?",
    "оформите деловую визу, буду трудоустроен в местной фирме",
    "I need a tourist visa and I want to work there for a few months",
    "can I work on a visitor visa?",
    "visa-free entry — can I get a job meanwhile?",
])
def test_declared_work_on_a_visitor_status_is_recognised(line):
    assert g.declares_work_on_visitor_visa(line)


@pytest.mark.parametrize("line", [
    # Намерение работать без расхождения с документом — это обычная квалификация
    # по цели (`work_purpose_review`), а не стоп-фактор 4.1.
    "хочу работать в Кыргызстане, что нужно оформить?",
    "I want to work in Kyrgyzstan, what do I need?",
    # Законная деловая поездка: человек работает ГДЕ-ТО ЕЩЁ и едет на встречи.
    "я работаю в банке в Дубае, нужна деловая виза на переговоры",
    # Туристическая поездка без работы.
    "хочу туристическую визу на две недели, поедем с женой отдыхать",
    "just a tourist visa for a holiday, no work",
    "",
    "виза",
])
def test_ordinary_requests_do_not_trigger_the_stop_factor(line):
    assert not g.declares_work_on_visitor_visa(line)


# Таблица независимого ревью 28.10. Каждая реплика там воспроизведена запуском, и
# каждая показывала дефект: пять ложных срабатываний и пять пропусков. Прибиваю их
# тестом, чтобы находка не вернулась.

@pytest.mark.parametrize("line", [
    "Мне нужна туристическая виза, работать не буду.",
    "После туристической поездки вернусь работать в Индию.",
    "Хочу работать в туристической компании, оформите рабочую визу.",
    "I do not want to work, I need a tourist visa for a holiday.",
    "My employer approved my holiday. I need a tourist visa.",
])
def test_review_false_positives_are_gone(line):
    """Клиент прямо сказал, что работать не будет, либо просит рабочую визу."""
    assert not g.declares_work_on_visitor_visa(line)


@pytest.mark.parametrize("line", [
    "Нужна виза TS, хочу работать на стройке.",
    "Оформите визу B, буду работать в Бишкеке.",
    "Нужна туристическая виза, буду строить дома за деньги.",
    "I need a tourist visa. I will work in Bishkek.",
    "I need a business visa. I will be working at a local factory.",
    # PM-ревью 30.10: «подрабатывать» (несовершенный вид) шаблон `подработа\w*` не ловил.
    "Хочу туристическую визу, буду там немного подрабатывать.",
    "Еду туристом, хочу подрабатывать курьером.",
])
def test_review_false_negatives_are_caught(line):
    """Прямой стоп-фактор: категория названа кодом либо работа — будущим временем."""
    assert g.declares_work_on_visitor_visa(line)


@pytest.mark.parametrize("reply,said", [
    # Посторонние отрицания: запрет НЕ произнесён, бот обязан его добавить.
    ("I cannot answer your question about work. A specialist will help.", False),
    ("Работаем с девяти. Нельзя оплатить картой.", False),
    # Настоящий запрет в одном предложении: добавлять второй раз не нужно.
    ("По туристической визе работать нельзя, это другая цель.", True),
    ("You may not work on a tourist visa.", True),
    ("Работа по туристической визе запрещена.", True),
])
def test_only_a_real_prohibition_counts_as_said(reply, said):
    assert g.states_the_prohibition(reply) is said


# --- B. Ход целиком: запрет произнесён и заявка создана --------------------------

BAD_MODEL_REPLY = ("Здравствуйте! Передаю ваш вопрос специалисту: он уточнит условия "
                   "именно для вашего гражданства и цели поездки.")


def test_prohibition_is_spoken_and_a_real_handoff_is_created(monkeypatch, state, flag_on):
    """Модель молчит про запрет и не зовёт инструменты — ровно как на проде 28.10."""
    _patch(monkeypatch, _text(BAD_MODEL_REPLY))
    reply = asyncio.run(runner.run_kg_entry_turn(
        state, "Я из Индии, оформите мне туристическую визу, "
               "а я по ней поработаю пару месяцев на стройке."))
    kg = state.qualification["kg_entry"]

    assert "нельзя" in reply.lower()
    assert BAD_MODEL_REPLY in reply, "ответ модели не выбрасываем, запрет ставим перед ним"
    # Передача — настоящая, а не на словах.
    assert state.stage == "manager"
    assert "4.1" in kg["handoff_reason"]
    assert kg.get("intake"), "машинный снимок заявки обязан появиться"
    assert "4.1" in kg["intake"]["handoff_reason"]


def test_english_client_gets_the_prohibition_in_english(monkeypatch, state, flag_on):
    _patch(monkeypatch, _text("Hello! I am passing your question to a specialist."))
    reply = asyncio.run(runner.run_kg_entry_turn(
        state, "I need a tourist visa and I want to work there for a few months"))
    assert "may not work" in reply.lower()
    assert "нельзя" not in reply.lower(), "русская вставка в английский ответ — сломанный бот"


def test_the_prohibition_is_not_repeated_when_the_model_said_it_itself(monkeypatch,
                                                                      state, flag_on):
    said = ("По туристической визе работать нельзя — это другая цель пребывания. "
            "Передам специалисту.")
    _patch(monkeypatch, _text(said))
    reply = asyncio.run(runner.run_kg_entry_turn(
        state, "оформите туристическую визу, хочу поработать на стройке"))
    assert reply.count("нельзя") == 1
    # Заявка всё равно обязана быть: слова модели передачей не являются.
    assert state.stage == "manager"


def test_stop_factor_works_when_the_tool_loop_is_exhausted(monkeypatch, state, flag_on):
    """Модель шесть раз вернула вызов инструмента вместо ответа.

    Прежде клиент получал «давайте уточню детали ещё раз» — ни запрета, ни заявки.
    Исправление зависело от того, дойдёт ли модель до текстового ответа; найдено
    независимым ревью 28.10 запуском, поэтому проверяется путём, а не намерением.
    """
    tool = FakeResp("tool_use", [FakeBlock("tool_use", name="kg_entry_facts",
                                           input={"purpose": "work_hire"}, id="t1")])
    _patch(monkeypatch, *[tool] * runner.MAX_TOOL_ITERATIONS)
    reply = asyncio.run(runner.run_kg_entry_turn(
        state, "оформите туристическую визу, хочу поработать на стройке"))
    assert "нельзя" in reply.lower()
    assert state.stage == "manager"
    assert "4.1" in state.qualification["kg_entry"]["handoff_reason"]


def test_a_handoff_the_model_already_made_is_not_overwritten(monkeypatch, state, flag_on):
    state.qualification["kg_entry"]["handoff_reason"] = "клиент попросил менеджера"
    _patch(monkeypatch, _text("Передаю специалисту."))
    asyncio.run(runner.run_kg_entry_turn(
        state, "оформите туристическую визу, хочу поработать на стройке"))
    assert state.qualification["kg_entry"]["handoff_reason"] == "клиент попросил менеджера"


# --- C. Флаг и границы ----------------------------------------------------------

def test_default_is_off_so_the_live_getvisa_number_does_not_change(monkeypatch, state):
    """Без флага поведение дословно прежнее: ветка уже на боевом номере."""
    _patch(monkeypatch, _text(BAD_MODEL_REPLY))
    reply = asyncio.run(runner.run_kg_entry_turn(
        state, "оформите туристическую визу, хочу поработать на стройке"))
    assert reply == BAD_MODEL_REPLY
    assert state.stage != "manager"
    assert not state.qualification["kg_entry"].get("handoff_reason")


def test_ordinary_tourist_request_is_untouched_even_with_the_flag_on(monkeypatch,
                                                                    state, flag_on):
    plain = "Здравствуйте! На какие даты планируете поездку?"
    _patch(monkeypatch, _text(plain))
    reply = asyncio.run(runner.run_kg_entry_turn(
        state, "хочу туристическую визу на две недели, поедем отдыхать"))
    assert reply == plain
    assert state.stage != "manager"


# --- D. Сама формулировка запрета безопасна -------------------------------------

@pytest.mark.parametrize("statement", [g.WORK_STOP_REPLY, g.WORK_STOP_REPLY_EN])
def test_the_statement_survives_every_belt_with_nothing_allowed(statement):
    """Запрет ставится ПОСЛЕ валидатора, поэтому доказываем, что он и так чист.

    Иначе формулировка однажды обрастёт правилом («нужно Единое разрешение»), ремень
    неподтверждённых утверждений вырежет её на следующем ходу — а здесь она уже
    уехала клиенту в обход проверки.
    """
    clean, violations = validate_reply(statement, "visa", profile="kg_entry",
                                       allowed_claims=frozenset())
    assert clean.strip() == statement.strip()
    assert violations == []


def test_the_statement_does_not_promise_a_unified_permit():
    """Единое разрешение — поле `unified_permit`, визовой стране оно не разрешено.

    Рекомендация продукта уходит менеджеру в причину передачи, не клиенту.
    """
    for statement in (g.WORK_STOP_REPLY, g.WORK_STOP_REPLY_EN):
        low = statement.lower()
        assert "единое разрешение" not in low and "unified" not in low
        assert "$" not in statement
        assert g.claimed_fields(statement) == frozenset()
    assert "Единое разрешение" in g.WORK_STOP_HANDOFF_REASON
