"""ГЕЙТ: нарезка базы знаний на куски, которые бот вправе произносить.

Написан ДО реализации.

Зачем куски, а не фрагменты поиска. Метки ТЗ (`[ПРОВЕРИТЬ]`, `[ПРАКТИКА]`,
`[РЕШЕНИЕ]`) извлекаются по всему тексту фрагмента, включая унаследованное введение
блока, поэтому одна метка во введении «пачкает» весь блок: на уровне фрагментов
годились бы 33 из 74, на уровне кусков чистый кусок есть во всех 74.

Что здесь закреплено, в порядке важности:

1. **Ни один символ источника не потерян и не задвоен.** Это тот же инвариант, что
   `tests/test_kg_search_corpus.py` держит для фрагментов: каждая содержательная строка
   исходника попадает ровно в один кусок.
2. **Служебные строки не становятся фактами.** Заголовки, маркеры `> PDF стр. N`,
   комментарии конверсии и разделители таблиц — это разметка, а не норма закона.
3. **Строка таблицы носит свою шапку.** Ячейка «30 дней | Австралия, Австрия…» без
   строки заголовков означает что угодно.
4. **Своя метка куска и унаследованная различаются.** По ТЗ `[РЕШЕНИЕ]` клиенту не
   озвучивается вообще, а метка из введения блока лишь понижает кусок до «мягко».
5. **`grants` равен тому, о чём кусок сам говорит.** Кусок не вправе открывать ремню
   валидатора поля, которых не упоминает.
"""
import re

import pytest

LABEL = re.compile(r"\[(ПРОВЕРИТЬ|ПРАКТИКА|РЕШЕНИЕ)[^\]]*\]")
SERVICE_PREFIXES = ("#", ">", "<!--", "```")


@pytest.fixture(scope="module")
def corpus():
    pytest.importorskip("app.knowledge.answerable")
    from app.knowledge.retrieval import load_review_index
    try:
        index = load_review_index()
    except Exception as exc:  # noqa: BLE001 — без корпуса гейт неприменим
        pytest.skip(f"корпус знаний недоступен: {type(exc).__name__}")
    return [index.fragment(fid) for fid in sorted(index._fragments)]  # noqa: SLF001


@pytest.fixture(scope="module")
def sliced(corpus):
    from app.knowledge.answerable import pieces
    return {f["id"]: pieces(f) for f in corpus}


# --- A. Ничего не потеряно и не задвоено ---------------------------------------

def test_every_content_line_lands_in_exactly_one_piece(corpus, sliced):
    """Главный инвариант: покрытие источника кусками ровно один раз."""
    for fragment in corpus:
        lines = [raw.strip() for raw in (fragment["raw_text"] or "").split("\n")]
        content = [
            line for line in lines
            if line
            and not line.startswith(SERVICE_PREFIXES)
            and not re.fullmatch(r"\|[\s\-:|]+\|", line)
        ]
        # Строки таблиц встречаются в кусках вместе с шапкой, поэтому сверяем вхождение.
        covered = []
        for piece in sliced[fragment["id"]]:
            covered.extend(piece["source_lines"])
        assert len(covered) == len(set(covered)), \
            f"{fragment['id']}: строка источника попала в два куска"
        taken = {line for piece in sliced[fragment["id"]] for line in piece["source_lines"]}
        missing = [i for i, line in enumerate(lines)
                   if line in content and i not in taken]
        assert not missing, (
            f"{fragment['id']}: содержательные строки не попали ни в один кусок: "
            f"{[lines[i][:60] for i in missing[:3]]}")


def test_service_lines_never_become_facts(sliced):
    """Заголовок, маркер страницы и комментарий конверсии — разметка, не норма."""
    for fragment_id, items in sliced.items():
        for piece in items:
            body = piece["text"]
            assert body.strip(), f"{fragment_id}: пустой кусок"
            for line in body.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                assert not stripped.startswith(("#", ">", "<!--")), \
                    f"{fragment_id}: служебная строка стала куском: {stripped[:60]!r}"
                assert not re.fullmatch(r"\|[\s\-:|]+\|", stripped), \
                    f"{fragment_id}: разделитель таблицы стал куском"


# --- B. Таблица не разорвана ---------------------------------------------------

