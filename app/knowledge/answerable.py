"""Нарезка фрагментов базы знаний на куски, которые бот вправе произносить.

Зачем отдельный слой поверх корпуса поиска. `app/knowledge/corpus.py` режет базу по
разделам ТЗ: один раздел или одна таблица — один фрагмент. Для поиска это правильно, а
для речи — слишком крупно по двум причинам.

**Метки.** `[ПРОВЕРИТЬ]`, `[ПРАКТИКА]` и `[РЕШЕНИЕ]` извлекаются по всему тексту
фрагмента, включая унаследованное введение блока. Одна метка во введении «пачкает» все
фрагменты блока: на уровне фрагментов произносить можно было бы 33 из 74, на уровне
кусков хотя бы один чистый кусок есть во всех 74. При этом по самому ТЗ (стр. 2)
безусловно запрещён клиенту только `[РЕШЕНИЕ]`; `[ПРОВЕРИТЬ]` — «не называть как точный
факт», `[ПРАКТИКА]` — «не выдавая за требование закона».

**Размер.** Фрагмент бывает 4133 символа, и целиком в контекст модели он не влезает по
деньгам. Медианный кусок — 84 символа.

Что здесь НЕ делается: ничего не одобряется. Нарезка только готовит куски и честно
размечает их метками и происхождением. Право произнести даёт отдельный оверлей
одобрения, подписанный человеком (`app/knowledge/answers_approval.py`).

Инвариант, который держит весь слой: **ни один содержательный символ источника не
потерян и не задвоен.** Каждая содержательная строка фрагмента принадлежит ровно одному
куску; служебные строки (заголовки, маркеры `> PDF стр. N`, комментарии конверсии,
разделители таблиц) фактами не становятся. Проверяется `tests/test_answerable_pieces.py`.
"""
from __future__ import annotations

from hashlib import sha256
import re
from typing import Any

LABEL = re.compile(r"\[(ПРОВЕРИТЬ|ПРАКТИКА|РЕШЕНИЕ)[^\]]*\]")

# Открытие метки без требования закрывающей скобки. Нужно потому, что метка бывает
# разорвана между кусками — см. `_labels_with_carry`.
LABEL_OPENING = re.compile(r"\[(ПРОВЕРИТЬ|ПРАКТИКА|РЕШЕНИЕ)")

# По ТЗ (стр. 2) клиенту не озвучивается вообще только это.
NEVER_TO_CLIENT = "РЕШЕНИЕ"

_TABLE_SEPARATOR = re.compile(r"\|[\s\-:|]+\|")
_NUMBERED = re.compile(r"^\d+[.)]\s")
_BULLET = re.compile(r"^[-*+]\s")


def _labels(text: str) -> list[str]:
    """Метки, стоящие в самом тексте. Порядок сохраняем для читаемости диффов."""
    found: list[str] = []
    for match in LABEL.finditer(text or ""):
        kind = match.group(1)
        if kind not in found:
            found.append(kind)
    return found


def _labels_with_carry(text: str, carried: str | None) -> tuple[list[str], str | None]:
    """Метки куска с учётом метки, ОТКРЫТОЙ в предыдущем куске.

    Считаем открытия, а не закрытые пары. Причина — живой случай в разделе 2.7:
    «[ПРОВЕРИТЬ на портале по конкретной стране — «Do» открывается в одном абзаце и
    закрывается в следующем. Регекс закрытой пары его не видел, и утверждение, которое
    ТЗ велит не называть как точный факт, попадало в отвечаемые как чистое. На уровне
    целого фрагмента дыры нет — текст там многострочный и пара находится; дыра есть
    ровно на уровне куска.

    Возвращает (метки этого куска, метка, которую несём на следующий).
    """
    body = text or ""
    found: list[str] = []
    carry = carried
    start = 0

    if carry is not None:
        found.append(carry)
        closing = body.find("]")
        if closing == -1:
            return found, carry          # кусок целиком внутри открытой метки
        carry, start = None, closing + 1

    for match in LABEL_OPENING.finditer(body, start):
        kind = match.group(1)
        if kind not in found:
            found.append(kind)
        if "]" not in body[match.end():]:
            carry = kind                 # закрытия в этом куске нет — несём дальше
    return found, carry


