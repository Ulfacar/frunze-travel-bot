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

# Деньги в любом виде. Решение владельца 21.10: бот сумм не называет вообще, потому
# что в ТЗ (прил. Г п.2) государственные сборы имеют статус «Открыт», фактических сумм
# портала не существует, а комиссия банка названа двумя разными цифрами. Такой кусок не
# подлежит одобрению: попав в контекст модели, сумма рано или поздно будет произнесена,
# и единственным препятствием остался бы ремень валидатора.
# Валюта рядом с числом — только самый простой случай. Независимое ревью 22.10 нашло
# главный: `| Услуга | Ставка, USD | | Однократная виза до 1 месяца | 50 |` — «USD»
# стоит в ШАПКЕ таблицы, а не рядом с «50», и такой кусок считался чистым. Поэтому
# денежным считается и кусок, где слово о деньгах есть где угодно, а цифра где угодно.
MONEY = re.compile(
    r"[$€]\s?\d|\d[\d\s.,]*\s?(?:\$|€|сом|usd|eur|долл|руб)|\d+\s?%|×\s?\d|"
    r"надбавк|пошлин|тариф|скидк|бесплатн|"
    r"консульск\w*\s+сбор|сервисн\w*\s+сбор",
    re.IGNORECASE)

# Слово о деньгах плюс любое число в том же куске. Нужно для таблиц, где валюта или
# слово «ставка» стоят в шапке, а сумма — в строке данных.
MONEY_WORD = re.compile(r"ставк|сумма|стоимост|сбор|оплат|плат[аеиёй]|usd|\$|€|сом\b",
                        re.IGNORECASE)
DIGIT = re.compile(r"\d")

# Разделы ТЗ о деньгах целиком. Страховка поверх шаблонов: в блоке 12 почти каждая
# строка — сумма или условие оплаты, и полагаться на распознавание отдельной строки
# здесь нельзя.
FEE_SECTIONS = frozenset({"12.1", "12.2", "12.6", "12.8"})


def has_money(text: str, section: str = "") -> bool:
    """Есть ли в куске деньги — в любом виде, включая «50» под шапкой «Ставка, USD»."""
    if str(section or "") in FEE_SECTIONS:
        return True
    body = text or ""
    if MONEY.search(body):
        return True
    return bool(MONEY_WORD.search(body) and DIGIT.search(body))

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


# Абзац, который НАЧИНАЕТСЯ с метки и сразу за ней кончается предложение: `**[РЕШЕНИЕ]**.`
# Так конверсия PDF→Markdown разрывает хвост предыдущего абзаца (живой случай — 6.3
# «Чей e-mail указывать… из CRM» ⏎ ⏎ «**[РЕШЕНИЕ]**. Проверить…»). Такая метка
# относится к ПРЕДЫДУЩЕМУ куску: без переноса содержательный абзац уходил в одобренные
# как чистый, а ТЗ (с. 2) запрещает озвучивать `[РЕШЕНИЕ]` клиенту безусловно. Найдено
# PM-ревью 30.10.2026 на `KG.KB.6.3#014`.
#
# «**[ПРАКТИКА]**: планировать въезд…» под это НЕ попадает: после метки идёт двоеточие и
# своё предложение, это самостоятельное правило, а не хвост.
_ORPHAN_LABEL = re.compile(r"^\s*(?:\*\*)?\[(ПРОВЕРИТЬ|ПРАКТИКА|РЕШЕНИЕ)[^\]]*\]"
                           r"(?:\*\*)?\s*[.;,]")

_COMMENT = re.compile(r"<!--.*?-->")


def _strip_comments(line: str) -> str:
    """Снять комментарии конверсии, оставив содержательный остаток строки.

    Найдено ревью 22.10: строка вида `<!--PDF:37--> Кто платит пошлину` отбрасывалась
    целиком, и пять строк источника исчезали. Сторона безопасная, но инвариант
    «ничего не потеряно» нарушался.
    """
    return _COMMENT.sub(" ", line).strip()


def _is_service(line: str) -> bool:
    """Разметка, а не норма: заголовок, маркер страницы, ограда кода, пустой остаток."""
    return not line or line.startswith(("#", ">", "```"))


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
    # Метка в ЗАГОЛОВКЕ раздела помечает весь раздел. Найдено ревью 22.10: строка
    # заголовка служебная и пропускается, а унаследованные метки брались только из
    # введения блока — поэтому раздел 9.4 «…для TS [РЕШЕНИЕ]», который ТЗ запрещает
    # озвучивать вообще, считался чистым.
    inherited = _labels((fragment.get("context_text") or "")
                        + "\n" + (fragment.get("title") or ""))
    section = str(fragment.get("section") or "")
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
        text = "\n".join(_strip_comments(lines[i].strip()) for i in shown).strip()
        if not text:
            return
        own_labels, carry = _labels_with_carry(text, carry)
        orphan = _ORPHAN_LABEL.match(text) if kind == "paragraph" else None
        if orphan and out and out[-1]["kind"] == "paragraph":
            previous = out[-1]
            if orphan.group(1) not in previous["labels"]:
                previous["labels"] = [*previous["labels"], orphan.group(1)]
            decided = (NEVER_TO_CLIENT in previous["labels"]
                       or NEVER_TO_CLIENT in previous["inherited_labels"])
            previous["answerable"] = not decided
            previous["approvable"] = not decided and not previous["has_money"]
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
            # Метка РЕШЕНИЕ запрещает кусок и когда стоит в нём самом, и когда стоит
            # в заголовке раздела или во введении блока.
            "answerable": (NEVER_TO_CLIENT not in own_labels
                           and NEVER_TO_CLIENT not in inherited),
            # Одобрению подлежит только то, что и по метке можно, и денег не содержит.
            "approvable": (NEVER_TO_CLIENT not in own_labels
                           and NEVER_TO_CLIENT not in inherited
                           and not has_money(text, section)),
            "has_money": has_money(text, section),
            "grants": sorted(claimed_fields(text)),
            "source_lines": owned,
        })

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            emit(paragraph, "paragraph")
            paragraph = []

    for index, raw_line in enumerate(lines):
        line = _strip_comments(raw_line.strip())

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
