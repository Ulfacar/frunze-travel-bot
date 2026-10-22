"""ГЕЙТ: что именно бот передаёт в нашу CRM при передаче человеку.

Написан ДО реализации.

Зачем. Сегодня бот отдаёт менеджеру ТЕКСТ карточки Б.4, а менеджер перепечатывает её
в CRM руками. Текст нельзя ни разобрать машинно, ни проверить потом: по нему не
восстановить, что именно бот сказал клиенту и на каком основании. А предмет здесь —
нормы миграционного права, и вопрос «почему бот так сказал» рано или поздно задаст либо
Гриша, либо проверяющий.

Поэтому при передаче рядом с текстом сохраняется машинный снимок заявки. Он же —
контракт данных для любого будущего пути в CRM: экран в панели, кнопка «принять»,
выгрузка. Снимок ничего в типизированной CRM не создаёт: durable-запись там по-прежнему
заводит только named-администратор, см. docs/bot-to-crm-handoff.md.

Главное требование к снимку: он описывает ПРОШЛОЕ. Если потом правят данные знаний или
флаги, снимок обязан остаться тем, чем был, иначе разбор инцидента опирается на
сегодняшнее состояние вместо вчерашнего.
"""
import asyncio

import pytest

import app.config
from app.core.state import DialogState


@pytest.fixture(autouse=True)
def clean_flags():
    from app.core import flags
    flags.reset()
    yield
    flags.reset()


def _state(**kg):
    state = DialogState(user_id="sim:intake", funnel="visa", bot_id="sim")
    state.qualification["entry_mode"] = "kg_entry"
    state.qualification["kg_entry"] = dict(kg)
    return state


def _handoff(state, **args):
    from app.agent.runner import _kg_entry_exec_tool
    return asyncio.run(_kg_entry_exec_tool("kg_entry_handoff", args or {"reason": "готово"},
                                           state))


def test_handoff_leaves_a_machine_readable_snapshot(monkeypatch):
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    state = _state(citizenship="Узбекистан", citizenship_iso3="UZB",
                   purpose="work_hire", location="in_kg", document_type="ordinary")
    _handoff(state, reason="нужно Единое разрешение", flags=["Срочно"])

    intake = state.qualification["kg_entry"].get("intake")
    assert intake, "снимок заявки не сохранён — менеджер снова перепечатывает руками"
    assert intake["schema"] == "kg-entry-intake/1"
    assert intake["citizenship_iso3"] == "UZB"
    assert intake["handoff_reason"] == "нужно Единое разрешение"
    assert intake["flags"] == ["Срочно"]
    assert intake["at"], "не записано время передачи"


def test_the_snapshot_says_what_the_bot_was_allowed_to_state(monkeypatch):
    """Ключевое для разбора: что бот сказал клиенту, а что оставил специалисту."""
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    state = _state(citizenship="Таджикистан", citizenship_iso3="TJK", purpose="tourism")
    _handoff(state)
    intake = state.qualification["kg_entry"]["intake"]
    assert "regime" not in intake["said_to_client"], \
        "метка [ПРОВЕРИТЬ] у Таджикистана, режим произносить нельзя"
    assert any("verify" in reason for reason in intake["withheld"]), \
        "причина умолчания не сохранена"


def test_the_snapshot_carries_the_basis_with_pages(monkeypatch):
    """Б.2 п.4: каждый вывод с основанием. В снимке — единицы, разделы и страницы ТЗ."""
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    state = _state(citizenship="США", citizenship_iso3="USA", purpose="tourism")
    _handoff(state)
    basis = state.qualification["kg_entry"]["intake"]["basis"]
    assert basis, "основание не сохранено"
    for row in basis:
        assert row["unit_id"] and row["page"] and row["source_ref"]
        assert "confirmed" in row and "label" in row


def test_the_snapshot_pins_the_knowledge_it_relied_on(monkeypatch):
    """Снимок описывает прошлое: по нему должно быть видно, какие данные тогда стояли."""
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    state = _state(citizenship="США", citizenship_iso3="USA", purpose="tourism")
    _handoff(state)
    intake = state.qualification["kg_entry"]["intake"]
    from app.knowledge.entry_bundle import loaded
    bundle = loaded()
    assert intake["bundle_hash"] == bundle.bundle_hash
    assert intake["source_hash"] == str((bundle.meta or {}).get("source_hash") or "")


