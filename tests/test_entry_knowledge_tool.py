"""ГЕЙТ: инструмент поиска по базе знаний в руках бота.

Написан ДО реализации.

Главное, что здесь закреплено, — **поведение при пустом оверлее**. Инструмент
выкатывается раньше, чем человек подпишет хоть один кусок, и это сделано нарочно: так
можно доказать fail-closed до того, как у бота появится право говорить. Пока ничего не
одобрено, поиск не находит ничего, и бот передаёт человеку. Решение владельца 22.10:
отвечать из общих знаний модели запрещено.

Второе: **в модель не уходит ни провенанс, ни неодобренный текст.** Клиент видит
человеческий язык без ссылок на раздел и страницу (тоже решение владельца), а значит
модели эти данные и не нужны — что в контекст попало, то рано или поздно будет
произнесено. Основание уходит менеджеру в карточку и в снимок заявки.

Третье: **бюджет хода.** Витков LLM до шести, а ограничения на число вызовов
инструментов за ход нет вовсе, поэтому счётчик обязателен — иначе один ход может
обойтись в десяток поисков и утроить цену.
"""
import asyncio

import pytest

import app.config
from app.core.state import DialogState

SANDBOX = "getvisa_tg"
QUESTION = "какие документы нужны для деловой визы"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    from app.core import flags
    index = pytest.importorskip("app.knowledge.answers_index")
    approval = pytest.importorskip("app.knowledge.answers_approval")
    flags.reset()
    index.reset()
    approval.reset()
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", True,
                        raising=False)
    yield
    flags.reset()
    index.reset()
    approval.reset()


def _state():
    state = DialogState(user_id=f"{SANDBOX}:1", funnel="visa", bot_id=SANDBOX)
    state.qualification["entry_mode"] = "kg_entry"
    state.qualification["kg_entry"] = {}
    return state


def _call(state, question=QUESTION):
    from app.agent.runner import _kg_entry_exec_tool
    return asyncio.run(_kg_entry_exec_tool("kg_entry_knowledge",
                                           {"question": question}, state))


def _approve_everything(monkeypatch, state=None):
    """Подписать всё, что отвечаемо — чтобы проверить путь «нашлось»."""
    from app.knowledge import answers_approval, answers_index
    index = answers_index.load()
    if index is None:
        pytest.skip("база знаний недоступна в этом дереве")
    rows = {p["piece_id"]: p["text_sha256"]
            for p in index._pieces.values() if p["approvable"]}   # noqa: SLF001
    monkeypatch.setattr(answers_approval, "load",
                        lambda: answers_approval.Approvals(
                            corpus_hash=index.corpus_hash,
                            source_hash=index.source_hash, by_piece=rows))
    return index


# --- A. Флаг выключен — ничего не изменилось ------------------------------------

def test_the_flag_is_off_by_default():
    assert app.config.settings.kg_entry_knowledge_enabled is False, (
        "поиск по базе включён по умолчанию — это меняет поведение для клиента "
        "сразу после деплоя")


def test_with_the_flag_off_the_tool_refuses(monkeypatch):
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", False,
                        raising=False)
    answer = _call(_state())
    assert "передай" in answer.lower() or "специалист" in answer.lower()


# --- B. Оверлея нет — бот передаёт человеку ------------------------------------

def test_without_an_approved_overlay_the_bot_hands_over(monkeypatch):
    """Удаление подписи — штатный откат: бот возвращается к «уточнит специалист»."""
    from app.knowledge import answers_approval
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", True,
                        raising=False)
    monkeypatch.setattr(answers_approval, "load", lambda: None)
    answer = _call(_state())
    assert "специалист" in answer.lower(), answer
    assert "докуме" not in answer.lower(), "в модель уехал текст базы без одобрения"


def test_nothing_from_the_base_leaks_without_approval(monkeypatch):
    from app.knowledge import answers_approval
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", True,
                        raising=False)
    monkeypatch.setattr(answers_approval, "load", lambda: None)
    state = _state()
    _call(state)
    recorded = state.qualification["kg_entry"].get("_knowledge") or []
    assert recorded == [], f"неодобренные куски записаны в анкету: {recorded}"


def test_with_the_signed_overlay_the_bot_answers(monkeypatch):
    """Обратная сторона: подпись есть — бот отвечает по базе, а не отписывается."""
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", True,
                        raising=False)
    state = _state()
    answer = _call(state, "какие документы нужны для деловой визы")
    assert "Из базы знаний" in answer, answer
    assert state.qualification["kg_entry"]["_knowledge"],         "использованные куски не записаны для карточки менеджера"


# --- C. Нашлось — что именно уходит модели -------------------------------------

