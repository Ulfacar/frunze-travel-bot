"""Deterministic draft RAG corpus; --check is read-only, no network/DB/LLM."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge.corpus import CorpusError, MAX_BYTES, RAG_BLOCKS, build_corpus, normalized_text

SOURCE = ROOT / "docs/kb-visa-inbound-v1.1-derived.md"
DIRECTORY = ROOT / "knowledge/kg_entry/search_v1_1"
LOCK = DIRECTORY / "source-lock.json"


def payload(source=SOURCE, lock_path=LOCK, pdf=None):
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    expected_keys = {"format", "kb_version", "rules_as_of", "source_document", "markdown_lf_sha256", "pdf_sha256", "rag_blocks", "split_after_chars"}
    if set(lock) != expected_keys or lock["format"] != "kg-entry-search-source/1" or lock["rag_blocks"] != list(RAG_BLOCKS):
        raise CorpusError("invalid_source_lock")
    with source.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CorpusError("source_too_large")
    content = normalized_text(raw.decode("utf-8"))
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != lock["markdown_lf_sha256"]:
        raise CorpusError("source_hash_mismatch")
    if pdf is not None:
        digest = hashlib.sha256()
        with pdf.open("rb") as stream:
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                if size > 128 * 1024 * 1024:
                    raise CorpusError("pdf_too_large")
                digest.update(chunk)
        if digest.hexdigest() != lock["pdf_sha256"]:
            raise CorpusError("pdf_hash_mismatch")
    corpus = build_corpus(content, version=lock["kb_version"], rules_as_of=lock["rules_as_of"],
                          source_document=lock["source_document"], pdf_sha256=lock["pdf_sha256"],
                          split_after_chars=lock["split_after_chars"])
    if corpus["audit"]["blocks"] != list(RAG_BLOCKS):
        raise CorpusError("incomplete_rag_scope")
    return (json.dumps(corpus, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"), corpus["audit"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DIRECTORY / "corpus.json")
    parser.add_argument("--pdf", type=Path, help="Optionally verify original PDF hash (not text accuracy)")
    args = parser.parse_args(argv)
    try:
        encoded, audit = payload(pdf=args.pdf)
        if args.output.is_symlink():
            raise CorpusError("output_symlink")
        if args.output.exists():
            if args.output.read_bytes() != encoded:
                raise CorpusError("output_differs")
        elif args.check:
            raise CorpusError("output_missing")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("xb") as stream:
                stream.write(encoded)
        print(json.dumps({"ok": True, "mode": "check" if args.check else "build", "audit": audit,
                          "corpus_sha256": hashlib.sha256(encoded).hexdigest(),
                          "pdf_hash_checked": args.pdf is not None, "publication_approved": False}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"ok": False, "code": exc.code if isinstance(exc, CorpusError) else "corpus_unavailable",
                          "line": exc.line if isinstance(exc, CorpusError) else None}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
