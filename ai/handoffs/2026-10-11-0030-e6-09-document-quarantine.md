# HANDOFF — bounded document quarantine

- STATUS: DONE for reviewed local synthetic implementation; no release or whole-PDF completion claim.
- CLASS / MODE: CRITICAL / solo. Task `ai/tasks/2026-10-10-e6-09-document-quarantine.md`.
- Branch/code: `fix/tours-search-quality`, `4c570a3408d21d1749543c1144eabf4cdc6a20fa`, base `419fe40`.
- Completion target: reviewed local implementation with explicit default-empty policy.

## Outcome

Bounded native PDF/JPEG intake stores immutable bytes in the existing domain database, atomically with the exact package receipt. Named full-admin upload authority, storage choice, types, byte/count quotas, validity and privacy/retention evidence must be configured explicitly; no actual policy was configured. Streaming multipart uses bounded memory, no temporary files, content decoding, rendering, public URLs or download/release endpoint. Filenames are validated but not stored.

Quarantined fingerprints cannot be reviewed or accepted through another package, the legacy matrix or the issued-document workflow. Issued file and passport copies both invalidate effective verification/delivery/receipt readiness, including historical reads and exact retry responses; immutable snapshots and factual travel history remain unchanged. Missing binary/receipt pairs and rehashed version/timestamp mismatch fail closed. Retries bind the same request and bytes; before/after commit faults preserve atomicity and avoid duplicates. UI modules cold-import independently; one-page quarantine print has no blank trailing page.

## Verification

Windows Python3.12, env-free `runs/e6-09-local`, synthetic FK-enabled SQLite, Chromium. Final25 changed source/test files match workspace, archive and committed normalized blobs; `ai/reviews/2026-10-11-e6-09-reviewed-snapshot.json`. No env/client files copied.

1. Supporting broad regression before final import extraction/issued integration: `python -m pytest tests/test_quarantine_multipart.py tests/test_entry_quarantine.py tests/test_entry_quarantine_migration.py tests/test_admin_kg_document_quarantine.py tests/browser_kg_document_quarantine.py tests/test_entry_document_packages.py tests/test_entry_document_packages_migration.py tests/test_admin_kg_document_packages.py tests/browser_kg_document_packages.py tests/test_entry_documents.py tests/test_entry_documents_migration.py tests/test_admin_kg_document_inventory.py tests/test_service_cases.py tests/test_alembic_domain_migration.py -q --basetemp=runs/root-quarantine-final-tmp --junitxml=runs/quarantine-final.xml`: **218 PASS /2 PG SKIP /3 deprecation warnings /351.29s**. Do not label this run as all25 final files.
2. After import correction, unchanged final UI files: `python -m pytest tests/test_admin_kg_document_quarantine.py tests/test_admin_kg_document_packages.py tests/test_admin_kg_document_inventory.py tests/browser_kg_document_quarantine.py -q --basetemp=runs/root-import-final-tmp --junitxml=runs/quarantine-ui-final.xml`: **39 PASS /3 warnings /85.68s**.
3. Final issued integration and full quarantine domain: `python -m pytest tests/test_entry_quarantine.py tests/test_entry_issued.py tests/test_entry_issued_migration.py tests/test_admin_kg_issued.py tests/browser_kg_issued.py -q --basetemp=runs/root-issued-final-tmp --junitxml=runs/quarantine-issued-final.xml`: **68 PASS /3 warnings /106.92s**. Includes current/historical/retry file/passport denial and final native issued flow.
4. PASS: independent review APPROVE in `ai/reviews/2026-10-11-e6-09-independent-review.md`; independent pre/final audit GO for25-file local target in `ai/reviews/2026-10-11-e6-09-quarantine-audit.md`. Actual independent commands, original reproductions and limitations are recorded there. Four findings closed: global reuse, issued reuse, receipt version/time binding, missing binary half.
5. PASS: cold direct imports quarantine/package/inventory/main; whitespace; bounded credential-pattern scan; protocol structure. Mobile390/JS, desktop1365/no-JS, invalid-file error, lost acknowledgement, same-file retry without duplicate, disabled policy, keyboard focus and print are tested. Mobile/desktop/retry screenshots and final one-page quarantine PDF visually inspected in `runs/e6-09-local/runs/e6-09-quarantine-browser/`.

Repeated checks are not added into a unique-test total. Full suite was not rerun for this slice; earlier whole-suite date/traps failures remain visible. Additive0026 schema/model/FK/size/type and empty/populated/offline downgrade checks PASS; PostgreSQL DDL PASS, actual PostgreSQL/runtime recovery UNKNOWN. Docker Linux engine remains unavailable as recorded in E6-08. Real privacy/retention/source approval and production acceptance are UNKNOWN; production/real-file use is outside the completion target.

## Continuation

F06 adds2 technical points: **67→69/100**; fixed definitions/weights unchanged. Parent objective remains incomplete. Next E6-10 persistent procedural stages and distinct dependencies; prepared task `ai/tasks/2026-10-11-e6-10-procedural-stages.md`, pre-audit/design before implementation. Latest user instruction: local work until08:00 Asia/Almaty, no deploy, save and send final status only to user via existing server Telegram bot. See `ai/tasks/2026-10-11-overnight-local-pdf.md`. Preserve unrelated files. The authorized final Telegram status is the only exception to the existing no-message scope.

Updated five-page progress PDF: `docs/reports/frunze-pdf-progress-2026-10-11-document-quarantine.pdf`, SHA256 `3382bb3e154baa4114fa394431d755f29ccda3da4ef2c8fdf2f53304f1eed64b`. All five pages inspected, final first-page text inspected again after refinement;26 source headings and69/31 score retained. Historical reports unchanged.
