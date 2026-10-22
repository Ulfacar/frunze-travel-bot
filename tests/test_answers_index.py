"""ГЕЙТ: индекс базы знаний, который спрашивает бот.

Главное требование — **fail-closed**. Пока человек не подписал куски, индекс не отдаёт
ничего, и бот передаёт человеку. Это решение владельца 22.10: отвечать из общих знаний
модели запрещено, «не нашёл» означает «передай специалисту».

Второе требование — **не мешать проверенному пути**. Поиск по разделам
(`app/knowledge/retrieval.py`, ~50 тестов) используется как первый этап и не меняется:
его выдача по-прежнему помечена `may_quote=False`.

Замеры, из-за которых индекс устроен именно так, закреплены в
`scripts/measure_knowledge_recall.py` и в наборе `scenarios/kg_knowledge_queries.json`:
прямой поиск по кускам давал по русским вопросам 70% попаданий в top-3, двухэтапный —
100%; по английским 20% без словаря и 80% со словарём.
"""
import pytest


@pytest.fixture(autouse=True)
def clean_caches():
    index = pytest.importorskip("app.knowledge.answers_index")
    approval = pytest.importorskip("app.knowledge.answers_approval")
    index.reset()
    approval.reset()
    yield
    index.reset()
    approval.reset()


@pytest.fixture
def loaded():
    from app.knowledge import answers_index
    index = answers_index.load()
    if index is None:
        pytest.skip("база знаний недоступна в этом дереве")
    return index


# --- A. Fail-closed: без подписи человека бот ничего не произносит --------------

def test_without_an_overlay_nothing_is_returned(loaded):
    """Оверлея нет — выдача пуста. Это штатное состояние до приёмки."""
    from app.knowledge import answers_approval
    assert answers_approval.load() is None, (
        "в дереве появился оверлей одобрения — перепишите тест осознанно, "
        "он охраняет именно состояние «ничего не одобрено»")
    assert loaded.search("какие документы нужны для деловой визы") == []
    assert loaded.search("what documents are needed for a business visa") == []


def test_approval_requires_both_hashes(loaded, monkeypatch):
    """Пустая привязка к корпусу или к PDF делает оверлей недоверенным целиком."""
    from app.knowledge import answers_approval
    piece = next(iter(loaded._pieces.values()))          # noqa: SLF001
    for corpus_hash, source_hash in (("", "x"), ("x", ""), ("", "")):
        monkeypatch.setattr(answers_approval, "load", lambda: answers_approval.Approvals(
            corpus_hash=corpus_hash, source_hash=source_hash,
            by_piece={piece["piece_id"]: piece["text_sha256"]}))
        assert not answers_approval.approved(
            piece, corpus_hash=loaded.corpus_hash, source_hash=loaded.source_hash)


def test_editing_the_text_kills_the_approval(loaded, monkeypatch):
    from app.knowledge import answers_approval
    piece = next(iter(loaded._pieces.values()))          # noqa: SLF001
    monkeypatch.setattr(answers_approval, "load", lambda: answers_approval.Approvals(
        corpus_hash=loaded.corpus_hash, source_hash=loaded.source_hash,
        by_piece={piece["piece_id"]: piece["text_sha256"]}))
    assert answers_approval.approved(piece, corpus_hash=loaded.corpus_hash,
                                     source_hash=loaded.source_hash)
    tampered = dict(piece, text_sha256="0" * 64)
    assert not answers_approval.approved(tampered, corpus_hash=loaded.corpus_hash,
                                         source_hash=loaded.source_hash)


