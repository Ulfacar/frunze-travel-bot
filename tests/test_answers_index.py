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

def test_without_an_overlay_nothing_is_returned(loaded, monkeypatch):
    """Оверлея нет — выдача пуста, бот передаёт человеку.

    23.10.2026 оверлей подписан («грузи»), поэтому проверка привязана не к состоянию
    файла, а к механизму: удаление оверлея обязано остаться штатным откатом. Состав
    подписанного проверяет `test_the_signed_overlay_is_pinned`.
    """
    from app.knowledge import answers_approval
    monkeypatch.setattr(answers_approval, "load", lambda: None)
    assert loaded.search("какие документы нужны для деловой визы") == []
    assert loaded.search("what documents are needed for a business visa") == []


def test_the_signed_overlay_is_pinned(loaded):
    """Инвариант по поставляемым данным: подписано ровно то, что прошло отбор.

    Каждая новая строка — это новый факт, который бот начнёт утверждать клиенту.
    Числа обязаны меняться осознанно, с прогоном scripts/build_answers_approval.py.
    """
    from app.knowledge.answerable import MONEY
    from app.knowledge import answers_approval
    overlay = answers_approval.load()
    assert overlay is not None, "оверлей одобрения исчез — бот перестал отвечать по базе"
    # Число меняется только осознанно, вместе с причиной. История: 534 → 457 (ревью
    # нашло таблицы сборов с валютой в шапке и метки в заголовках 5.5 и 9.4) → 454
    # (усиление отбора) → 453: 05.11.2026 снята подпись KG.KB.12.3#011, льготная сетка
    # швейной отрасли истекла 01.11.2026 (ai/tasks/2026-10-29-unsign-kg-kb-12-3-011.md).
    assert len(overlay.by_piece) == 453
    assert overlay.corpus_hash == loaded.corpus_hash
    assert overlay.source_hash == loaded.source_hash
    # Подписи, которые ждут снятия решением Гриши (PM-ревью 30.10.2026). Кусок 6.3#014
    # получил метку [РЕШЕНИЕ] после починки нарезки (осиротевшая метка относится к
    # предыдущему абзацу); подпись в файле осталась, но код её не признаёт:
    # `approvable=False` → `approved()` = False. Снять строку из оверлея — решение
    # владельца, см. docs/pm-review-2026-10-30/pdf.md.
    awaiting_unsign = {"KG.KB.6.3#014"}
    for piece_id, digest in overlay.by_piece.items():
        piece = loaded._pieces.get(piece_id)          # noqa: SLF001
        assert piece is not None, f"подписан несуществующий кусок {piece_id}"
        assert digest == piece["text_sha256"], f"{piece_id}: текст правили после подписи"
        if piece_id in awaiting_unsign:
            assert not answers_approval.approved(
                piece, corpus_hash=loaded.corpus_hash, source_hash=loaded.source_hash), \
                f"{piece_id}: кусок с меткой [РЕШЕНИЕ] всё ещё произносим"
            continue
        assert not piece["labels"], f"{piece_id}: подписан кусок с меткой ТЗ"
        assert not MONEY.search(piece["text"]), f"{piece_id}: подписан кусок с суммой"


def test_the_signed_overlay_actually_answers(loaded):
    """Подпись должна давать ответы, а не просто лежать в файле."""
    for query in ("какие документы нужны для деловой визы",
                  "what documents are needed for a business visa",
                  "почему отказывают в визе"):
        found = loaded.search(query, limit=3)
        assert found, f"{query!r}: оверлей подписан, а выдача пуста"
        for piece in found:
            assert not piece["labels"]


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


def test_no_inherited_label_is_signed(loaded):
    """Метка из заголовка раздела запрещает подпись так же, как своя.

    Найдено независимым ревью 22.10: раздел 5.5 «Внутренний стандарт качества файлов
    [ПРАКТИКА]» помечен в ЗАГОЛОВКЕ, и его куски без собственной метки были подписаны.
    Бот мог выдать внутренний формат имени файла за требование закона.
    """
    from app.knowledge import answers_approval
    overlay = answers_approval.load()
    assert overlay is not None
    for piece_id in overlay.by_piece:
        piece = loaded._pieces[piece_id]              # noqa: SLF001
        assert not piece["inherited_labels"], (
            f"{piece_id}: подписан кусок раздела, помеченного в заголовке "
            f"({piece['inherited_labels']})")


def test_service_crm_column_is_cut_from_table_rows(loaded):
    """Блок 17 — это реальные ситуации клиентов, а не служебная таблица.

    До 05.11.2026 к каждой строке приклеивалась шапка со столбцом «Статус / воронка
    CRM», и кусок выглядел служебным целиком. Выбор был ложный: снять подпись со всей
    таблицы (бот замолчал бы на 41 теме) или оставить боту коды статусов, которые он
    может процитировать клиенту. Режем столбец, строку оставляем.
    """
    rows = [p for p in loaded._pieces.values()                      # noqa: SLF001
            if str(p["section"]) == "17.0" and p["kind"] == "table_row"]
    assert len(rows) == 57
    for piece in rows:
        head = piece["text"].split(chr(10))[0]
        # Служебного СТОЛБЦА нет. Слово CRM в клиентской колонке «Что делать»
        # остаётся (17.0#015: «запросить PDF из CRM») — это текст ситуации, не столбец.
        assert head == "| № | Ситуация | Что делать |", piece["piece_id"]
    # Клиентский смысл не потерян: ситуация и действие на месте.
    paspo = next(p for p in rows if "Потерян паспорт" in p["text"])
    assert "Visa transfer" in paspo["text"] and "Недействительные документы" in paspo["text"]
    assert "V22" not in paspo["text"]        # код статуса из служебного столбца ушёл


def test_a_label_in_the_service_column_still_forbids_the_piece():
    """Обрезка не должна расширять то, что боту разрешено говорить.

    Метка [РЕШЕНИЕ] или сумма, стоящая в служебном столбце, обязана запрещать кусок
    и после обрезки: предикаты считаются по полному тексту, а не по усечённому.
    """
    from app.knowledge.answerable import pieces
    raw = (
        "| № | Ситуация | Что делать | Статус / воронка CRM |"
        + "\n" + "|---|---|---|---|"
        + "\n" + "| 1 | Клиент просит скидку | Отказать | X01 [РЕШЕНИЕ] |"
        + "\n" + "| 2 | Клиент просит рассрочку | Отказать | X02, депозит 500 USD |"
    )
    out = pieces({"id": "KG.KB.99.0", "section": "99.0", "block": 99,
                  "title": "", "context_text": "", "raw_text": raw,
                  "pdf_pages_from_markers": [1]})
    assert len(out) == 2
    assert all("CRM" not in p["text"] for p in out)
    # Метка из обрезанного столбца по-прежнему запрещает произносить.
    assert out[0]["labels"] == ["РЕШЕНИЕ"] and out[0]["answerable"] is False
    # Сумма из обрезанного столбца по-прежнему мешает одобрению.
    assert out[1]["has_money"] is True and out[1]["approvable"] is False


def test_a_row_with_a_different_cell_count_is_left_alone():
    """Непонятно, какой столбец служебный — не угадываем."""
    from app.knowledge.answerable import without_service_columns
    text = ("| № | Ситуация | Статус / воронка CRM |" + "\n"
            + "| 1 | Две ячейки вместо трёх |")
    assert without_service_columns(text) == text
