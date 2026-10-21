"""ГЕЙТ: при выключенном флаге въездная ветка не существует.

Написан ДО реализации и исполнителем НЕ редактируется.

Это главный тест всей задачи. Въездные визы встраиваются в ЖИВУЮ визовую воронку на
боевом номере GetVisa, где сейчас работают Медина и Элиза. Если флаг выключен, поведение
обязано быть прежним дословно — иначе это не откат, а вторая задача.

Проверяется и обратная сторона: при включённом флаге выездной клиент по-прежнему уходит
прежним путём. Новая ветка забирает только то, что распознано как въезд.

Отдельно закреплена находка проектирования 21.10: детерминированный прайс выездных виз
(`visa_price_reply`) стреляет в оркестраторе ВЫШЕ воронки. Без гварда иностранец,
спросивший «how much is a visa to Kyrgyzstan», получил бы прайс по Шенгену и США —
нарушение решения владельца «бот цен не называет» на первом же сообщении.
"""
import asyncio

import pytest

import app.config
from app.channels.base import Message
from app.core.state import DialogState

FLAG = "kg_entry_enabled"
ENTRY_TEXT = "I need a visa to Kyrgyzstan"
OUTBOUND_TEXT = "нужна виза в США"


def _state(**kw):
    return DialogState(user_id=kw.pop("user_id", "getvisa:996700000001"),
                       funnel="visa", **kw)


def _msg(text, user_id="getvisa:996700000001"):
    return Message(channel="whatsapp", user_id=user_id, chat_id=user_id, text=text)


def _off(monkeypatch):
    monkeypatch.setattr(app.config.settings, FLAG, False, raising=False)


def _on(monkeypatch):
    monkeypatch.setattr(app.config.settings, FLAG, True, raising=False)


def _no_llm(monkeypatch):
    """Офлайн-путь воронки: так тест не трогает сеть и виден детерминированный ответ."""
    monkeypatch.setattr(app.config.settings, "openrouter_api_key", "", raising=False)


# --- A. Флаг по умолчанию выключен ---------------------------------------------

def test_flag_defaults_to_off():
    assert getattr(app.config.settings, FLAG) is False, (
        "флаг въездной ветки включён по умолчанию — это меняет поведение для клиента "
        "сразу после деплоя")


def test_flag_is_registered_in_the_panel():
    """Тумблер должен быть в «Статусе системы», иначе выключить его можно только деплоем."""
    from app.admin.router import FEATURE_FLAGS
    assert FLAG in FEATURE_FLAGS


# --- B. Выключенный флаг = прежнее поведение -----------------------------------

def test_entry_text_goes_the_old_way_when_flag_is_off(monkeypatch):
    _off(monkeypatch); _no_llm(monkeypatch)
    from app.funnels.visa import VisaFunnel
    state = _state()
    reply = asyncio.run(VisaFunnel().handle(_msg(ENTRY_TEXT), state))
    assert reply is not None
    assert state.qualification.get("entry_mode") is None, \
        "ветка пометила диалог въездным при выключенном флаге"


def test_old_and_new_replies_match_exactly_when_flag_is_off(monkeypatch):
    """Ответ при флаге OFF должен совпадать с ответом на нейтральную реплику."""
    _off(monkeypatch); _no_llm(monkeypatch)
    from app.funnels.visa import VisaFunnel
    a = asyncio.run(VisaFunnel().handle(_msg(ENTRY_TEXT), _state()))
    b = asyncio.run(VisaFunnel().handle(_msg("здравствуйте"), _state()))
    assert a == b, "въездная реплика получила особый ответ при выключенном флаге"


# --- C. Включённый флаг не задевает выездных -----------------------------------

def test_outbound_client_is_untouched_when_flag_is_on(monkeypatch):
    _on(monkeypatch); _no_llm(monkeypatch)
    from app.funnels.visa import VisaFunnel
    state = _state()
    asyncio.run(VisaFunnel().handle(_msg(OUTBOUND_TEXT), state))
    assert state.qualification.get("entry_mode") is None, \
        "выездной клиент уехал во въездную ветку"


def test_ambiguous_client_is_untouched_when_flag_is_on(monkeypatch):
    """Одинокое «виза» — не повод забирать диалог в новую базу знаний."""
    _on(monkeypatch); _no_llm(monkeypatch)
    from app.funnels.visa import VisaFunnel
    state = _state()
    asyncio.run(VisaFunnel().handle(_msg("виза"), state))
    assert state.qualification.get("entry_mode") is None


# --- D. Включённый флаг: въездной распознан ------------------------------------

def test_entry_client_is_marked_and_handed_over(monkeypatch):
    _on(monkeypatch); _no_llm(monkeypatch)
    from app.funnels.visa import VisaFunnel
    state = _state()
    reply = asyncio.run(VisaFunnel().handle(_msg(ENTRY_TEXT), state))
    assert state.qualification.get("entry_mode") == "kg_entry"
    assert reply, "въездному клиенту не ответили вовсе"
    # Пока речь не включена, исход один: человек.
    assert state.stage == "manager"


def test_mode_is_sticky_across_turns(monkeypatch):
    """Второй ход про посольство не должен увести клиента в выездную базу знаний."""
    _on(monkeypatch); _no_llm(monkeypatch)
    from app.funnels.visa import VisaFunnel
    state = _state()
    asyncio.run(VisaFunnel().handle(_msg(ENTRY_TEXT), state))
    asyncio.run(VisaFunnel().handle(_msg("а в посольстве спрашивают?"), state))
    assert state.qualification.get("entry_mode") == "kg_entry"


def test_no_prices_in_the_entry_reply(monkeypatch):
    """Решение владельца: бот цен не называет вообще."""
    _on(monkeypatch); _no_llm(monkeypatch)
    from app.funnels.visa import VisaFunnel
    state = _state()
    reply = asyncio.run(VisaFunnel().handle(_msg(ENTRY_TEXT), state)) or ""
    assert "$" not in reply and "сом" not in reply.lower()
    assert not any(ch.isdigit() for ch in reply), f"в ответе появились числа: {reply!r}"


# --- E. Гвард на выездной прайс (находка проектирования 21.10) ------------------

def test_outbound_price_reply_is_guarded_for_entry_dialogs():
    """Иностранец про КР не должен получить прайс по Шенгену из слоя выше воронки."""
    from pathlib import Path
    import app.core.orchestrator as orch
    source = Path(orch.__file__).read_text("utf-8")
    block = source[source.index("def _maybe_faq_reply"):]
    block = block[:block.index("visa_price_reply") + 200]
    assert "entry_mode" in block, (
        "в _maybe_faq_reply нет гварда по entry_mode: въездной клиент получит "
        "детерминированный прайс выездных виз ещё до воронки")
