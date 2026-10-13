"""Локальный корпус из производного Markdown: целые таблицы, метки и provenance.

Это подготовка для поиска, не retrieval endpoint или разрешение выдачи клиенту.
Исходный текст не исполняется и не получает приоритет над инструкциями приложения.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import re

RAG_BLOCKS = (1, 2, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17)
MAX_BYTES = 5 * 1024 * 1024
LABELS = {"ПРОВЕРИТЬ": "verify", "ПРАКТИКА": "practice", "РЕШЕНИЕ": "decision"}


class CorpusError(ValueError):
    def __init__(self, code: str, line: int | None = None):
        self.code, self.line = code, line
        super().__init__(f"{code}" + (f" at line {line}" if line else ""))


def normalized_text(text: str) -> str:
    if not isinstance(text, str):
        raise CorpusError("source_type")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise CorpusError("source_unicode") from None
    if size > MAX_BYTES:
        raise CorpusError("source_too_large")
    return text


def _cells(line):
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    parts, current, escaped = [], [], False
    for char in value:
        if char == "|" and not escaped:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        escaped = char == "\\" and not escaped
    # Последний unescaped pipe закрывает строку, но || содержит пустую ячейку.
    if current or not value.endswith("|") or escaped:
        parts.append("".join(current))
    return parts


def _structure(lines):
    headings, tables, fences = [], [], []
    fence = None
    table_start = None

    def finish_table(end):
        nonlocal table_start
        if table_start is None:
            return
        rows = lines[table_start:end]
        cells = _cells(rows[0])
        if len(rows) < 2 or not all(re.fullmatch(r"\s*:?-{3,}:?\s*", c) for c in _cells(rows[1])):
            raise CorpusError("table_separator_missing", table_start + 1)
        if any(len(_cells(row)) != len(cells) for row in rows):
            raise CorpusError("table_column_mismatch", table_start + 1)
        tables.append((table_start, end))
        table_start = None

    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\n"))
        if fence:
            char, length, start = fence
            if marker and marker[1][0] == char and len(marker[1]) >= length and not marker[2].strip():
                fences.append((start, index + 1))
                fence = None
            continue
        if marker:
            finish_table(index)
            fence = (marker[1][0], len(marker[1]), index)
            continue
        if line.lstrip().startswith("|"):
            if table_start is None:
                table_start = index
            continue
        finish_table(index)
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.rstrip("\n"))
        if heading:
            headings.append((index, len(heading[1]), heading[2]))
    finish_table(len(lines))
    if fence:
        raise CorpusError("unclosed_fence", fence[2] + 1)
    return headings, tables, fences


def _pages(text):
    found = set()
    # Только структурные page markers конверсии, не числа из юридического текста.
    for match in re.finditer(r"(?m)^> PDF стр\. ([\d, –-]+)\s*$|<!--PDF:(\d+)-->|<!--TABLE pdf p\.([\d, –-]+)-->", text):
        value = next(group for group in match.groups() if group is not None)
        for part in value.split(","):
            pair = re.fullmatch(r"\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*", part)
            if pair:
                start, end = int(pair[1]), int(pair[2] or pair[1])
                if not 1 <= start <= end <= 94:
                    raise CorpusError("invalid_pdf_page_marker")
                found.update(range(start, end + 1))
    return sorted(found)


def build_corpus(markdown: str, *, version: str, rules_as_of: str, source_document: str,
                 pdf_sha256: str, split_after_chars: int = 6000) -> dict:
    """Каждый source_span — точный диапазон нормализованного Markdown, inclusive 1-based.

    Body spans покрывают выбранные блоки ровно один раз. Context повторяет родительское
    введение, чтобы при разбиении по H3 не потерять его условия/метки. Oversized фрагменты
    сохраняются целиком и отмечаются; предел не является командой разрезать таблицу.
    """
    if type(split_after_chars) is not int or split_after_chars < 100:
        raise CorpusError("invalid_split_threshold")
    if (not all(isinstance(v, str) for v in (version, rules_as_of, source_document, pdf_sha256))
            or not re.fullmatch(r"\d+\.\d+", version) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rules_as_of)
            or not re.fullmatch(r"[a-f0-9]{64}", pdf_sha256) or not source_document.strip()):
        raise CorpusError("invalid_metadata")
    try:
        date.fromisoformat(rules_as_of)
    except ValueError:
        raise CorpusError("invalid_metadata") from None
    markdown = normalized_text(markdown)
    lines = markdown.splitlines(keepends=True)
    headings, tables, fences = _structure(lines)
    top = [(line, title) for line, level, title in headings if level == 1]
    source_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    fragments, scopes, seen_blocks = [], [], set()

    def emit(start, end, *, block, section, title, context="", part=0):
        raw = "".join(lines[start:end])
        text = context + raw
        local_labels = set(re.findall(r"\[(ПРОВЕРИТЬ|ПРАКТИКА|РЕШЕНИЕ)[^\]\r\n]*\]", text))
        fid = f"KG.KB.{section}" + (f".part{part:02d}" if part else "")
        fragments.append({
            "id": fid, "kb_version": version, "rules_as_of": rules_as_of,
            "date_basis": "source_claim", "block": block, "section": section, "title": title,
            "source_document": source_document, "source_pdf_sha256": pdf_sha256,
            "source_markdown_lf_sha256": source_hash,
            "source_span": {"start_line": start + 1, "end_line": end},
            "pdf_pages_from_markers": _pages(text),
            "labels": sorted(LABELS[label] for label in local_labels),
            "source_issue_refs": sorted(set(re.findall(r"\bSRC-\d{2}\b", text))),
            "status": "draft", "may_quote": False, "publication_approved": False,
            "text": text, "raw_text": raw, "context_text": context,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "oversized": len(text) > split_after_chars,
        })

    for pos, (start, block_title) in enumerate(top):
        end = top[pos + 1][0] if pos + 1 < len(top) else len(lines)
        match = re.match(r"БЛОК (\d+)\.", block_title)
        if not match or int(match[1]) not in RAG_BLOCKS:
            continue
        block = int(match[1])
        if block in seen_blocks:
            raise CorpusError("duplicate_block", start + 1)
        seen_blocks.add(block)
        scopes.append({"block": block, "start_line": start + 1, "end_line": end})
        seconds = [(line, title) for line, level, title in headings if start < line < end and level == 2]
        intro_end = seconds[0][0] if seconds else end
        intro = "".join(lines[start:intro_end])
        emit(start, intro_end, block=block, section=f"{block}.0", title=block_title)
        seen_sections = set()
        for i, (section_start, title) in enumerate(seconds):
            section_end = seconds[i + 1][0] if i + 1 < len(seconds) else end
            match = re.match(r"(\d+\.\d+)\.\s", title)
            if not match or int(match[1].split(".")[0]) != block or match[1] in seen_sections:
                raise CorpusError("invalid_or_duplicate_section", section_start + 1)
            section = match[1]
            seen_sections.add(section)
            thirds = [line for line, level, _ in headings if section_start < line < section_end and level == 3]
            if len("".join(lines[section_start:section_end])) <= split_after_chars or not thirds:
                emit(section_start, section_end, block=block, section=section, title=title, context=intro)
            else:
                prefix_end = thirds[0]
                prefix = "".join(lines[section_start:prefix_end])
                cuts = [section_start, *thirds, section_end]
                for part, (a, b) in enumerate(zip(cuts, cuts[1:]), 1):
                    context = intro if a == section_start else intro + prefix
                    emit(a, b, block=block, section=section, title=title, context=context, part=part)
    if not fragments:
        raise CorpusError("no_rag_blocks")
    if len({f["id"] for f in fragments}) != len(fragments):
        raise CorpusError("duplicate_fragment_id")
    # Проверка атомарных конструкций независимо от логики выбора границ.
    scope_atoms = lambda atoms: [(a, b) for a, b in atoms if any(s["start_line"] - 1 <= a < s["end_line"] for s in scopes)]
    for a, b in scope_atoms(tables + fences):
        if not any(f["source_span"]["start_line"] - 1 <= a and b <= f["source_span"]["end_line"] for f in fragments):
            raise CorpusError("split_atomic_block", a + 1)
    return {
        "format": "kg-entry-search-corpus/1", "kb_version": version, "rules_as_of": rules_as_of,
        "source_pdf_sha256": pdf_sha256, "source_markdown_lf_sha256": source_hash,
        "status": "draft", "publication_approved": False, "retrieval_connected": False,
        "audit": {"blocks": sorted(seen_blocks), "source_scopes": scopes, "fragments": len(fragments),
                  "tables": len(scope_atoms(tables)), "fenced_blocks": len(scope_atoms(fences)),
                  "oversized_fragments": [f["id"] for f in fragments if f["oversized"]],
                  "fragments_with_labels": dict(sorted(Counter(label for f in fragments for label in f["labels"]).items()))},
        "fragments": fragments,
    }
