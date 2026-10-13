"""Фиксированная конверсия PDF v1.1: прямое извлечение, без доступа к сети/БД.

Capture — проверяемый снимок выбранных таблиц/страниц, а не подтверждение их актуальности.
Не использовать этот парсер как универсальный PDF-importer: другой хеш требует нового mapping.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import json
from pathlib import Path
import re
import sys

from yaml import YAMLError
from app.knowledge.validation import StrictLoader, check_tree

PDF_SHA256 = "141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2"
PDF_NAME = "Kyrgyzstan-visa-knowledge-base-v1.1.pdf"
PDF_BYTES = 1_263_396
SOURCE_PAGES = (9, 13, 15, 19, 20, 21, 22, 23, 24, 25, 30, 59, 61, 62, 82, 85, 86, 88, 89)
EXPECTED_ROWS = {"registration": 9, "service_fees": 11, "processing_times": 10,
                 "deadlines": 22, "escalation": 12}


def normalize(text: str) -> str:
    """Только типографика/пробелы; не удаляет числа, метки или слова."""
    return re.sub(r"\s+", "", text.replace("\u00ad", "").replace("\u00a0", " "))


def clean_page(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(line for line in lines
                     if not line.startswith("Визы в Кыргызстан — база знаний и SOP")
                     and not re.fullmatch(r"\d+ / 93", line.strip())).strip("\n")


def extract_pdf(pdf: Path) -> dict:
    # Импорт внутри функции: проверка уже сохранённого capture не требует PyMuPDF.
    with pdf.open("rb") as stream:
        raw = stream.read(PDF_BYTES + 1)
    if len(raw) != PDF_BYTES or hashlib.sha256(raw).hexdigest() != PDF_SHA256:
        raise ValueError("Unexpected PDF SHA-256; source mapping must be reviewed")
    import fitz
    capture = {"format": "kg-entry-source-capture/1", "pdf_sha256": PDF_SHA256,
               "pdf_name": PDF_NAME, "pages": {}, "tables": {key: [] for key in EXPECTED_ROWS}}
    with fitz.open(stream=raw, filetype="pdf") as doc:
        if len(doc) != 94:
            raise ValueError("Expected 94 PDF pages")
        for number in SOURCE_PAGES:
            page = doc[number - 1]
            capture["pages"][str(number)] = clean_page(page.get_text())
            if number not in {24, 25, 30, 59, 61, 62}:
                continue
            # PyMuPDF печатает рекламную подсказку один раз; CLI stdout остаётся JSON.
            with redirect_stdout(sys.stderr):
                finder = page.find_tables()
            for table in finder.tables:
                rows = table.extract()
                header = [" ".join((c or "").split()) for c in rows[0]]
                key = None
                if number in {24, 25} and header[-1] == "Страны":
                    key = "registration"
                elif number == 59 and header == ["Услуга", "Предложение", "Логика"]:
                    key = "service_fees"
                elif number == 61 and len(header) == 7 and header[0] == "Продукт":
                    key = "processing_times"
                elif number in {61, 62} and header == ["Дедлайн", "Значение", "Источник"]:
                    key = "deadlines"
                elif number == 30 and header == ["Признак", "Почему стоп", "Действие"]:
                    key = "escalation"
                if key:
                    capture["tables"][key] += [{"page": number, "row": i,
                                               "cells": [" ".join((c or "").split()) for c in row]}
                                              for i, row in enumerate(rows[1:], 1)]
    validate_capture(capture)
    return capture


def validate_capture(capture: dict) -> None:
    if capture.get("format") != "kg-entry-source-capture/1" or capture.get("pdf_sha256") != PDF_SHA256:
        raise ValueError("Unsupported source capture")
    if set(capture["pages"]) != {str(n) for n in SOURCE_PAGES}:
        raise ValueError("Missing source pages")
    if set(capture["tables"]) != set(EXPECTED_ROWS):
        raise ValueError("Unexpected source tables")
    for name, expected in EXPECTED_ROWS.items():
        rows = capture["tables"][name]
        columns = {"registration": 2, "service_fees": 3, "processing_times": 7, "deadlines": 3, "escalation": 3}[name]
        if len(rows) != expected or any(len(row["cells"]) != columns or
                                      not all(isinstance(c, str) and c.strip() for c in row["cells"])
                                      or str(row["page"]) not in capture["pages"] for row in rows):
            raise ValueError(f"Source table coverage mismatch: {name}")
    if len(template_sections(capture)) != 13:
        raise ValueError("Expected 13 templates")


def strict_source_yaml(raw: str):
    try:
        loader = StrictLoader(raw)
        loader.filename = "source-B5"
        try:
            result = loader.get_single_data()
        finally:
            loader.dispose()
    except YAMLError:
        raise ValueError("Malformed source B.5 YAML") from None
    check_tree(result)
    return result


def source_yaml(capture: dict) -> tuple[dict, str]:
    first = capture["pages"]["88"]
    last = capture["pages"]["89"]
    raw = first[first.index('version: "2026-10-02"'):] + "\n" + last[:last.index("Б.6.")]
    # Единственная синтаксическая склейка: перенос комментария стал строкой YAML.
    raw = raw.replace("\nподдержки портала", " поддержки портала")
    parsed = strict_source_yaml(raw)
    if set(parsed) != {"version", "sources", "registration_default", "visa_free", "special", "visa_required", "rules"}:
        raise ValueError("Unexpected appendix B.5 structure")
    return parsed, raw


def template_sections(capture: dict) -> list[dict]:
    first = capture["pages"]["85"]
    text = first + "\n" + capture["pages"]["86"]
    matches = list(re.finditer(r"^А\.(\d+)\. ([^\n]+)\n", text, re.M))
    return [{"number": int(m.group(1)), "title": m.group(2),
             "text": text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip(),
             "pages": [85, 86] if m.group(1) == "7" else [85 if m.start() < len(first) else 86]}
            for i, m in enumerate(matches)]


def markdown_tables(markdown: str) -> list[list[list[str]]]:
    """Только таблицы существующей конверсии E5-01; не общий Markdown parser."""
    tables, current = [], []
    for line in markdown.splitlines() + [""]:
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                current.append(cells)
        elif current:
            tables.append(current)
            current = []
    return tables


def compare_conversion(capture: dict, markdown: str) -> dict:
    """Сверка именно входов генератора. Не сертифицирует все 94 страницы E5-01."""
    tables = markdown_tables(markdown)
    selectors = {"registration": "Срок, в течение которого можно не регистрироваться",
                 "service_fees": "Услуга", "processing_times": "Продукт",
                 "deadlines": "Дедлайн", "escalation": "Признак"}
    comparisons = []
    for key, header in selectors.items():
        candidates = [t for t in tables if t[0][0] == header and len(t) - 1 == EXPECTED_ROWS[key]]
        if len(candidates) != 1:
            raise ValueError(f"Cannot identify derived table: {key}")
        pdf_rows = [row["cells"] for row in capture["tables"][key]]
        for number, (pdf_row, md_row) in enumerate(zip(pdf_rows, candidates[0][1:]), 1):
            cleaned = [re.sub(r"\*\*\[SRC-03:[^\]]+\]\*\*", "", c) for c in md_row]
            if [normalize(c) for c in pdf_row] != [normalize(c) for c in cleaned]:
                raise ValueError(f"Derived/PDF table cell mismatch: {key} row {number}")
        comparisons.append({"table": key, "rows": len(pdf_rows), "result": "PASS"})
    original, _ = source_yaml(capture)
    expected = deepcopy(original)
    vf = expected["visa_free"]
    vf["ninety_180"]["registration_exempt_days"]["Молдова"] = None
    vf["ninety_180"]["registration_exempt_days_blocked"] = {
        "Молдова": {"source_value": 90, "status": "BLOCKED_NEEDS_VERIFICATION", "conflict": "SRC-04"}}
    vf["annex1_30_60"]["registration_exempt_days_exceptions"] = {"Греция": 90, "Чили": 60}
    expected["visa_free"]["other_check_portal"]["note"] = re.sub(
        r"\s+,", ",", expected["visa_free"]["other_check_portal"]["note"])
    blocks = re.findall(r"```yaml\n(.*?)\n```", markdown, re.S)
    if len(blocks) != 1 or strict_source_yaml(blocks[0]) != expected:
        raise ValueError("Derived/PDF B.5 differs beyond documented SRC-04/05 and whitespace repair")
    headings = list(re.finditer(r"^### А\.(\d+)\. ([^\n]+)\n", markdown, re.M))
    if len(headings) != 13:
        raise ValueError("Derived template count mismatch")
    for index, (source, heading) in enumerate(zip(template_sections(capture), headings)):
        end = headings[index + 1].start() if index + 1 < len(headings) else markdown.index("# Приложение Б.", heading.end())
        body = markdown[heading.end():end]
        body = re.sub(r"<!--.*?-->|^> PDF стр\. \d+\s*$", "", body, flags=re.M).replace("**", "")
        if int(heading.group(1)) != source["number"] or normalize(body) != normalize(source["text"]):
            raise ValueError(f"Derived/PDF template mismatch: A.{source['number']}")
    return {"tables": comparisons, "b5": "PASS_WITH_DOCUMENTED_SRC04_SRC05",
            "templates": {"count": 13, "result": "PASS"},
            "scope": "selected generator inputs only", "legal_review": "UNKNOWN"}


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