def test_a_table_row_carries_its_header(sliced):
    """Ячейка без строки заголовков означает что угодно."""
    rows = [p for items in sliced.values() for p in items if p["kind"] == "table_row"]
    assert rows, "ни одной строки таблицы не нарезано — таблиц в корпусе 40"
    for piece in rows:
        lines = [line for line in piece["text"].split("\n") if line.strip()]
        assert len(lines) >= 2, (
            f"{piece['piece_id']}: строка таблицы без шапки: {piece['text'][:80]!r}")
        assert lines[0].lstrip().startswith("|"), \
            f"{piece['piece_id']}: первая строка куска — не шапка таблицы"


def test_table_header_itself_is_not_a_fact(sliced):
    """Шапка «Срок | Страны» фактом не является и отдельным куском быть не должна."""
    for items in sliced.values():
        for piece in items:
            if piece["kind"] != "table_row":
                continue
            lines = [line for line in piece["text"].split("\n") if line.strip()]
            assert len(lines) > 1, f"{piece['piece_id']}: кусок состоит только из шапки"


# --- C. Метки: своя и унаследованная ------------------------------------------

def test_own_labels_come_from_the_piece_text(sliced):
    """Метка, ЗАКРЫТАЯ внутри куска, обязана быть у него записана."""
    for items in sliced.values():
        for piece in items:
            closed = {LABEL.match(m.group(0)).group(1)
                      for m in LABEL.finditer(piece["text"])}
            assert closed <= set(piece["labels"]), (
                f"{piece['piece_id']}: закрытая метка не записана: {closed}")


OPENING = re.compile(r"\[(ПРОВЕРИТЬ|ПРАКТИКА|РЕШЕНИЕ)")


def test_a_label_torn_between_two_pieces_is_not_lost(sliced):
    """Считаем ОТКРЫТИЯ метки, а не закрытые пары.

    Найдено проверкой 22.10: в разделе 2.7 метка `[ПРОВЕРИТЬ ...` открывается в одном
    абзаце и закрывается в следующем. Регекс закрытой пары её не видел, и кусок
    выглядел чистым — то есть утверждение, которое ТЗ велит не называть как точный
    факт, попало бы в отвечаемые. На уровне целого фрагмента дыра не проявляется,
    только на уровне куска.
    """
    for items in sliced.values():
        for piece in items:
            openings = len(OPENING.findall(piece["text"]))
            closed = len(LABEL.findall(piece["text"]))
            if openings != closed:
                assert piece["labels"], (
                    f"{piece['piece_id']}: метка открыта и не закрыта внутри куска, "
                    f"а кусок считается чистым: {piece['text'][-90:]!r}")


def test_the_known_torn_label_is_pinned(sliced):
    """Именованная регрессия на тот самый кусок раздела 2.7."""
    pieces_27 = sliced.get("KG.KB.2.7") or []
    torn = [p for p in pieces_27 if OPENING.findall(p["text"])
            and len(OPENING.findall(p["text"])) != len(LABEL.findall(p["text"]))]
    assert torn, "кусок с разорванной меткой в разделе 2.7 исчез — проверь источник"
    for piece in torn:
        assert "ПРОВЕРИТЬ" in piece["labels"], (
            f"{piece['piece_id']}: разорванная метка ПРОВЕРИТЬ не подхвачена")


def test_a_piece_inside_an_open_label_inherits_it(sliced):
    """Кусок, целиком попавший внутрь открытой метки, тоже помечен.

    Иначе хвост «…Do I need visa?»]» выглядел бы чистым фактом.
    """
    for items in sliced.values():
        carried = None
        for piece in items:
            if carried and "]" in piece["text"]:
                assert carried in piece["labels"], (
                    f"{piece['piece_id']}: хвост открытой метки {carried} не помечен")
            openings = len(OPENING.findall(piece["text"]))
            closed = len(LABEL.findall(piece["text"]))
            carried = (piece["labels"][-1] if piece["labels"] else None)                 if openings != closed else None


def test_inherited_labels_do_not_become_own(corpus, sliced):
    """Метка во введении блока не делает кусок помеченным — она только понижает его."""
    for fragment in corpus:
        context_labels = {LABEL.match(m.group(0)).group(1)
                          for m in LABEL.finditer(fragment["context_text"] or "")}
        for piece in sliced[fragment["id"]]:
            assert set(piece["inherited_labels"]) == context_labels, \
                f"{piece['piece_id']}: унаследованные метки собраны неверно"
            if context_labels and not LABEL.search(piece["text"]):
                assert piece["labels"] == [], (
                    f"{piece['piece_id']}: унаследованная метка записана как своя")


def test_a_decision_piece_is_never_answerable(sliced):
    """ТЗ: `[РЕШЕНИЕ]` — «клиенту не озвучивать». Безусловно."""
    for items in sliced.values():
        for piece in items:
            if "РЕШЕНИЕ" in piece["labels"]:
                assert piece["answerable"] is False, \
                    f"{piece['piece_id']}: кусок с меткой РЕШЕНИЕ помечен отвечаемым"


