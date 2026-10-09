"""Локальный поиск по зафиксированному черновику PDF; не источник готовых ответов."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from .corpus import MAX_BYTES, RAG_BLOCKS, build_corpus, normalized_text

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs/kb-visa-inbound-v1.1-derived.md"
DIRECTORY = ROOT / "knowledge/kg_entry/search_v1_1"
PDF_HASH = "141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2"
MARKDOWN_HASH = "642cecf9d2bcf0368da31f8fe30fe65a3c0c0dbef0039ac8c5e551340067a5f5"
TOKEN = re.compile(r"[a-zа-я0-9]+", re.I)
STOP = frozenset("а и в во на по с со из для при как что это ли или к от до о об не the a an of in to for and or is are how what".split())
ALIASES = {"visa": "виза", "passport": "паспорт", "registration": "регистрация", "family": "семья",
           "invitation": "приглашение", "documents": "документы", "work": "работа", "refund": "возврат",
           "refusal": "отказ", "overstay": "просрочка"}


class RetrievalError(ValueError):
    """Only fixed diagnostic codes, no query or source payload."""


def _tokens(text):
    # Six-letter Cyrillic prefixes give predictable inflection tolerance without
    # external morphology models. This is lexical ranking, not legal interpretation.
    result = []
    for word in TOKEN.findall(text.casefold().replace("ё", "е")):
        if word in STOP:
            continue
        word = ALIASES.get(word, word)
        result.append(word[:6] if len(word) > 6 and re.fullmatch("[а-я]+", word) else word)
    return result


def _bounded(path, maximum):
    with Path(path).open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise RetrievalError("knowledge_source_too_large")
    return raw


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RetrievalError("duplicate_source_key")
        result[key] = value
    return result


class _ReviewIndex:
    """Internal index; application callers must use the verified loader below."""
    def __init__(self, corpus):
        self._fragments = {f["id"]: deepcopy(f) for f in corpus["fragments"]}
        self._counts = {key: Counter(_tokens(f["text"])) for key, f in self._fragments.items()}
        self._titles = {key: set(_tokens(f["title"])) for key, f in self._fragments.items()}
        self._df = Counter(token for counts in self._counts.values() for token in counts)
        self._lengths = {key: sum(counts.values()) for key, counts in self._counts.items()}
        self._average = sum(sum(c.values()) for c in self._counts.values()) / max(len(self._counts), 1)
        self.source_hash = corpus["source_pdf_sha256"]
        self.version = corpus["kb_version"]

    def fragment(self, fragment_id):
        if not isinstance(fragment_id, str) or fragment_id not in self._fragments:
            raise RetrievalError("fragment_unavailable")
        # Returned objects never grant quoting permission, even to another caller.
        result = deepcopy(self._fragments[fragment_id])
        result.update(may_quote=False, publication_approved=False, status="draft")
        return result

    def search(self, query, *, limit=5, block=None):
        if (not isinstance(query, str) or len(query) > 200 or any(ord(c) < 32 for c in query)
                or type(limit) is not int or not 1 <= limit <= 10
                or block is not None and (type(block) is not int or block not in RAG_BLOCKS)):
            raise RetrievalError("invalid_search_query")
        terms = list(dict.fromkeys(_tokens(query)))
        if len(terms) > 40:
            raise RetrievalError("invalid_search_query")
        ranked = []
        total = len(self._fragments)
        for key, counts in self._counts.items():
            fragment = self._fragments[key]
            if block is not None and fragment["block"] != block:
                continue
            score = 0.0
            for term in terms:
                freq = counts.get(term, 0)
                if not freq:
                    continue
                idf = math.log(1 + (total - self._df[term] + .5) / (self._df[term] + .5))
                length = self._lengths[key] / max(self._average, 1)
                score += idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * length))
                if term in self._titles[key]:
                    score += 2 * idf
            if terms and query.strip().casefold() == key.casefold():
                score += 100
            if score > 0:
                ranked.append((round(score, 8), key))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return {"format": "kg-knowledge-search/1", "mode": "review_only", "kb_version": self.version,
                "source_pdf_sha256": self.source_hash, "may_quote": False, "publication_approved": False,
                "total_matches": len(ranked), "results": [dict(fragment=self.fragment(key), score=score)
                                                          for score, key in ranked[:limit]]}


def load_review_index(*, source=SOURCE, directory=DIRECTORY):
    """Paths are trusted application/test inputs, never HTTP query parameters."""
    try:
        lock = json.loads(_bounded(Path(directory) / "source-lock.json", 16_384), object_pairs_hook=_unique)
        expected_lock = {"format": "kg-entry-search-source/1", "kb_version": "1.1",
                         "rules_as_of": "2026-10-02", "source_document": "docs/kb-visa-inbound-v1.1-derived.md",
                         "markdown_lf_sha256": MARKDOWN_HASH, "pdf_sha256": PDF_HASH,
                         "rag_blocks": list(RAG_BLOCKS), "split_after_chars": 6000}
        if lock != expected_lock:
            raise RetrievalError("invalid_source_lock")
        content = normalized_text(_bounded(source, MAX_BYTES).decode("utf-8"))
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != lock["markdown_lf_sha256"]:
            raise RetrievalError("source_hash_mismatch")
        corpus = build_corpus(content, version=lock["kb_version"], rules_as_of=lock["rules_as_of"],
                              source_document=lock["source_document"], pdf_sha256=lock["pdf_sha256"],
                              split_after_chars=lock["split_after_chars"])
        expected = (json.dumps(corpus, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if _bounded(Path(directory) / "corpus.json", MAX_BYTES * 4).replace(b"\r\n", b"\n") != expected:
            raise RetrievalError("corpus_differs_from_source")
        if corpus["audit"]["blocks"] != list(RAG_BLOCKS):
            raise RetrievalError("incomplete_knowledge_scope")
        return _ReviewIndex(corpus)
    except RetrievalError:
        raise
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        raise RetrievalError("knowledge_source_unavailable") from None