def test_a_decision_piece_can_never_be_approved(loaded, monkeypatch):
    """`[РЕШЕНИЕ]` — «клиенту не озвучивать». Одобрение этого не снимает."""
    from app.knowledge import answers_approval
    decision = [p for p in loaded._pieces.values()       # noqa: SLF001
                if "РЕШЕНИЕ" in p["labels"]]
    assert decision, "в корпусе нет кусков с меткой РЕШЕНИЕ — проверьте источник"
    monkeypatch.setattr(answers_approval, "load", lambda: answers_approval.Approvals(
        corpus_hash=loaded.corpus_hash, source_hash=loaded.source_hash,
        by_piece={p["piece_id"]: p["text_sha256"] for p in decision}))
    for piece in decision:
        assert not answers_approval.approved(piece, corpus_hash=loaded.corpus_hash,
                                             source_hash=loaded.source_hash)


# --- B. Ранжирование и выдача --------------------------------------------------

def test_decision_pieces_are_never_in_the_ranking(loaded):
    """Даже при approved_only=False кусок с РЕШЕНИЕМ в выдачу не попадает."""
    for query in ("отказ", "виза", "регистрация", "работа", "документы"):
        for piece in loaded.search(query, limit=10, approved_only=False):
            assert "РЕШЕНИЕ" not in piece["labels"], piece["piece_id"]


def test_one_piece_per_section(loaded):
    """Иначе выдача забивается соседними строками одной таблицы, а бюджет уходит."""
    for query in ("какие документы нужны", "регистрация", "продление"):
        found = loaded.search(query, limit=4, approved_only=False)
        sections = [p["section"] for p in found]
        assert len(sections) == len(set(sections)), f"{query}: повтор раздела {sections}"


def test_limit_is_respected(loaded):
    for limit in (1, 2, 3, 4):
        assert len(loaded.search("виза документы регистрация срок",
                                 limit=limit, approved_only=False)) <= limit


@pytest.mark.parametrize("query", ["", "   ", "x" * 201, None, 123])
def test_a_bad_query_returns_nothing(loaded, query):
    assert loaded.search(query, approved_only=False) == []


@pytest.mark.parametrize("limit", [0, 11, True, 2.5, "3"])
def test_a_bad_limit_returns_nothing(loaded, limit):
    assert loaded.search("виза", limit=limit, approved_only=False) == []


def test_search_is_deterministic(loaded):
    first = loaded.search("какие документы нужны для деловой визы", approved_only=False)
    second = loaded.search("какие документы нужны для деловой визы", approved_only=False)
    assert [p["piece_id"] for p in first] == [p["piece_id"] for p in second]


# --- C. Словарь EN→RU ----------------------------------------------------------

def test_the_lexicon_keeps_the_original_words():
    """Английский термин может встречаться и в самой базе — выбрасывать его нельзя."""
    from app.knowledge.answers_lexicon import expand
    assert "e-visa" in expand("e-visa").lower()
    assert "регист" in expand("registration")


def test_the_lexicon_does_not_expand_the_word_visa():
    """«visa» почти не несёт информации: вся база про визы.

    Разворот в шесть падежных форм подсвечивал любой раздел, где слово встречается
    часто, и ронял вопросы про документы — замер это показал.
    """
    from app.knowledge.answers_lexicon import EN_TO_RU
    assert EN_TO_RU["visa"] == ()
    assert EN_TO_RU["visas"] == ()


def test_english_questions_find_their_section(loaded):
    """Основная аудитория въездной ветки пишет по-английски."""
    expected = {
        "why do they refuse a visa": "15.0",
        "what do I need to work in Kyrgyzstan": "11.1",
        "how are days of stay counted": "2.9",
        "who can be an inviting party": "9.3",
    }
    for query, section in expected.items():
        found = loaded.search(query, limit=3, approved_only=False)
        assert section in [p["section"] for p in found], (
            f"{query!r}: ожидался раздел {section}, получено "
            f"{[p['section'] for p in found]}")


# --- D. Проверенный путь ревью не затронут -------------------------------------

def test_the_review_path_still_refuses_to_grant_quoting():
    from app.knowledge.retrieval import load_review_index
    index = load_review_index()
    report = index.search("регистрация", limit=2)
    assert report["may_quote"] is False
    assert report["mode"] == "review_only"
    for item in report["results"]:
        assert item["fragment"]["may_quote"] is False