def test_unlabelled_pieces_are_answerable(sliced):
    without = [p for items in sliced.values() for p in items if not p["labels"]]
    assert without, "ни одного куска без метки — это противоречит замеру по ПДФ"
    for piece in without:
        assert piece["answerable"] is True, \
            f"{piece['piece_id']}: кусок без метки не отвечаем"


# --- D. Разрешения ремня -------------------------------------------------------

def test_grants_match_what_the_piece_itself_says(sliced):
    """Кусок открывает ремню ровно те поля, о которых говорит, и ничего сверх."""
    from app.agent.entry_guards import claimed_fields
    for items in sliced.values():
        for piece in items:
            assert set(piece["grants"]) == set(claimed_fields(piece["text"])), (
                f"{piece['piece_id']}: grants не совпадает с claimed_fields текста")


def test_grants_never_include_anything_outside_the_belt(sliced):
    allowed = {"regime", "stay_limit", "registration", "unified_permit"}
    for items in sliced.values():
        for piece in items:
            assert set(piece["grants"]) <= allowed, \
                f"{piece['piece_id']}: grants содержит поле вне ремня"


# --- E. Устойчивость идентификаторов -------------------------------------------

def test_piece_ids_are_unique_and_stable(sliced):
    seen = set()
    for fragment_id, items in sliced.items():
        for piece in items:
            assert piece["piece_id"] not in seen, f"дубль piece_id: {piece['piece_id']}"
            seen.add(piece["piece_id"])
            assert piece["piece_id"].startswith(fragment_id + "#"), \
                f"{piece['piece_id']}: идентификатор не привязан к фрагменту"
            assert piece["fragment_id"] == fragment_id
            assert piece["block"] and piece["section"]


def test_slicing_is_deterministic(corpus):
    from app.knowledge.answerable import pieces
    for fragment in corpus[:5]:
        assert pieces(fragment) == pieces(fragment), \
            f"{fragment['id']}: нарезка не детерминирована"


def test_each_piece_keeps_its_provenance(sliced):
    """Основание менеджеру: раздел и страницы ПДФ у каждого куска."""
    for items in sliced.values():
        for piece in items:
            assert piece["text_sha256"] and len(piece["text_sha256"]) == 64
            assert isinstance(piece["pdf_pages"], list)
            assert piece["kind"] in ("paragraph", "table_row", "list_item")


# --- F. Состав прибит числом ---------------------------------------------------

def test_the_slice_is_pinned_by_the_numbers(sliced):
    """Замер 22.10.2026 на корпусе v1.1. Изменились числа — изменилась база или нарезка.

    Это тот же приём, что держит бандл единиц в `tests/test_entry_bundle_pinned.py`:
    молча поехавшая нарезка меняет то, что бот говорит иностранцу про закон.
    """
    import collections
    items = [p for group in sliced.values() for p in group]
    assert len(items) == 721, f"кусков {len(items)}, ожидалось 721"
    assert dict(collections.Counter(p["kind"] for p in items)) == {
        "table_row": 451, "paragraph": 225, "list_item": 45}

    labels = collections.Counter()
    for piece in items:
        if "РЕШЕНИЕ" in piece["labels"]:
            labels["РЕШЕНИЕ"] += 1
        elif "ПРОВЕРИТЬ" in piece["labels"]:
            labels["ПРОВЕРИТЬ"] += 1
        elif "ПРАКТИКА" in piece["labels"]:
            labels["ПРАКТИКА"] += 1
        else:
            labels["без метки"] += 1
    # ПРОВЕРИТЬ 53, а не 51: два куска раздела 2.7 считались чистыми, пока метки
    # искались закрытыми парами, а не открытиями — см. тесты про разорванную метку.
    assert dict(labels) == {"без метки": 613, "ПРОВЕРИТЬ": 53,
                            "ПРАКТИКА": 34, "РЕШЕНИЕ": 21}
    assert sum(1 for p in items if p["answerable"]) == 700
    assert sum(1 for p in items if p["grants"]) == 283


def test_fragments_without_content_produce_nothing(sliced):
    """Фрагмент из одного заголовка и маркера страницы кусков не даёт — и это верно."""
    empty = [fid for fid, group in sliced.items() if not group]
    assert len(empty) == 9, f"фрагментов без кусков {len(empty)}, ожидалось 9: {empty}"