def _is_service(line: str) -> bool:
    """Разметка, а не норма: заголовок, маркер страницы, комментарий, ограда кода."""
    return line.startswith(("#", ">", "<!--", "```"))


def _digest(text: str) -> str:
    return sha256((text or "").encode("utf-8")).hexdigest()


def pieces(fragment: dict[str, Any]) -> list[dict[str, Any]]:
    """Фрагмент корпуса → список атомарных кусков.

    Куски трёх видов:
      * `table_row` — строка данных таблицы, **всегда со строкой заголовков**: ячейка
        «30 дней | Австралия, Австрия…» без шапки означает что угодно. Шапку
        «владеет» первая строка данных, поэтому в покрытии источника она учтена один
        раз, а в тексте присутствует у каждой строки;
      * `list_item` — нумерованный или маркированный пункт;
      * `paragraph` — абзац прозы (подряд идущие строки до пустой).
    """
    raw = fragment.get("raw_text") or ""
    lines = raw.split("\n")
    inherited = _labels(fragment.get("context_text") or "")
    fragment_id = str(fragment.get("id") or "")
    pages = list(fragment.get("pdf_pages_from_markers") or [])

    out: list[dict[str, Any]] = []
    paragraph: list[int] = []          # индексы строк текущего абзаца
    table_header: list[int] = []       # индексы строк шапки текущей таблицы
    header_taken = False               # шапку уже «присвоила» первая строка данных
    in_table_body = False

    carry: str | None = None           # метка, открытая в предыдущем куске

    def emit(indexes: list[int], kind: str, *, prepend: list[int] = ()) -> None:
        nonlocal carry
        owned = list(indexes)
        shown = list(prepend) + owned
        text = "\n".join(lines[i].strip() for i in shown).strip()
        if not text:
            return
        own_labels, carry = _labels_with_carry(text, carry)
        from app.agent.entry_guards import claimed_fields
        out.append({
            "piece_id": f"{fragment_id}#{len(out) + 1:03d}",
            "fragment_id": fragment_id,
            "block": fragment.get("block"),
            "section": fragment.get("section"),
            "title": fragment.get("title"),
            "pdf_pages": pages,
            "kind": kind,
            "text": text,
            "text_sha256": _digest(text),
            "labels": own_labels,
            "inherited_labels": list(inherited),
            "answerable": NEVER_TO_CLIENT not in own_labels,
            "grants": sorted(claimed_fields(text)),
            "source_lines": owned,
        })

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            emit(paragraph, "paragraph")
            paragraph = []

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()

        if not line:
            flush_paragraph()
            table_header, header_taken, in_table_body = [], False, False
            continue

        if _is_service(line):
            # Служебная строка обрывает абзац и таблицу, но куском не становится.
            flush_paragraph()
            table_header, header_taken, in_table_body = [], False, False
            continue

        if _TABLE_SEPARATOR.fullmatch(line):
            # Разделитель шапки: дальше идут строки данных. Сам разделитель не нужен.
            flush_paragraph()
            in_table_body = True
            continue

        if line.startswith("|"):
            flush_paragraph()
            if not in_table_body:
                table_header.append(index)      # ещё шапка
                continue
            if not header_taken and table_header:
                # Первая строка данных владеет и шапкой: так шапка покрыта ровно раз.
                emit(table_header + [index], "table_row")
                header_taken = True
            else:
                emit([index], "table_row", prepend=table_header)
            continue

        # Вне таблицы: пункт списка — свой кусок, остальное собирается в абзац.
        table_header, header_taken, in_table_body = [], False, False
        if _NUMBERED.match(line) or _BULLET.match(line):
            flush_paragraph()
            emit([index], "list_item")
            continue
        paragraph.append(index)

    flush_paragraph()
    return out