def test_an_approved_answer_reaches_the_model(monkeypatch):
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", True,
                        raising=False)
    _approve_everything(monkeypatch)
    state = _state()
    answer = _call(state)
    assert len(answer) > 80, f"ответ подозрительно пуст: {answer!r}"
    assert state.qualification["kg_entry"].get("_knowledge"), \
        "использованные куски не записаны для карточки менеджера"


def test_no_provenance_reaches_the_model(monkeypatch):
    """Клиенту — человеческий язык без ссылок, значит и модели провенанс не нужен."""
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", True,
                        raising=False)
    _approve_everything(monkeypatch)
    answer = _call(_state())
    # «раздел» из списка убран намеренно: это слово самой базы («см. раздел 11.4»),
    # а не наш провенанс. Запрет ссылаться на разделы живёт в промпте.
    for forbidden in ("KG.KB.", "KG.AN.", "стр.", "sha256", "text_sha256"):
        assert forbidden not in answer, f"в модель уехал провенанс: {forbidden!r}"


def test_no_amount_ever_reaches_the_model(monkeypatch):
    """Решение владельца: бот сумм не называет. Значит их нет и в контексте модели."""
    import re
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", True,
                        raising=False)
    _approve_everything(monkeypatch)
    for question in ("сколько стоит виза", "консульский сбор", "резидент-карта",
                     "единое разрешение", "какие документы нужны"):
        answer = _call(_state(), question)
        found = re.findall(r"[$€]\s?\d|\d[\d\s.,]*\s?(?:\$|€|сом|usd|долл)", answer)
        assert not found, f"{question!r}: в модель уехала сумма {found[:3]}"


def test_the_payload_stays_inside_the_budget(monkeypatch):
    """Прибавка к ходу ограничена: витков до шести, лимита на вызовы инструментов нет."""
    from app.agent import runner
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", True,
                        raising=False)
    _approve_everything(monkeypatch)
    answer = _call(_state(), "виза документы регистрация срок работа отказ продление")
    assert len(answer) <= runner.KB_MAX_CHARS + 400, (
        f"ответ инструмента {len(answer)} символов, бюджет "
        f"{runner.KB_MAX_CHARS}")


def test_the_search_budget_per_turn_is_capped(monkeypatch):
    from app.agent import runner
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", True,
                        raising=False)
    _approve_everything(monkeypatch)
    state = _state()
    for _ in range(runner.KB_MAX_CALLS):
        _call(state)
    refused = _call(state)
    assert "передай" in refused.lower() or "больше не ищи" in refused.lower(), refused


# --- D. Ловушка образа ---------------------------------------------------------

def test_the_overlay_is_shipped_once_it_exists():
    """Если оверлей появился — он обязан попасть в образ.

    Прецедент: `fc12075` чинил ровно это для бандла правил. Dockerfile перечисляет
    файлы знаний по одному, и забытая строка даёт на проде молчаливую пустоту при
    зелёном /health.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    overlay = root / "knowledge" / "kg_entry" / "answers-approved-v1.1.yaml"
    if not overlay.exists():
        pytest.skip("оверлея одобрения ещё нет — проверять нечего")
    dockerfile = (root / "Dockerfile").read_text("utf-8")
    assert "answers-approved-v1.1.yaml" in dockerfile, (
        "оверлей одобрения не копируется в образ — на проде бот не произнесёт "
        "ни одного факта из базы при зелёном /health")


def test_the_search_budget_resets_every_turn(monkeypatch):
    """Бюджет поиска — на ХОД, а не на диалог.

    Найдено независимым ревью 22.10: счётчик лежит в анкете, которая переживает ход,
    и без обнуления бот после двух вопросов навсегда отвечал «бюджет исчерпан». То
    есть ответы по базе отмирали на третьей реплике клиента.
    """
    from app.agent import runner
    monkeypatch.setattr(app.config.settings, "kg_entry_knowledge_enabled", True,
                        raising=False)
    state = _state()
    for _ in range(runner.KB_MAX_CALLS):
        _call(state)
    assert state.qualification["kg_entry"].get("_kb_calls") == runner.KB_MAX_CALLS

    # Модель здесь не нужна: проверяем ровно обнуление на входе в ход, а не диалог.
    async def no_llm(_state, _text, _spec):
        return "ок"

    monkeypatch.setattr(runner, "run_turn", no_llm)
    asyncio.run(runner.run_kg_entry_turn(state, "а ещё вопрос"))
    assert not state.qualification["kg_entry"].get("_kb_calls"), \
        "счётчик поиска не обнулён в начале хода"
    answer = _call(state)
    assert "бюджет" not in answer.lower(), \
        f"после нового хода бот всё ещё считает бюджет исчерпанным: {answer!r}"
