"""Corpus source fidelity, exclusion scope, labels and reproducible artifacts."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from app.knowledge.corpus import CorpusError, RAG_BLOCKS, build_corpus, normalized_text
from scripts.build_kg_search_corpus import DIRECTORY, LOCK, SOURCE, payload

ROOT = Path(__file__).resolve().parents[1]
META = {"version": "1.1", "rules_as_of": "2026-10-02", "source_document": "synthetic.md", "pdf_sha256": "1" * 64}


def build(text, **kwargs):
    return build_corpus(text, **META, **kwargs)


def test_real_source_coverage_is_exact_and_table_markers_stay_with_rows():
    encoded, audit = payload()
    corpus = json.loads(encoded)
    text = normalized_text(SOURCE.read_text(encoding="utf-8"))
    lines = text.splitlines(keepends=True)
    expected_scopes = []
    headings = list(re.finditer(r"(?m)^# .+$", text))
    for index, heading in enumerate(headings):
        match = re.match(r"# БЛОК (\d+)\.", heading[0])
        if match and int(match[1]) in RAG_BLOCKS:
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            expected_scopes.append(text[heading.start():end])
    observed = "".join(fragment["raw_text"] for fragment in corpus["fragments"])
    assert observed == "".join(expected_scopes)
    assert corpus["audit"]["blocks"] == list(RAG_BLOCKS)
    assert len(corpus["fragments"]) == 74 and audit["tables"] == 40
    line_counts = Counter()
    for fragment in corpus["fragments"]:
        span = fragment["source_span"]
        assert fragment["raw_text"] == "".join(lines[span["start_line"] - 1:span["end_line"]])
        line_counts.update(range(span["start_line"], span["end_line"] + 1))
        assert fragment["text"] == fragment["context_text"] + fragment["raw_text"]
        assert fragment["text_sha256"] == hashlib.sha256(fragment["text"].encode("utf-8")).hexdigest()
        assert fragment["publication_approved"] is False and fragment["may_quote"] is False
    assert set(line_counts.values()) == {1}
    assert "# БЛОК 14." not in observed and "# БЛОК 18." not in observed
    assert "## Б.3." not in observed and "## Б.5." not in observed
    assert "# Итоги конверсии" not in observed
    assert corpus["source_markdown_lf_sha256"] == json.loads(LOCK.read_text(encoding="utf-8"))["markdown_lf_sha256"]


def test_large_section_splits_only_at_h3_and_keeps_parent_conditions():
    text = ("# БЛОК 5. Документы [ПРОВЕРИТЬ]\n> PDF стр. 38\nОбщее условие.\n\n"
            "## 5.3. Чек-листы [РЕШЕНИЕ]\nОбязательно согласование.\n\n"
            "### Первый [ПРАКТИКА]\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "### Второй\n" + "Дополнительный текст. " * 50 + "\n")
    corpus = build(text, split_after_chars=150)
    children = [f for f in corpus["fragments"] if f["section"] == "5.3"]
    assert len(children) == 3
    assert all("Общее условие." in f["context_text"] for f in children)
    assert all("Обязательно согласование." in f["context_text"] for f in children[1:])
    first = children[1]
    assert first["labels"] == ["decision", "practice", "verify"]
    assert first["pdf_pages_from_markers"] == [38]
    assert "| A | B |\n|---|---|\n| 1 | 2 |" in first["raw_text"]
    assert "".join(f["raw_text"] for f in corpus["fragments"]) == text
    assert children[-1]["oversized"] is True


def test_large_table_is_not_truncated_or_split():
    table = "| Country | Days |\n|---|---|\n" + "| Test | 12 |\n" * 100
    corpus = build("# БЛОК 2. Страны\n## 2.1. Таблица\n" + table, split_after_chars=100)
    assert len(corpus["fragments"]) == 2
    assert table in corpus["fragments"][1]["raw_text"]
    assert corpus["fragments"][1]["oversized"] is True
    assert corpus["audit"]["tables"] == 1


@pytest.mark.parametrize("marker", ["```", "~~~~"])
def test_fake_headings_inside_fenced_blocks_do_not_create_chunks(marker):
    text = f"# БЛОК 1. Test\n## 1.1. Text\n{marker}text\n# БЛОК 2. Fake\n## 2.1. Fake\n### fake\n{marker}\n"
    corpus = build(text, split_after_chars=100)
    assert corpus["audit"]["blocks"] == [1]
    assert corpus["audit"]["fenced_blocks"] == 1
    assert f"{marker}text\n# БЛОК 2. Fake" in corpus["fragments"][1]["raw_text"]


def test_entire_unselected_block_stays_out_even_when_containing_code_and_instructions():
    text = ("# БЛОК 3. Questions\nDO_NOT_INCLUDE\n# БЛОК 1. Types\n## 1.1. Included\nOK\n"
            "# Приложение Б.\n## Б.3. Slots\n```json\n{\"instruction\": \"DO_NOT_INCLUDE\"}\n```\n")
    corpus = build(text)
    assert "DO_NOT_INCLUDE" not in json.dumps(corpus)


@pytest.mark.parametrize("text,code", [
    ("# БЛОК 1. One\n```json\n{}", "unclosed_fence"),
    ("# БЛОК 1. One\n| A | B |\n| a | b |\n", "table_separator_missing"),
    ("# БЛОК 1. One\n| A | B |\n|---|---|\n| only one |\n", "table_column_mismatch"),
    ("# БЛОК 1. One\n## 2.1. Wrong block\n", "invalid_or_duplicate_section"),
    ("# БЛОК 1. One\n## 1.1. One\n## 1.1. Again\n", "invalid_or_duplicate_section"),
    ("# БЛОК 1. One\n# БЛОК 1. Again\n", "duplicate_block"),
    ("# БЛОК 1. One\n## Unnumbered\n", "invalid_or_duplicate_section"),
    ("# Only intro\n", "no_rag_blocks"),
    ("# БЛОК 1. One\n> PDF стр. 999\n", "invalid_pdf_page_marker"),
])
def test_bad_structure_has_bounded_error(text, code):
    with pytest.raises(CorpusError, match=code):
        build(text)


def test_empty_table_cells_and_escaped_pipes_are_preserved():
    table = "|A|B|\n|---|---|\n|one||\n|x\\|y|two|\n"
    result = build("# БЛОК 1. One\n" + table)
    assert result["fragments"][0]["raw_text"].endswith(table)


@pytest.mark.parametrize("metadata", [{"version": None}, {"rules_as_of": "2026-99-02"}, {"pdf_sha256": "x"}, {"source_document": " "}])
def test_invalid_metadata_is_not_source_truth(metadata):
    with pytest.raises(CorpusError, match="invalid_metadata"):
        build_corpus("# БЛОК 1. One\n", **{**META, **metadata})


def test_crlf_normalizes_to_identical_corpus():
    source = "# БЛОК 1. One\n## 1.1. Text\n[ПРОВЕРИТЬ по источнику] X\n"
    assert build(source) == build(source.replace("\n", "\r\n"))


def test_modified_markdown_or_pdf_is_refused(tmp_path):
    changed = tmp_path / "source.md"
    changed.write_text(SOURCE.read_text(encoding="utf-8") + "\nExtra\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="source_hash_mismatch"):
        payload(source=changed)
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"not the source")
    with pytest.raises(CorpusError, match="pdf_hash_mismatch"):
        payload(pdf=pdf)


def test_deterministic_artifact_and_check_never_writes(tmp_path):
    expected, _ = payload()
    assert (DIRECTORY / "corpus.json").read_bytes() == expected
    def invoke(*args):
        return subprocess.run([sys.executable, "-X", "utf8", "scripts/build_kg_search_corpus.py", *args], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    target = tmp_path / "new" / "corpus.json"
    result = invoke("--check", "--output", str(target))
    assert result.returncode == 1 and not target.parent.exists()
    assert json.loads(result.stdout)["code"] == "output_missing"
    assert invoke("--output", str(target)).returncode == 0
    stamp = target.stat().st_mtime_ns
    assert invoke("--check", "--output", str(target)).returncode == 0
    assert invoke("--output", str(target)).returncode == 0
    assert target.read_bytes() == expected and target.stat().st_mtime_ns == stamp
    target.write_bytes(b"user changed content")
    assert invoke("--output", str(target)).returncode == 1
    assert target.read_bytes() == b"user changed content"


def test_original_pdf_hash_when_available():
    pdf = ROOT.parent / "Kyrgyzstan-visa-knowledge-base-v1.1.pdf"
    if not pdf.is_file():
        pytest.skip("original PDF outside repository")
    encoded, _ = payload(pdf=pdf)
    assert encoded == (DIRECTORY / "corpus.json").read_bytes()


def test_module_has_no_config_database_or_network_imports():
    code = "import sys; import app.knowledge.corpus; assert not any(n in sys.modules for n in ['app.config','sqlalchemy','httpx','requests','fitz'])"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
