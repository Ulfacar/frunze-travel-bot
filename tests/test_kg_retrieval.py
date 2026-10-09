"""Real pinned source: ranking, corruption, provenance and read-only boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.knowledge.retrieval import DIRECTORY, SOURCE, RetrievalError, load_review_index


@pytest.fixture(scope="module")
def index():
    return load_review_index()


@pytest.mark.parametrize("query,expected", [
    ("семья", "KG.KB.10.0"), ("family", "KG.KB.10.0"),
    ("регистрация", "KG.KB.2.10"), ("просрочка", "KG.KB.8.3"),
    ("passport", "KG.KB.2.8"), ("KG.KB.1.2", "KG.KB.1.2"),
])
def test_reference_topics(index, query, expected):
    result = index.search(query)
    assert result["results"][0]["fragment"]["id"] == expected
    assert result["mode"] == "review_only" and not result["may_quote"] and not result["publication_approved"]
    assert result == index.search(query)


def test_whole_fragment_keeps_context_tables_labels_and_source(index):
    original = json.loads((DIRECTORY / "corpus.json").read_text(encoding="utf-8"))
    for fragment in original["fragments"]:
        assert index.fragment(fragment["id"]) == fragment
    table = index.fragment("KG.KB.1.2")
    assert table["oversized"] and "|" in table["text"] and table["pdf_pages_from_markers"]
    assert "verify" in table["labels"] and table["source_issue_refs"]
    table["text"] = "modified"
    table["labels"].clear()
    assert index.fragment(table["id"]) != table


def test_filters_limits_empty_and_unknown_id(index):
    assert all(hit["fragment"]["block"] == 10 for hit in index.search("семья", block=10)["results"])
    assert len(index.search("виза", limit=2)["results"]) == 2
    for query in ("", "  ", "и в на", "quuxxyz"):
        assert index.search(query)["results"] == []
    with pytest.raises(RetrievalError, match="^fragment_unavailable$"):
        index.fragment("../../.env")


@pytest.mark.parametrize("kwargs", [
    {"query": None}, {"query": "a" * 201}, {"query": "семья\nпаспорт"},
    {"query": "x", "limit": True}, {"query": "x", "limit": 0}, {"query": "x", "limit": 11},
    {"query": "x", "block": 3}, {"query": "x", "block": True},
    {"query": " ".join(str(i) for i in range(41))},
])
def test_bounded_queries(index, kwargs):
    with pytest.raises(RetrievalError, match="^invalid_search_query$"):
        index.search(**kwargs)


@pytest.fixture
def source_copy(tmp_path):
    source = tmp_path / "source.md"
    source.write_bytes(SOURCE.read_bytes())
    for name in ("source-lock.json", "corpus.json"):
        (tmp_path / name).write_bytes((DIRECTORY / name).read_bytes())
    return {"source": source, "directory": tmp_path}


def test_windows_checkout_line_endings(source_copy):
    for path in (source_copy["source"], source_copy["directory"] / "corpus.json"):
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert load_review_index(**source_copy).search("семья")["results"]


@pytest.mark.parametrize("mutation", ["text", "quote", "duplicate", "pages", "missing", "hash", "truncated"])
def test_corpus_corruption_is_rejected(source_copy, mutation):
    path = source_copy["directory"] / "corpus.json"
    corpus = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "text": corpus["fragments"][0]["text"] += "changed"
    if mutation == "quote": corpus["fragments"][0]["may_quote"] = True
    if mutation == "duplicate": corpus["fragments"].append(deepcopy(corpus["fragments"][0]))
    if mutation == "pages": corpus["fragments"][0]["pdf_pages_from_markers"] = [94]
    if mutation == "missing": corpus["fragments"].pop()
    if mutation == "hash": corpus["source_pdf_sha256"] = "0" * 64
    path.write_text("{" if mutation == "truncated" else json.dumps(corpus, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(RetrievalError, match="^corpus_differs_from_source$"):
        load_review_index(**source_copy)


@pytest.mark.parametrize("mutation", ["source", "lock", "duplicate_key", "missing_file", "too_large"])
def test_source_integrity_failures_are_fixed_codes(source_copy, mutation):
    path = source_copy["directory"] / "source-lock.json"
    expected = "invalid_source_lock"
    if mutation == "source":
        source_copy["source"].write_text("changed", encoding="utf-8")
        expected = "source_hash_mismatch"
    if mutation == "lock": path.write_text("{}", encoding="utf-8")
    if mutation == "duplicate_key":
        path.write_text('{"secret":1,"secret":2}', encoding="utf-8")
        expected = "duplicate_source_key"
    if mutation == "missing_file":
        source_copy["source"] = source_copy["directory"] / "missing"
        expected = "knowledge_source_unavailable"
    if mutation == "too_large":
        path.write_bytes(b"x" * 16_385)
        expected = "knowledge_source_too_large"
    with pytest.raises(RetrievalError, match="^" + expected + "$"):
        load_review_index(**source_copy)


def test_cli_from_other_directory(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/search_kg_knowledge.py"
    run = subprocess.run([sys.executable, "-X", "utf8", str(script), "family", "--limit", "1"], cwd=tmp_path,
                         capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["ok"] and report["results"][0]["fragment"]["id"] == "KG.KB.10.0"
    run = subprocess.run([sys.executable, str(script), "x", "--block", "3"], cwd=tmp_path,
                         capture_output=True, text=True, timeout=20)
    assert run.returncode == 1 and json.loads(run.stdout) == {"ok": False, "code": "invalid_search_query"}
