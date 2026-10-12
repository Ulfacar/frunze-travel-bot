# E6-29B — separate final audit of current-stay checks

Auditor `/root/e622_audit`, separate from builder `/root` and reviewer
`/root/calculation_review`. 2026-10-12, CRITICAL / solo. Reviewed local
read-only component; **Final GO / DONE for exact R6 in the agreed reviewed local
E6-29B component scope.** Separate independent review is APPROVE, corrective
checks and final compatibility evidence pass. Full H02 remains UNKNOWN.

## Requirement and exact candidate

Read `ai/tasks/2026-10-12-e6-29b-current-stay-stops.md` and the parent
`ai/reviews/2026-10-12-e6-29-pre-audit.md` current-stay addendum before actual
code and reviewer conclusions. The component evaluates only actual permission
expiry, strict fewer than five separately approved working days, and observed
visa-free window headroom <=3. Supplied-source STOP03/04/12 meanings and typed
interview/history semantics were inspected. Planned exit, visa validity,
registration expiry, projected exit-day arithmetic and historical overstay flags
are not substituted for today's actual permission end or observed headroom.

Final candidate `runs/e6-29b-r6`, base
`3efc7cc2cdb6f947c3588980ca02dc4a1a74536b`. **13/13 normalized-LF overlay hashes
verified; eight scoped root runtime/test identities match**. Raw manifest
SHA-256 `8e6a55e5da5ce78c7de7091004d615c6fb69a2351dd31275ec61f47ddbd8e2b4`.
Four runtime and four test files are in scope. The other overlays are parent
pre-audit documentation, three unrelated UI files and byte-identical prior
0036 migration; this component introduces no migration or native UI.
R3→R4 runtime is identical. R4→R5 changes only `current_stay_stops.py` to fix
the early non-trigger/source gap below. R5→R6 runtime changes only the shared
manual-guard validator, with a corresponding test and parent design-document
update. The current-stay service itself remains byte-identical to R5.

Own env-free archives are `runs/e6-29b-audit-r4`, `runs/e6-29b-audit-r5` and
`runs/e6-29b-audit-r6`,
reconstructed from the base plus verified overlays, with own probes only.
R4 raw manifest SHA-256
`06b79ddcb272b2642affb197c326e1ae4f7cbe1cf120c9078ec75bfb6846ae98`.
R5 raw manifest is `fca5687e9d8207f7eb93df1ad4e493a58128cdb5c0020a14eb6757199152a04a`.
Exact earlier identities/executions are in `runs/e6-29b-audit-r5/runs/identities-r5.json`;
final scoped identities are in `runs/e6-29b-audit-r6/runs/final-identities-r6.json`.

## Confirmed audit finding and retained failure

**R4 FIX_REQUIRED: the abroad early return bypassed current source authority.**
The service required a source-bound policy and exact current profile, but
returned all three `not_triggered/currently_abroad` checks before checking the
active publication, profile/source version, authority source hashes or current
STOP availability. A normal, coherent abroad profile/history/attestation first
passes; withdrawing the actual publication afterward still returned
`requires_specialist=False`, with no source pin in the result. This violates the
explicit dependency contract even though an abroad applicability result itself
is not permission to stay.

The auditor identified this in source and independently reproduced it on actual
PostgreSQL. The reviewer independently flagged the same source concern, without
claiming the runtime reproduction. Parent accepted the finding. R5 moves the
abroad result after current active-version/hash/parameter and STOP runtime
validation. Each unavailable STOP is now unknown even on abroad/non-VF
applicability. It does not require irrelevant calendar or VF-regime calculations
merely to establish the independently attested non-applicability.

The same original connected PostgreSQL repro now PASSes. The original R4 XML
remains at `runs/e6-29b-audit-r4/runs/e629b-audit-r4.xml`.

Separate earlier R2 findings remain visible in the independent review: a visa
branch ignored changed/withdrawn current history or passport conflict, and
current typed interview D1/D2 history could contradict the journal unnoticed.
R3 adds an exact nullable history pin and current validation on all applicable
branches, and explicitly refuses unreconciled D1/D2 history instead of ignoring
it. Known historical `violations.overstay` is not today's actual expiry flag;
the catalog asks whether there have been previous overstays.

**Late R5 FIX_REQUIRED: unsupported narrowing of a literal manual regime.**
The parent raised the shared validator's acceptance of additional predicates.
The actual current source has disjoint executable and noncatalog manual country
sets, so this initially did not show a current-source positive bypass. That is
not a proof for the supported versioned-source contract. The reviewer then
normally imported/reviewed/published a separate synthetic source with RUS added
to the literal manual SIMPLIFIED_ALL country list. The correct baseline sees a
competing manual rule; adding an unsupported USA-residence condition only to
the interpretation hid that rule and produced non-triggering VF headroom.
The reviewer's original **1 FAIL/21.91s** is retained in
`runs/e6-29b-review-r5/review-manual.xml`.

