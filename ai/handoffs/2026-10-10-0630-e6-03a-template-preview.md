# HANDOFF: E6-03A — typed source-template preview

- STATUS: **DONE for local STANDARD slice**; whole PDF/CRM70-point goal ACTIVE.
- CLASS / MODE: STANDARD / solo. Task `ai/tasks/2026-10-10-e6-03a-template-preview.md`.
- Branch `fix/tours-search-quality`; runtime `1d4a73cd09cf5124dcfa10492607df9a02724fbc`;
  smoke-route test follow-up `8e9ab4f`. Target: local checked change, no release.

## Outcome

All13 appendix-A messages are preserved with source/version/status, alternatives
and RU/EN text. Native CRM preview validates literal typed placeholders; each
occurrence is separate, preventing repeated dates from sharing one accidental
value. Values are never evaluated or reparsed, URLs never fetched, HTML escaped.
Missing/arithmetic placeholders remain visible. Unapproved source prices/deadlines
are not silently confirmed: every preview remains a draft with sending prohibited.
No persistence, actual message delivery, permissions or production changes.

## Evidence

Exact Git archive `runs/e6-03a-templates-final`, Windows/Python3.12, no env files:

`python -m pytest tests/test_kg_template_preview.py tests/test_admin_kg_templates.py tests/test_admin_kg_entry.py tests/test_admin_kg_documents.py tests/browser_kg_templates.py -q --tb=short`

**95 passed /3 dependency deprecation warnings /151.37s**. Covers real source
reproduction, every template/token, repeated dates, strict types and money/currency,
unresolved calculations, injection, no domain SQL, auth/flags/CSRF, invalid-form
retention, native mobile390/desktop1365 without JavaScript and print.
Snapshot `ai/reviews/2026-10-10-e6-03a-template-snapshot.json`: **12/12** changed files
match Git/workspace/archive with explicit CRLF/LF normalization and raw hashes.
Staged whitespace/token-shape scan and Python compilation PASS. Cold imports
`app.admin.kg_templates`, `app.admin.kg_entry`, `app.main` all exit0. One-page synthetic
print and mobile result inspected; a blank inherited second page was fixed.

Full-suite discovery at the prior document-inventory revision found two stale
legacy smoke lists (documents/processes were incorrectly expected to respond200
while OFF). Both failures reproduced at baseline `f0d9efa` (2 FAIL /17.23s).
Follow-up `8e9ab4f` adds the three explicit preview routes to those lists and a
separate strict OFF404/ON200 contract; old always-on page assertions unchanged.
Selected legacy full-admin/scoped checks plus four OFF/ON cases: **7 PASS /26.61s**
in isolated template worktree. This does not relabel the earlier full-suite result.

## Review and limits

Separate SELF_REVIEW `ai/reviews/2026-10-10-e6-03a-template-self-review.md` PASS for
local STANDARD target. Critical inventory/foundation independent review, audit
and PostgreSQL runtime remain UNKNOWN. No approved client advice or release claim.
I01 gains1 technical point: **42/100** fixed engineering criteria, not launch readiness.

Next: continue full conditional documents/package evidence and connected
application workflow/deadline tasks. E6-03 email import/outbox remains incomplete;
this supporting template slice does not close it. Preserve unrelated user files.
