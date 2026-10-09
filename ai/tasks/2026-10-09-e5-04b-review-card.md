# TASK: E5-04B — карточка анкеты для проверки специалистом

- Date: 2026-10-09; branch `fix/tours-search-quality`, base `ccc6e038b75448750f23681261e2b3a6d015881b`.
- CRITICAL / solo. Target: local implementation + review packet; builder Codex,
  independent reviewer and final auditor UNKNOWN.
- User: «дальше», continuing PDF requirements + CRM before redesign. Commits/push
  of the working branch authorized earlier; no deployment or external messages.

## Goal and scope

An administrator opens a readable, printable review card from a saved KG interview.
The URL pins the qualification revision and service case; the server verifies their
contact binding and source integrity. The card shows recorded answers, stop reasons,
missing information, RU/EN next questions and source references. Older revisions stay
readable with an explicit newer-version notice. Opening/printing does not record a
handoff or assert visa eligibility. Source: original PDF §3.4 / Б.4 / Б.6.

This is the preparation part of E5-04, not the completed manager workflow or E6-01.
Current full-admin + existing OFF-by-default flag remains. Manager access was asked
as an async business question; an unanswered question does not expand access.
No new personal-data fields, migrations, notification channels or assignment policy.

## Risk pre-audit

Use a domain operation, not only a hidden link: validate actor and ids before DB;
look up the visa case and contact on the server; load only the pinned qualification
through existing integrity verification. No query-string profile/source substitution.
GET is read-only, no task/qualification/event creation or latest-revision fallback.
HTML escaping, bounded identifiers, no-store responses, generic errors and logs.
Printed copy labels revision/as-of and unresolved checks; it is not a legal decision.
Rollback: remove the new link/route; existing qualification data stay unchanged.

## Acceptance

| ID | Scenario | Expected evidence |
|---|---|---|
| A1 | Save → review card → reload | Same pinned answers/version; human labels; no DB writes |
| A2 | Create newer revision, revisit old card | Old answers remain; latest link and warning |
| A3 | Anonymous/non-admin/foreign contact/non-visa/invalid id/flag OFF | Direct request denied; no data leakage |
| A4 | Corrupt snapshot/source or DB unavailable | Explicit failure, no successful partial card or private error payload |
| A5 | Partial / stop / unknown / false / in-KG / conditional facts | Honest gaps and source review; no fabricated recommendation, price or deadline |
| A6 | Mobile/desktop, no JS, print | Readable flow, labels/focus, no overflow, navigation omitted from print |

## Checks and completion

Focused HTTP/domain checks plus existing questionnaire/workday/storage tests; isolated
Chromium with synthetic data. Full regression only if change scope warrants it.
Separate SELF_REVIEW and packet/handoff/STATE required. CRITICAL independent gates
remain UNKNOWN if unavailable; report PARTIALLY_READY. CI/deployment/production
acceptance N/A for this local target. Known tour-date failure and deployment-traps
baseline are not evidence of a new regression and must not be presented as green.

## Results

- Related HTTP/domain/CRM suite: **170 passed / 1 warning / 151.45s**, before final
  specialist-facts display. Final new tests: **30 passed / 1 warning / 36.80s**.
- Final browser: **1 passed / 3 deprecation warnings / 20.95s**, mobile390 with JS,
  desktop1365 without JS, native flow, print/PDF, focus and no horizontal overflow.
- Demo PDF: two pages, both visually inspected; synthetic data only, ignored `runs/`.
- First 21 pass / 1 fail was a test selector matching CSS `#F1F5F9`; corrected to `(F1)`.
- SELF_REVIEW recorded in packet; independent review/final audit/PG UNKNOWN.
- Status PARTIALLY_READY. Manager-access decision pending, no permission expansion.
- Handoff `ai/handoffs/2026-10-09-2058-e5-04b-review-card.md`.
