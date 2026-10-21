"""ГЕЙТ: один ход въездного диалога целиком — от реплики клиента до ответа.

Написан ДО реализации и исполнителем НЕ редактируется.

Здесь проверяется то, что нельзя проверить по кускам: что факты записались, движок
посчитал режим, валидатор не дал произнести неподтверждённое, а контекст в промпте
остался компактным.

Модель заменена фейком. Это принципиально: тест обязан проверять ПУТЬ, а не качество
формулировок модели. Урок 21.10 — тест, написанный под мой код вместо реального пути,
бывает зелёным при сломанной функции.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

import app.agent.runner as runner
import app.config
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


def _tool(name, inp, id="t1"):
    return FakeResp("tool_use", [FakeBlock("tool_use", name=name, input=inp, id=id)])


def _text(text):
    return FakeResp("end_turn", [FakeBlock("text", text=text)])


def _patch(monkeypatch, *responses):
    fake = AsyncMock()
    fake.messages.create = AsyncMock(side_effect=list(responses))
    monkeypatch.setattr(runner, "client", lambda: fake)
    return fake


@pytest.fixture()
def state():
    s = DialogState(user_id="getvisa:996700000099", funnel="visa")
    s.qualification["entry_mode"] = "kg_entry"
    s.qualification["kg_entry"] = {}
    return s


def _say(monkeypatch, value):
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", value,
                        raising=False)


# --- A. Факты записываются и распознаются ---------------------------------------

def test_facts_are_stored_and_citizenship_resolved(monkeypatch, state):
    _say(monkeypatch, False)
    _patch(monkeypatch,
           _tool("kg_entry_facts", {"citizenship": "India", "purpose": "business_meeting",
                                    "entry_on": "2026-11-10", "exit_on": "2026-11-20"}),
           _text("Понял вас. Уточню условия у специалиста."))
    asyncio.run(runner.run_kg_entry_turn(state, "I am from India, business trip in November"))
    kg = state.qualification["kg_entry"]
    assert kg["citizenship"] == "India"
    assert kg["citizenship_iso3"] == "IND", "английское название не распознано"
    assert kg["purpose"] == "business_meeting"


def test_unknown_country_does_not_pretend_to_be_resolved(monkeypatch, state):
    _say(monkeypatch, False)
    _patch(monkeypatch,
           _tool("kg_entry_facts", {"citizenship": "Нарния"}),
           _text("Уточню у специалиста."))
    asyncio.run(runner.run_kg_entry_turn(state, "я из Нарнии"))
    assert "citizenship_iso3" not in state.qualification["kg_entry"]


# --- B. Правила не произносятся без разрешения ----------------------------------

def test_rule_is_not_spoken_while_speech_is_disabled(monkeypatch, state):
    """Флаг речи выключен ⇒ даже верный вывод движка не доходит до клиента."""
    _say(monkeypatch, False)
    _patch(monkeypatch,
           _tool("kg_entry_facts", {"citizenship": "Россия"}),
           _text("Вы можете находиться 90 дней без визы в течение 180 дней."))
    reply = asyncio.run(runner.run_kg_entry_turn(state, "я из России, нужна ли виза"))
    assert "90" not in reply, f"неподтверждённое правило дошло до клиента: {reply!r}"
    assert "специалист" in reply.lower()


def test_tool_result_tells_the_model_not_to_speak(monkeypatch, state):
    """Модель должна получить явный запрет, а не догадываться по молчанию."""
    _say(monkeypatch, False)
    fake = _patch(monkeypatch,
                  _tool("kg_entry_facts", {"citizenship": "Россия"}),
                  _text("Хорошо, уточню."))
    asyncio.run(runner.run_kg_entry_turn(state, "я из России"))
    sent = fake.messages.create.call_args_list[-1].kwargs["messages"]
    dumped = str(sent)
    assert "НЕЛЬЗЯ" in dumped or "нельзя" in dumped


def test_prices_never_reach_the_client(monkeypatch, state):
    _say(monkeypatch, True)
    _patch(monkeypatch, _text("Консульский сбор $50, наши услуги $50."))
    reply = asyncio.run(runner.run_kg_entry_turn(state, "сколько стоит"))
    assert "$" not in reply and "50" not in reply


def test_documents_are_not_requested_before_consent(monkeypatch, state):
    _say(monkeypatch, True)
    _patch(monkeypatch, _text("Пришлите скан паспорта."))
    reply = asyncio.run(runner.run_kg_entry_turn(state, "что нужно"))
    assert "скан" not in reply.lower()


# --- C. Передача специалисту ----------------------------------------------------

def test_handoff_sets_the_stage_and_reason(monkeypatch, state):
    _say(monkeypatch, False)
    _patch(monkeypatch,
           _tool("kg_entry_handoff", {"reason": "стоп-фактор: цель работа",
                                      "flags": ["Срочно", "B2B"]}),
           _text("Передала специалисту, он свяжется в рабочее время."))
    asyncio.run(runner.run_kg_entry_turn(state, "нашёл работу на фабрике"))
    kg = state.qualification["kg_entry"]
    assert state.stage == "manager"
    assert "работа" in kg["handoff_reason"]
    assert kg["flags"] == ["Срочно", "B2B"]


# --- D. Контекст в промпте компактный -------------------------------------------

def test_context_is_compact_and_has_no_raw_json(monkeypatch, state):
    """Тотальный дамп анкеты на шестидесяти слотах и дорог, и шумен."""
    state.qualification["kg_entry"] = {
        "citizenship": "India", "citizenship_iso3": "IND",
        "document_type": "ordinary", "purpose": "business_meeting",
        "location": "abroad", "entry_on": "2026-11-10", "exit_on": "2026-11-20",
        "applicants_count": 1, "inviter": "ОсОО Пример",
        "_verdict_line": "виза · общий порядок",
    }
    _say(monkeypatch, False)
    fake = _patch(monkeypatch, _text("Хорошо."))
    asyncio.run(runner.run_kg_entry_turn(state, "привет"))
    sent = fake.messages.create.call_args_list[-1].kwargs["messages"]
    context = [m for m in sent if "Уже известно" in str(m.get("content"))]
    assert context, "компактный контекст не попал в промпт"
    body = str(context[0]["content"])
    assert "{" not in body and "}" not in body, "в промпт уехал сырой JSON"
    assert body.count(";") <= 10
    assert "citizenship_iso3" not in body, "в промпт уехало служебное поле"


# --- E. Прежние воронки не изменились -------------------------------------------

def test_other_funnels_keep_the_default_context_and_no_profile():
    assert runner.VISA_SPEC.qual_context is None
    assert runner.VISA_SPEC.validator_profile is None
    assert runner.TOURS_SPEC.qual_context is None
    assert runner.TICKETS_SPEC.validator_profile is None
