# E6-03A — SELF_REVIEW

- STANDARD / solo. Requirement: appendix A / fixed criterion I01; task
  `ai/tasks/2026-10-10-e6-03a-template-preview.md`.
- Same context performed a separate requirement/diff review; not independent audit.
- Scope: local literal typed previews, no message sending, publication or persistence.

## Review

All13 source templates and source statuses are preserved. Their original conditional
alternatives and RU/EN passages remain text. The generator pins the source-unit
snapshot; the runtime pins the resulting catalog. Unknown new tokens fail generation.
Each placeholder occurrence has its own ID; the two dates in A06 are independent.

Values are exact typed literals: dates, positive integers, explicit money/currency,
HTTPS references, source choices and bounded text. No evaluation, arithmetic,
format traversal, URL fetch or second interpolation. Jinja escapes displayed text.
Computed ambiguous source placeholders remain unresolved and cannot be filled.
Literal unapproved prices/deadlines remain visibly draft; even a fully filled
preview returns `send_allowed=False`. This does not implement approved customer replies.

Existing auth/KG gate precedes source access. Session/actor/template/catalog-bound
form signature; bounded strict body and fields; unknown/duplicate inputs refused.
No domain database access, new permission, file upload or message dispatch added.
Invalid forms retain typed user text without showing a false successful preview.

Native mobile390, desktop1365 without JavaScript, keyboard focus and print checked.
Review found a blank second print page from inherited body height; print CSS sets
document height to auto. Initial test failure used a nonexistent settings field;
corrected to the existing `service_cases_enabled` flag, no runtime gate weakened.

## Evidence / verdict

Initial pure23 PASS. Combined initial31 PASS /1 fixture failure; corrected fixture
plus two browser scenarios3 PASS. Final print rerun and exact-commit related checks
are recorded in the handoff, not assumed here.
SELF_REVIEW: **PASS for local STANDARD scope**, subject to recorded final checks.
Prior CRITICAL independent review/audit/PG remain UNKNOWN and are not closed here.