def test_a_later_change_does_not_rewrite_an_old_snapshot(monkeypatch):
    """Снимок неизменяем: разбор инцидента не должен опираться на сегодняшние данные."""
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    state = _state(citizenship="США", citizenship_iso3="USA", purpose="tourism")
    _handoff(state)
    first = dict(state.qualification["kg_entry"]["intake"])

    # Речь отключили, факты уточнили — прежний снимок обязан остаться прежним.
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", False,
                        raising=False)
    state.qualification["kg_entry"]["purpose"] = "study"
    assert state.qualification["kg_entry"]["intake"] == first


def test_the_snapshot_never_contains_a_price(monkeypatch):
    """Решение владельца: сумм нет нигде, включая служебные данные."""
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    state = _state(citizenship="США", citizenship_iso3="USA", purpose="tourism")
    _handoff(state)
    import json
    raw = json.dumps(state.qualification["kg_entry"]["intake"], ensure_ascii=False)
    for token in ("$", "USD", "сом", "€"):
        assert token not in raw, f"в снимке заявки оказалась сумма: {token}"


def test_without_a_citizenship_the_snapshot_is_still_written(monkeypatch):
    """Передача бывает и до выяснения гражданства — снимок обязан это честно показать."""
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    state = _state()
    _handoff(state, reason="стоп-фактор")
    intake = state.qualification["kg_entry"]["intake"]
    assert intake["citizenship_iso3"] is None
    assert intake["verdict"] is None
    assert intake["said_to_client"] == []
    assert intake["handoff_reason"] == "стоп-фактор"


# --- Основание из базы знаний --------------------------------------------------

def test_the_snapshot_carries_the_knowledge_it_used(monkeypatch):
    """Менеджер обязан видеть, из каких кусков базы бот отвечал.

    Клиенту раздел и страница не показываются (решение владельца), поэтому
    единственное место, где это остаётся, — снимок заявки и карточка.
    """
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    state = _state(citizenship="Индия", citizenship_iso3="IND",
                   purpose="business_meeting")
    state.qualification["kg_entry"]["_knowledge"] = [
        {"piece_id": "KG.KB.5.2#007", "block": 5, "section": "5.2",
         "pdf_pages": [37], "labels": [], "text_sha256": "a" * 64},
    ]
    _handoff(state, reason="нужен список документов")
    intake = state.qualification["kg_entry"]["intake"]
    assert intake["knowledge_used"], "основание из базы не попало в снимок"
    row = intake["knowledge_used"][0]
    assert row["section"] == "5.2" and row["block"] == 5
    assert row["pdf_pages"] == [37]
    assert row["piece_id"] == "KG.KB.5.2#007"


def test_without_knowledge_the_field_is_empty(monkeypatch):
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    state = _state(citizenship="США", citizenship_iso3="USA", purpose="tourism")
    _handoff(state)
    assert state.qualification["kg_entry"]["intake"]["knowledge_used"] == []


def test_the_card_shows_the_knowledge_basis():
    from app.core import entry_card
    filled = {"name": "Rajesh", "phone": "996700111222", "channel": "whatsapp",
              "kg_entry": {"citizenship": "IND", "_knowledge": [
                  {"piece_id": "KG.KB.5.2#007", "block": 5, "section": "5.2",
                   "pdf_pages": [37], "labels": [], "text_sha256": "a" * 64}]}}
    card = entry_card.render(filled, None)
    assert "5.2" in card, "в карточке нет раздела базы, из которого отвечал бот"
    assert "37" in card, "в карточке нет страницы ТЗ"


def test_the_knowledge_basis_never_reaches_the_client_card_fields():
    """Хеш куска менеджеру не нужен — он служебный, в карточке его быть не должно."""
    from app.core import entry_card
    filled = {"name": "X", "phone": "996700000000",
              "kg_entry": {"_knowledge": [
                  {"piece_id": "KG.KB.5.2#007", "block": 5, "section": "5.2",
                   "pdf_pages": [37], "labels": [], "text_sha256": "b" * 64}]}}
    card = entry_card.render(filled, None)
    assert "b" * 64 not in card