R6 restricts noncatalog literal-country manual guards to the exact source
country predicate and optional ordinary-document predicate. Catalog manual
conditions still require exact equality. Unsupported extra residence or
nonordinary-document narrowing is rejected. The reviewer's original normal-flow
repro and auditor expanded actual-PG control pass. This is a real shared-validator
hardening in addition to extraction; it is not described as merely mechanical.

## Source-first assessment of corrected behavior

- **Authority/facts:** separate immutable server policy and fact schemas pin
  exact person/profile/history/interview and source interpretation. Actual
  permission-end semantics are explicit operator attestation, not government
  verification. Inputs cannot assert selected regime, safety, remainder or an
  exclusion of all other regimes. Supported document-inventory claims are
  narrowly whitelisted; absent/incomplete facts do not become complete-empty.
- **Current person and contradictions:** latest profile must be confirmed today;
  current individual history is validated even for visa/abroad paths. Existing
  history must match passport, basis, entry and location; missing history with an
  explicit null pin may support an independent visa date but never VF counting.
  A new journal invalidates that null pin. Current interview head/profile pins,
  collection block and supported overlapping facts are checked. Supplied D1/D2
  rows/totals remain unknown pending interpretation rather than being discarded.
- **One coherent read:** case → applicant → knowledge-set locks precede one
  current clock sample; same-session history and publication readers consume
  that instant. Composition ownership/outer route lock order is documented.
  No nested public transaction, persisted result, receipt mutation or provider
  call is introduced. Returned hashes describe this evaluation, not durable
  approval across later mutations.
- **Complete regime authority:** all current source VF/VR/SP IDs must be present
  in guard and qualification policies with exact hashes. Catalog/manual country
  conditions, explicit GENERAL partition and supported executable predicates
  are retained. Matched manual/unknown/multiple regimes refuse VF arithmetic.
  A definitively false conjunct may exclude a guard despite an irrelevant
  unknown; no invented fact is required. Relevant unknowns still refuse.
- **Calendar:** full immutable content hash, complete draft calendar data,
  authority dates, explicit endpoint convention and strict five-day threshold.
  Each inspected date must be covered by calendar authority. At most366 dates
  are scanned. A proven lower bound of five is labeled nonexact unless the
  actual interval was fully checked; missing/provisional years never default to
  guessed weekdays. Actual expiry today and yesterday remain distinct.
- **Observed VF headroom:** current complete same-passport confirmed history,
  exactly one matching open stay, no overlap and exact separately authorized
  counting-source values are required. WINDOW_ANCHOR is a strict one-element
  list under the retained source schema. The helper subtracts observed
  `reported_history_days`, not hypothetical `scenario_headroom`. Both counting
  flags are source-bound; old arithmetic stays review-only and unapproved.
- **Per-check result:** known expired/calendar findings survive independent VF
  authority uncertainty. Non-VF/abroad applicability does not imply eligibility.
  Output stays `current_stay_stops_only`, `permission_to_remain=None`, no quote,
  delivery `not_sent`, no product and no generic permission to continue. Other
  interview/legal stops remain the future consumer's separate responsibility.

## Auditor's own PostgreSQL execution

Serial commands in each own archive, using only the existing guarded
`FRUNZE_LOCAL_PG_CONNECTION` fixture and disposable synthetic loopback databases:

```text
python -m pytest tests/test_auditor_current_stay.py -q --tb=short --junitxml=runs/e629b-audit-r4.xml --basetemp=C:/Users/alanb/AppData/Local/Temp/e629b-audit-r4
python -m pytest tests/test_auditor_current_stay.py -q --tb=short --junitxml=runs/e629b-audit-r5.xml --basetemp=C:/Users/alanb/AppData/Local/Temp/e629b-audit-r5
```

R4: **1 PASS /2 FAIL,106.32s**, zero errors/skips. One failure is the confirmed
source bypass above. The other is an auditor oracle mistake: missing foreign-visa
inventory for RUS was incorrectly expected to block when the CHN/IND-only
guard is already definitively false. This is explicitly allowed tri-state
conjunction behavior, not a runtime defect. Original test/XML are preserved.

R5: **3 PASS,102.87s**, exit0, zero failures/errors/skips, one existing dependency
deprecation warning. The corrected oracle keeps that irrelevant-unknown case as
a positive control and adds relevant unknown residence inventory. Final JUnit
SHA-256 `e02190bb1f0e5eb451da66aada3a6e771d4f12ae9f08ec3417d5bb5afd97c8f9`.
The three independently executed scenarios establish:

1. Original abroad positive followed by actual publication withdrawal now becomes
   unknown/specialist; no stale early non-trigger survives.
2. Changed current source hash, regime hash, applicable GENERAL partition and
   relevant unknown residence inventory prevent VF arithmetic. A known expired
   actual permission remains triggered where only the VF dependency is unknown.
   Irrelevant CHN/IND foreign-visa uncertainty for RUS does not invent a conflict.
   Restoring original authority reproduces the exact baseline evaluation.
3. Raw corruption of actual personal-history, profile and source bundle hashes
   each raises `EntryStorageInvalid`. Restoring each original hash restores the
   exact result. SQL observation of the successful evaluation confirms no
   INSERT/UPDATE/DELETE/DDL.

