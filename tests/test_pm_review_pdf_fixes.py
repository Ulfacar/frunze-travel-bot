"""Проверка PDF-потока (PM-ревью 30.10.2026): три расхождения с ТЗ Гриши v1.1.

Все три найдены прямыми вызовами функций на коде `74ba9b5`, без модели:

1. **Утечка `[РЕШЕНИЕ]` через разорванную метку** (ТЗ, с. 2: «клиенту не озвучивать»).
   В Markdown-источнике абзац 6.3 «Чей e-mail указывать…» заканчивается, а метка
   `**[РЕШЕНИЕ]**.` стоит ОТДЕЛЬНЫМ абзацем на следующей строке. Нарезка делала из неё
   самостоятельный кусок, и содержательный кусок `KG.KB.6.3#014` уходил в одобренные как
   чистый. Осиротевшая метка относится к предыдущему куску.

2. **Выездной ремень валидатора срабатывает на въездном профиле** (ТЗ 1.1: Единое
   разрешение — «оформляем сами, полный цикл»; Б.7: «для работы нужно Единое
   разрешение»). `validate_reply(..., funnel="visa", profile="kg_entry")` сначала
   прогоняет общий визовый ремень `_AFFIRM_WORKVISA` и подменяет верную фразу про
   рабочую визу на «Рабочими визами мы не занимаемся… (например, США: B1/B2, F1, M1)».

3. **Выездной FAQ перехватывает ход въездного клиента** (ТЗ 5.3/А.4: список документов
   TS; решение владельца: бот цен не называет). В `_maybe_faq_reply` гвард `_entry_talk`
   стоит только над прайсом, а `match_faq` по выездным записям («какие документы» →
   «страховка, справка с работы»; «сколько стоит» → «назову официальный прайс») идёт
   без него.

Пункты 2 и 3 — поведение бота для клиента, поэтому за флагом
`kg_entry_outbound_isolation_enabled` с дефолтом OFF. Пункт 1 — данные нарезки: он не
меняет ни корпус, ни хеши подписей, а только лишает один кусок права на одобрение.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.config
from app.channels.base import Message
from app.core.state import DialogState

FLAG = "kg_entry_outbound_isolation_enabled"


# --- 1. Осиротевшая метка ---------------------------------------------------------

def _fragment(raw: str) -> dict:
    return {"id": "KG.KB.T.1", "block": 6, "section": "6.3", "title": "Тест",
            "raw_text": raw, "context_text": "", "pdf_pages_from_markers": [41]}


def test_orphan_decision_label_marks_previous_piece():
    from app.knowledge.answerable import pieces
    raw = ("**Чей e-mail указывать:** рекомендуем контролируемый компанией ящик\n"
           "\n"
           "**[РЕШЕНИЕ]**. Проверить, принимает ли портал адреса с «+» **[ПРОВЕРИТЬ]**.\n"
           "\n"
           "**Кто отвечает за контроль:** ответственный менеджер сделки.\n")
    out = pieces(_fragment(raw))
    by_text = {p["text"][:12]: p for p in out}
    email = by_text["**Чей e-mail"]
    assert "РЕШЕНИЕ" in email["labels"], "метка из следующего абзаца не перенесена"
    assert email["answerable"] is False and email["approvable"] is False
    # Следующий содержательный абзац метку НЕ наследует.
    control = by_text["**Кто отвеча"]
    assert control["labels"] == [] and control["answerable"] is True


def test_orphan_label_does_not_change_piece_texts_or_hashes():
    """Правка касается только меток: тексты и хеши кусков те же, подписи живы."""
    from app.knowledge.answerable import pieces
    raw = ("Абзац один.\n\n**[ПРАКТИКА]**: правило компании.\n\nАбзац два.\n")
    out = pieces(_fragment(raw))
    assert [p["text"] for p in out] == ["Абзац один.", "**[ПРАКТИКА]**: правило компании.",
                                        "Абзац два."]
    # «[ПРАКТИКА]: …» — это самостоятельное предложение с текстом, а не хвост
    # предыдущего: первому абзацу метка не достаётся.
    assert out[0]["labels"] == []


def test_real_corpus_piece_6_3_014_is_no_longer_approvable():
    """Живой кусок из базы, из-за которого всё и началось."""
    pytest.importorskip("app.knowledge.answers_index")
    from app.knowledge import answers_index
    index = answers_index.load()
    if index is None:
        pytest.skip("корпус знаний недоступен")
    piece = index._pieces.get("KG.KB.6.3#014")          # noqa: SLF001
    if piece is None:
        pytest.skip("кусок KG.KB.6.3#014 отсутствует — корпус другой версии")
    assert "РЕШЕНИЕ" in piece["labels"]
    assert piece["approvable"] is False


# --- 2. Выездной ремень на въездном профиле -------------------------------------

REPLY = ("Работать по туристической визе нельзя. Для работы нужна рабочая виза, "
         "то есть Единое разрешение, его оформляет работодатель.")
ALLOWED = frozenset({"regime", "stay_limit", "registration", "unified_permit"})


def test_flag_defaults_to_off():
    assert getattr(app.config.settings, FLAG) is False


def test_flag_is_registered_in_the_panel():
    from app.admin.router import FEATURE_FLAGS
    assert FLAG in FEATURE_FLAGS


def test_outbound_workvisa_belt_is_skipped_for_entry_profile_when_isolated():
    from app.agent.validator import validate_reply
    clean, violations = validate_reply(REPLY, "visa", profile="kg_entry",
                                       allowed_claims=ALLOWED, outbound_isolated=True)
    assert "не занимаемся" not in clean and "B1/B2" not in clean
    assert "work_visa_offer_blocked" not in violations
    assert "Единое разрешение" in clean


def test_outbound_workvisa_belt_still_fires_without_isolation():
    """Флаг OFF — поведение прежнее дословно (это и есть дефект, зафиксированный ревью)."""
    from app.agent.validator import validate_reply
    clean, violations = validate_reply(REPLY, "visa", profile="kg_entry",
                                       allowed_claims=ALLOWED)
    assert "work_visa_offer_blocked" in violations


def test_outbound_funnel_untouched_by_isolation_argument():
    """Выездная воронка (profile=None) ремень сохраняет при любом значении аргумента."""
    from app.agent.validator import validate_reply
    text = "Оформим вам рабочую визу в США без проблем."
    for isolated in (False, True):
        clean, violations = validate_reply(text, "visa", outbound_isolated=isolated)
        assert "work_visa_offer_blocked" in violations


# --- 3. Выездной FAQ на въездном клиенте ----------------------------------------

def _orchestrator(monkeypatch, *, entry_mode: bool):
    from app.core import faq, orchestrator as orch
    # Стартовые FAQ-записи (те же, что `seed_defaults` кладёт на прод) — в память,
    # чтобы тест не зависел от базы стенда.
    store_faq = faq.MemoryFaqStore()
    monkeypatch.setattr(faq, "get_faq_store", lambda: store_faq)
    asyncio.run(faq.seed_defaults())
    state = DialogState(user_id="getvisa:996700000009", funnel="visa")
    if entry_mode:
        state.qualification = {"entry_mode": "kg_entry", "kg_entry": {"citizenship": "Индия"}}
    store = SimpleNamespace(load=AsyncMock(return_value=state), save=AsyncMock())
    adapter = SimpleNamespace(send=AsyncMock(return_value="X"), channel="whatsapp")
    o = orch.Orchestrator(channel=adapter)
    o._sync_card = AsyncMock(); o._maybe_instant_handoff = AsyncMock()
    o._reply = AsyncMock(return_value=True)
    return o, state, store


def _ask(o, state, store, text):
    msg = Message(channel="whatsapp", user_id=state.user_id, chat_id=state.user_id, text=text)
    return asyncio.run(o._maybe_faq_reply(msg, state, store))


@pytest.mark.parametrize("question", ["Какие документы нужны для визы?",
                                      "Сколько стоит виза в Кыргызстан?",
                                      "Какие визы вы делаете?"])
def test_outbound_faq_does_not_answer_entry_client_when_isolated(monkeypatch, question):
    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, FLAG, True, raising=False)
    o, state, store = _orchestrator(monkeypatch, entry_mode=True)
    assert _ask(o, state, store, question) is False
    assert state.history == []


def test_outbound_faq_still_answers_entry_client_when_flag_off(monkeypatch):
    """Дефект воспроизводим при флаге OFF — это прежнее поведение, оно не меняется."""
    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, FLAG, False, raising=False)
    o, state, store = _orchestrator(monkeypatch, entry_mode=True)
    assert _ask(o, state, store, "Какие документы нужны для визы?") is True
    assert "справка с работы" in state.history[-1]["content"]


def test_outbound_faq_keeps_answering_outbound_client_when_isolated(monkeypatch):
    """Выездной клиент на том же номере получает FAQ как прежде."""
    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, FLAG, True, raising=False)
    o, state, store = _orchestrator(monkeypatch, entry_mode=False)
    assert _ask(o, state, store, "Какие документы нужны для визы в США?") is True
