# HANDOFF — E5-04A: PDF interview in CRM

- STATUS **PARTIALLY_READY**, CRITICAL / solo, target local implementation + review packet.
- Branch `fix/tours-search-quality`, base `46284fbaf05d4596b39d889961b01771ee661cfc`.
- Code `56f84e0db3ba5817f6fa4dad6030e891eaf2b0e4`; follow-up docs-only commit records final evidence. LF manifest `ai/reviews/2026-10-09-e5-04a-crm-snapshot.json`.
- Task `ai/tasks/2026-10-09-e5-04a-crm-qualification.md`; contract `docs/e5-04a-crm-qualification.md`.
- Builder Codex, separate SELF_REVIEW performed. Independent reviewer/final auditor UNKNOWN.

## Outcome

User asked to move original PDF implementation and CRM together, redesign later.
Existing visa service card now links to a manual KG interview: fill partial profile,
save via E5-03E, reload, RU/EN next questions, stops/source-conflict/history caveats,
previous read-only revision. Contact comes from the case; the questionnaire is shared
by that contact's visa services and is clearly labelled as a KG trip interview.
No new products/direction/applicants, full handoff, notifications or general redesign.

New `app/admin/kg_entry.py`, `kg_entry_form.py`, `templates/kg_entry.html`; integration
in router/workday/case panel. Existing full-admin boundary, session-bound CSRF/HMAC,
server-derived source/base/contact, bounded URL-encoded body, CAS and same-key recovery.
No DB migration this stage. `ADMIN_KG_ENTRY_ENABLED=false` + existing workday gate;
writing additionally requires service_cases_enabled. New env flag forwarded in Compose.

## Evidence

| Scenario | Environment / snapshot | Result / limitation |
|---|---|---|
| Related new HTTP + existing contracts/workday/storage | Synthetic SQLite, worktree | **187 passed / 1 warning / 156.80s**, before four extra tests |
| Final HTTP including XSS/history/as-of/flag and buffer bound | Synthetic SQLite, final new code | **42 passed / 1 warning / 57.58s** |
| Committed-copy HTTP | `56f84e0`, `runs/e5-04a-committed-copy-20261009/`, `python -m pytest tests/test_admin_kg_entry.py -q` | **42 passed / 1 warning / 53.86s**; `.env`/`prod.env` absent; 13/13 manifest hashes match Git blobs and copy |
| Browser | Isolated loopback FastAPI, Chromium, synthetic data | **1 passed / 3 deprecation warnings / 31.82s**; mobile390 with JS, desktop1365 without JS; native save/reload/history/focus, no overflow; screenshots inspected |
| Full suite | `python -m pytest tests -q` | **3318 passed / 1 failed / 8 skipped / 1 warning / 605.66s**; known tour-date baseline only; run started before buffer ordering refinement covered by final HTTP42 |
| Deployment traps | `python scripts/prod_traps_check.py --diff-base 46284fb --limit 1` | **FAIL**, 1 ERROR / 57 WARN, historical ANTHROPIC_API_KEY Compose-forwarding gap; new flag forwarded |
| Static compilation / whitespace | Local worktree | PASS, line-ending warnings only |
| Staged public-repository checks | Code commit index | PASS, whitespace check and 13/13 manifest hashes; credential-shaped literal scan found 0 matches (not a comprehensive secret audit) |
| Independent review/final audit/PG runtime | Not available/performed | UNKNOWN; SELF_REVIEW is not independent approval |
| CI/deploy/production acceptance | Local target only | N/A, no production release requested or executed |

First HTTP run had 37 passed / 1 failed: test counted global logout submit button
when checking old interview. Parser corrected to the actual kg-entry-form; old interview
was already read-only. No business expectation was weakened.
Final buffer check now refuses an over-limit chunk before copying it into the bytearray;
full run covered the earlier equivalent 413 behavior, separate final HTTP gate passed.

## Recovery and limits

POST conflict/validation/uncertain commit preserves values and signed key. If the error
page also cannot reload DB, it still offers retry using escaped submitted options;
next save re-verifies sources. It does not turn echoed data into approved knowledge.
Latest snapshot uses pinned sources; no UI for switching imported versions/history yet.
Per-contact storage is not per-application storage; do not present E6-01 as completed.
No ordinary manager access: that remains an explicit business/access decision.

Original PDF physical pages 29 (§3.4) and 88 (Б.4) were re-read. No legal rules were
published/changed. Source data/PDF are untouched. Historical PDF progress report E5-03E
remains a dated checkpoint; current map is `docs/e5-pdf-progress.md` (rough 70–80% remaining,
not a measured percentage). General redesign is deferred by user instruction.

Known tour-parser date test failure is the prior baseline (isolated ef77321 reproduced
on Oct9), outside this change; do not claim the whole suite or deployment gate is green.
Unrelated audio/zip/reports/temp were preserved. No production data or messages used.

## Resume

Independent read-only packet review first. Then complete interview/handoff and
Applicant/Application CRM work under defined manager scope; confirm owner decisions
on legal/source/calendar publication before client eligibility. Do not enable the flag
on production without the critical release gate. Existing CONTRACT-UI gates remain open.

Browser reproduction: `python -m pytest tests/browser_kg_entry.py -q -s`.
Screenshots in ignored `runs/e5-04a-crm-browser/`; test helper forbids outside network.
