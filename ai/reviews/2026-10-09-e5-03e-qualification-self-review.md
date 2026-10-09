# SELF_REVIEW — E5-03E

- Codex, same builder/context; not independent review or final audit.
- Base 6d24227; target **2ebe7f4531e514f1cee06632efc37de8556f4c13**; CRITICAL / solo, **PARTIALLY_READY**.
- Separate pass: task A1–7, complete new files, shared diff, prior transaction/source helpers.

## Findings and decisions

1. Preserve the old read-only API: source loading extracted into caller-session helper,
   not a nested session during save. Public review has SQL SELECT only tests.
2. Full replacement is explicit, avoiding stale answers/derived stops when purpose or
   passport changes. Input/results are owned copies; frozen JSON guards nested writes.
3. Idempotency precedes CAS, allowing a retry of an old successful request after later
   revisions. Changed expected revision, KB, history or input under same key conflicts.
4. Same-contact constraints are enforced both in service reads and composite DB FK.
   Contact-level transaction lock + unique revision handle races; SQLite concurrency
   evidence is not presented as PostgreSQL proof.
5. Existing owned transaction helper handles rollback/retry/uncertain commit. New tests
   inject insert failure and a lost commit reply, then recover the same request without duplicate.
6. Read checks snapshot, adjacent previous link, pinned source context and accepted import.
   It does not recursively recompute every older revision. Replay fingerprints code/runtime
   and compares results; compatible old snapshots stay readable after runtime fingerprint drift.
7. Hashes detect accidental/unsynchronised privileged SQL changes, not forged data with
   all matching hashes. Explicitly documented; no new cryptographic guarantee is claimed.
8. New migration creates only one table, no seeds/backfills. Empty downgrade only; offline
   and populated downgrade refuse before any drop. No production migration was executed.
9. First test run: 102 passed / 1 failed due to test using `missing_fields` instead of the
   actual E5-03D `missing_facts` paths. Corrected test; business requirements unchanged.
10. Initial related suite: 233 passed / 2 skipped / 115.29s. Added eight targeted cases
    afterwards for actual DB scope, unknown/false and identifier validation; full suite includes them.

## Evidence and limits

Full final code suite: **3276 passed / 1 failed / 8 skipped / 1 warning / 490.61s**.
The only failure is the known date-dependent test_still_reads_a_plain_request; source
parser and test were not changed. New storage/migration tests (including the eight
additional cases) passed. Real source rehearsal also passed: three revisions, restart,
replay, preserved source conflict, all six input SHA/mtime unchanged.
Committed Git copy: **63 passed / 33.39s**, no .env/prod.env; 11/11 manifest hashes
match both Git blobs and the copy. Staged whitespace and credential-pattern checks PASS.
Final two-page PDF layout inspected; text checked after Unicode whitespace normalization. Independent reviewer,
auditor and PostgreSQL runtime remain UNKNOWN. No release certification; scoped manager
API/HTTP, full slots, handoff, retention and approved legal knowledge remain separate work.
PDF report is a project progress report, not a replacement for the source visa knowledge base.
