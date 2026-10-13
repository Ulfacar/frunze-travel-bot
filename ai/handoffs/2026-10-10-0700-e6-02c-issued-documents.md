# E6-02C — issued-document lifecycle

- Branch `fix/tours-search-quality`; implementation `6c4b58727349c79166a3eb833bdb93cf2d620b5d`.
- CRITICAL / solo / local target **PARTIALLY_READY**. Independent review/audit UNKNOWN; no production changes.
- Immutable issued-file versions, all12 PDF16.1 comparisons, correction evidence, passport binding epochs, three delivery channels, separate receipt and client identity confirmation, actual entry/exit evidence. New files/passports invalidate current checks; sending never implies receipt. No travel permission or service completion is inferred.
- Native application forms support history, safe uncertain-commit retries, mobile/no-JS/print. Additive `e6_issued_0019`; populated/offline downgrade refuses.
- Exact-commit archive `runs/e6-02c-issued-final`, no env files. Command: `python -m pytest tests/test_entry_issued.py tests/test_entry_issued_migration.py tests/test_admin_kg_issued.py tests/test_entry_documents.py tests/test_entry_documents_migration.py tests/test_admin_kg_document_inventory.py tests/test_entry_applications.py tests/test_entry_applications_migration.py tests/test_admin_kg_applications.py tests/test_alembic_domain_migration.py tests/test_service_cases.py tests/browser_kg_issued.py tests/browser_kg_document_inventory.py -q --tb=short -ra`.
- **PASS:193 passed /2 PostgreSQL skipped /3 deprecation warnings /229.96s**. PostgreSQL runtime/recovery UNKNOWN. SQLite real FK constraints and negative scope/approval references tested; PG DDL only.
- Snapshot manifest `ai/reviews/2026-10-10-e6-02c-issued-snapshot.json`:15 files Git/workspace/archive match after explicit CRLF→LF normalization; raw hashes retained. Mobile and both print pages inspected in worktree browser run; final browser flow rerun in exact archive.
- Review packet `ai/reviews/2026-10-10-e6-02c-issued-packet.md`. SELF_REVIEW is not independent approval. False-alarm correction cancellation is not implemented; replacement requires a new official file fingerprint.
- E07 technical acceptance evidenced (+2); fixed technical score44/100. Parent70-point goal remains active. Next: individual applicant profiles, never copying payer/family facts automatically.
