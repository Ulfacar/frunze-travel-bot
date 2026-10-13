# E6-07B — publication gates and current runtime eligibility

- STATUS **PARTIALLY_READY**, CRITICAL / solo, local target. Branch `fix/tours-search-quality`; final code `6e6fd8ce6a102d519655aaef1953f009cc569726`, initial implementation `a3316af6ccd232c2a0fb8ddc5d6b71a053501251`.
- Task `ai/tasks/2026-10-10-e6-07b-knowledge-publication.md`. Default-deny publication policy; explicit review/approval/activation/rollback/withdrawal; immutable source/decision/manifest audit; one atomic active pointer/status projection. No actual source approval or production publication.
- Runtime returns literal approved values/provenance and refuses draft, unselected, expired, conflicted, changed-review or policy-revoked rules. A rejected/expired rule does not disable other eligible units. Old calculations replay unchanged; preview lists cases pinned to candidate and current active versions. No bot/client rollout.
- Native CRM preview/diff/readiness/current active eligibility/history, existing admin/OFF/workday/write gates, signed selection/manifest/policy/revision, uncertain-write exact retry even after failed reread; mobile390, no-JS desktop1365 and two-page print inspected.
- Source/policy owner and review periods remain unassigned; test approvals are synthetic. All208 actual source units remain unapproved. Additive0024, immutable scoped FK, populated/offline downgrade refusal. PostgreSQL runtime/recovery and independent review/final audit UNKNOWN.

## Evidence

Final exact env-free Git archive `runs/e6-07b-final-fixed`, Windows/Python3.12/synthetic SQLite:

`python -m pytest tests/test_knowledge_publication.py tests/test_admin_kg_knowledge_publication.py tests/test_knowledge_publication_migration.py tests/test_knowledge_decisions.py tests/test_knowledge_review.py tests/test_entry_storage.py tests/browser_kg_knowledge_publication.py -q --tb=short -ra`

**PASS:152 passed /3 deprecation warnings /132.17s**, no selected skips/failures. Raw local `final-check.log` is PowerShell UTF16. Snapshot `ai/reviews/2026-10-10-e6-07b-knowledge-publication-snapshot.json`:21 Git/workspace/archive files match after CRLF→LF normalization; raw hashes retained. Compilation/whitespace PASS.

Earlier exact archive `runs/e6-07b-final` at `a3316af6ccd232c2a0fb8ddc5d6b71a053501251`: publication/domain/HTTP/migration/browser plus knowledge import/review/projection, decisions, entry storage, domain schema/cases and progress checker: **323 PASS /2 PostgreSQL SKIP /3 warnings /192.27s**. Original-PDF cases passed in that run using the verified read-only source copy in ignored `runs/`. Cold imports publication/decisions/main PASS on that initial revision. Full suite was not rerun; prior tour-date baseline failure remains.

Separate SELF_REVIEW found a real expiry-boundary race after the broader run: eligibility and audit time used separate reads. New boundary test reproduces FAIL against a3316af; final code uses one operation instant and rejects clock rollback before append. Final152 includes boundary/clock, source expiry per rule, rollback, failure before commit, lost acknowledgement, duplicate/CAS/concurrent commands, changed evidence, old-case impact and immutable calculation replay. This is not independent approval.

## Continuation / preserved context

D04/D05 technical acceptance +4: **61/100** fixed points. Definitions/weights unchanged. User explicitly extended the target from70 to100 and requested saved context; original goal tool title still says70, but user100 scope supersedes it. Parent goal ACTIVE; never stop after this slice or relabel UNKNOWN as PASS.

Next `ai/tasks/2026-10-10-e6-08-complete-document-packages.md`: complete conditional supplements, immutable package review/revocation and CRM acceptance (F04/F05/F07); policy-gated file adapter F06 follows. Source PDF physical38/39/53/54 visually checked; images `runs/e6-08-source`. Existing matrix23×9 plus textual supplements is incomplete; detailed types also include TR/SW1/SW2/DN/J/M/I/R/T/A. Unknown conditions must block acceptance, alternatives remain alternatives. Do not invent DEC-06/07/11 or modify historical inventory definitions.

Commit/push are authorized; production/env/real personal data/messages are not. Preserve unrelated untracked artifacts. Review packet `ai/reviews/2026-10-10-e6-07b-knowledge-publication-packet.md`. Required independent review/final audit, PostgreSQL rehearsal and owner/source/pilot approval remain external completion gates; continue all independent implementation first.

Updated checkpoint PDF `docs/reports/frunze-pdf-progress-2026-10-10-engineering-progress.pdf`:5 pages visually inspected,26/26 headings present,61/100 points and target100. SHA7548688c52cbc3042d4c0b9c197ad2718d5d16651cdafd29e1a72230cef8d14d. Metadata `ai/reviews/2026-10-10-pdf-progress-report.json`.