No active auditor test process remains; PG slot released. No private environment,
real personal record, live source activation, external service or message was used.

After the late shared-validator fix, a separate exact R6 actual-PG command ran:

```text
python -m pytest tests/test_auditor_manual_collision.py -q --tb=short --junitxml=runs/e629b-audit-r6.xml --basetemp=C:/Users/alanb/AppData/Local/Temp/e629b-audit-r6
```

**1 PASS/37.82s**, exit0, zero failures/errors/skips, one dependency warning.
JUnit SHA-256 `5dc28ef955b5eb07ec00e17d5667bc92e5e28a2f527e8906bf1c77c22a9cab79`.
This independently authored probe uses the reviewer's legitimate separately
imported source-variant fixture mechanism, with additional allowed original,
country-only and reordered ordinary guards and rejected residence/nonordinary
guards. All retain or refuse the competing manual regime without arithmetic or
permission. The original finding belongs to the reviewer. Earlier three R5
actual-PG controls map to the unchanged service and unchanged applicable guard
paths; no claim of a single combined four-test rerun is made. PG is released.

## Compatibility and separate evidence

Independent normalized-byte comparison confirms unchanged connected assessment,
personal-history and interview journals, publication service, stay arithmetic/
schema, WorkCalendars and interview reducer. Prior migration0036 is unchanged.
The assessment helper changes only `validate_authority` to call extracted
`validate_regimes`; its other pre-existing functions' complete ASTs are unchanged.
Added regime-set/hash checks duplicate prerequisites already checked by old
assessment authority. R6 additionally rejects unsupported narrowing of literal
manual rules in the shared validator, as explicitly recorded above. This affects
fresh evaluation only; retained arithmetic/journal formats are unchanged.

Builder R3 actual PG artifact
`runs/e6-29b-r3/runs/e629b-r3-pg.xml` independently parsed: **5 PASS/127.25s**,
zero failures/errors/skips, SHA-256
`290c6645bb01b8c0cd7c6b0ce3b8ba84e3dfce32d9d2bfad93940582ec24e2d6`.
Source inspection confirms real `pg_stat_activity` lock waits: held read blocks
profile/history/publication writers; a committed profile correction before reader
acquisition is observed; crossing local midnight during actual case-lock wait
uses the new day. R5 changes only the later source/non-applicability branch;
the lock and clock path is unchanged. This is mapped builder evidence, not an
auditor rerun of those concurrency cases.

Builder final R4 `runs/e6-29b-r4/runs/e629b-r4-focused-compat.xml` independently
parsed: **43 PASS/635.047s**, zero failures/errors/skips, SHA-256
`f15b99b18b9584aad306472f6f9dd8ca2f0e45ba13e8424ccab8f821a9affb00`.
These are eight pure calendar checks,33 current-stay domain checks and two
connected-assessment extraction regressions. R5 unchanged paths map directly;
the changed early-source branch is covered by the original auditor repro and
reviewer's R5 controls. Builder final R5 source-delta XML adds **2 PASS/46.080s**
for the abroad fact path and independent visa fact with initially missing
history. The earlier R2 **38 PASS/501.947s** is historical, before the known
corrections; it is not final-runtime approval.

Reviewer own corrected evidence is **6 PASS/140.958s** on R3 and **2
PASS/47.796s** on R5: original four normal-flow failures now refused, refreshed
pin cannot hide a basis conflict, known expiry survives missing VF authority,
both source counting flags false produce observed headroom4 versus projected5,
wrong abroad source hash becomes unknown, and rejected STOP12 does not erase
known expiry. Reviewer R6 adds **2 PASS/47.02s**: the original normally imported
manual collision and a supported country-only guard positive on the unchanged
original source. These are separate reviewer executions, not auditor runs.

Builder exact R6 `runs/e6-29b-r6/runs/e629b-r6-guard-compat.xml`:
**3 PASS/96.637s**, zero failures/errors/skips; SHA-256
`63d582886260b8d5e986b2e603d131d38eae9940259ffd2a0379002bc6ed3d49`.
The new manual-guard negative loop and two old-assessment controls pass after
the shared validator hardening. The auditor independently parsed this final
artifact and rechecked all eight scoped root identities against R6.

All evidence is attributed to exact snapshots and is not summed into a
whole-repository pass count. Native/browser checks are N/A: this component adds
no UI or route.

## Completion boundary

The separate final review is **APPROVE** in
`ai/reviews/2026-10-12-e6-29b-current-stay-independent-review.md`, independently
read and normalized-LF hash-verified at
`40ff4c54d2dedca420555bff0af6fe4336718a846ecfa2ec81f5ec9a399140d9`.
No confirmed component defect or applicable evidence/review gate remains open.
**GO for the reviewed local E6-29B component.** H02 remains UNKNOWN regardless
of this component's completion: no incoming connection, normal typed conversation,
atomic use by a causal writer or current dialogue acceptance has been added here.
Actual source/calendar/counting/privacy/fact approval and production activation
remain outside scope. No criterion points or release are authorized by this audit.
