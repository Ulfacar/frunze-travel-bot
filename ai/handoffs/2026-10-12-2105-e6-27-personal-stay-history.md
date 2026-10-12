# HANDOFF: 2026-10-12-2105 — personal stay history

- STATUS: DONE for the bounded reviewed local E6-27 scope
- CLASS / MODE: CRITICAL / solo
- Task: `ai/tasks/2026-10-12-e6-27-personal-stay-history.md`
- Branch: `fix/tours-search-quality`; code `643c455bf690e14a4b8e48f557e3fe2f7541d77f`,
  exact16-file identity to frozen R6 over `803eacff8209007a66b6a877e37cfe845593ce00`
- Completion target: reviewed local change; no production migration/release.

## Outcome and scope

Added an immutable case/applicant stay journal and additive migration0035. Each
revision pins the precise personal profile and explicit opaque current passport
reference; no contact/payer history is inherited. Validate the entire bounded
chain and profile history under parent locks. Unknown completeness, unverified
visits, changed profile/passport and stale confirmation remain explicit findings.
The same-session reader supports future qualification without a second snapshot.
None of these states confers eligibility, quotation or entry permission.

Save limits reserve one terminal withdrawal:249 ordinary revisions plus a250th
withdrawal, with8192canonical bytes reserved inside the16MiB total. Exact old
commands recover their original immutable receipt before current CAS/profile/
clock/capacity checks. Conflicting keys, actors, dates and malformed histories
fail closed. Populated downgrade is refused; old data is not converted.

Native RU/EN forms modify one visit or history declaration at a time, preserving
all undisplayed rows up to1000. Signed actor/session/case/person/base/profile
metadata protects operations; passport choices only resolve references from the
pinned personal snapshot. Editing visits resets completeness. Historical views
are read-only. Uncertain saves and case-registry failures preserve the original
retry envelope. Existing feature/full-admin/workday/write gates remain intact.
Print explicitly states pagination and retains current-versus-historical status.

Scope is16 runtime/test files, listed in the final snapshot evidence. Preserved
uncommitted UI files `base.html`, `boards.html`, `test_admin_new_look.py` were
included in browser snapshots but are not part of the E6-27 commit. Unrelated
untracked artifacts remain untouched.

## Builder evidence

Environment: env-free Gitarchives, Python3.12, real FK-enforced synthetic SQLite,
explicit disposable PostgreSQL16.15 on localhost55971, actual Chromium. Every
snapshot has its base and LF-normalized overlay hashes in `snapshot.json`.

| Claim | Command / scenario | Snapshot | Result / limit |
|---|---|---|---|
| Domain/native/migration/PG | `python -m pytest tests/test_applicant_stay_history.py tests/test_admin_kg_applicant_history.py tests/test_applicant_stay_history_migration.py tests/test_applicant_stay_history_postgres.py -q --junitxml=runs/e627-r2.xml` with explicit local PG connection file | `runs/e6-27-r2` |46PASS88.76s, including11actualPG; later native/template deltas separately tested |
| Profile/schema/service-case compatibility | `python -m pytest tests/browser_kg_applicant_history.py tests/test_admin_kg_applicant_history.py tests/test_admin_kg_applicant_profiles.py tests/test_applicant_profiles.py tests/test_applicant_profiles_migration.py tests/test_alembic_domain_migration.py tests/test_service_cases.py -q --junitxml=runs/e627-native-related-r3.xml` |R3|112PASS2optionalPGSKIP122.88s; not a complete project suite |
| Controlled case503, preserved exact retry, native flow | `python -m pytest tests/test_admin_kg_applicant_history.py tests/browser_kg_applicant_history.py -q --junitxml=runs/e627-native-final-r4.xml` |R4|15PASS54.77s;13native+2legacy-theme browser |
| Final print/theme/accessibility | `python -m pytest tests/browser_kg_applicant_history.py -q --junitxml=runs/e627-theme-browser-r6.xml` |R6|2PASS23.33s:390pxRUdark and1365pxENlight/noJS; actual button text contrast>=4.5, no horizontal overflow, keyboard focus, exact historical facts, one-page PDFs visually inspected |
| Existing publication compatibility at new migration head | `python -m pytest tests/test_publication_recovery_postgres.py::test_terminal_251_and_metadata -q --junitxml=runs/e627-existing-publication-head-r6.xml` with explicit local PG connection file |R6|1actualPGPASS15.33s; old terminal publication recovery and entire model metadata parity |

The runs overlap and are not summed into a new full-suite count. Domain/model/
migration code is unchanged across R1–R6; final native handler is R4, final
template R6. Preserve original failures: R1 builder29PASS1FAIL was a test's
incorrect assumption about normalized visit order; corrected comparison verifies
every retained row by its stable ref. Independent original GET/POST unavailable
case probes exposed uncontrolled500; both corrected in R4. R5 final print tests
found a blank second page from inherited100% html/body height; R6 overrides print
height only. All original JUnit/output files remain available. Dependency
deprecation warnings are not suppressed.

## Review and remaining gates

Independent pre-audit: `ai/reviews/2026-10-12-e6-27-pre-audit.md`.
Implementation reviewer `/root/publication_review`: **APPROVE**,
`ai/reviews/2026-10-12-e6-27-independent-review.md`. Separate auditor
`/root/e622_audit`: **GO**, `ai/reviews/2026-10-12-e6-27-final-audit.md`.
Reviewer own6SQLite PASS with2original FAIL retained; own6actualPGPASS39.49s,
R5native16PASS with2printFAIL retained, exactR6browser2PASS21.32s. Auditor
own9PASS32.71s, including6actualPG and3SQLite/offline migration checks, plus
independent inspection of both final rendered PDFs and themed screenshots.
These are separate overlapping evidence sets, not one combined test run.

Exact16-file root/index/commit/frozen identities and raw JUnit hashes/counters:
`ai/reviews/2026-10-12-e6-27-snapshot-evidence.json`. Final manifest LF SHA256
`0476f1cdc4fa770a9199b153694ada30345ee0821537216b9b68c86057927fde`.

Fixed engineering score remains92/100,8remaining. E6-27 alone does not closeC05.
All208 actual source units remain unapproved draft evidence. No source/business
policy decision, real record, outbound send, deploy or remote push was performed.
Existing CRM demo8765 was not migrated or replaced; portable PG remains running
for further explicitly isolated tests.

## Next action

E6-27 required reports and scoped save are complete. E6-28 connected personal
qualification design/pre-audit is next:
`ai/tasks/2026-10-12-e6-28-connected-qualification.md`. FullC05/H02/J01/J02/J03/J05
remain open. Continue the parent task; this local slice is not project completion.
