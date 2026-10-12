# E6-25 applications/documents — independent final audit

- Auditor: `/root/e622_audit`, separate from builder `/root` and reviewer `/root/calculation_review`.
- Date: 2026-10-12. CRITICAL / solo; target: reviewed local fixed E01/E02/E03/E05/E07/F01/F02/F03 behavior.
- Requirements read before conclusions: `ai/tasks/2026-10-12-e6-25-applications-documents-review.md`, `ai/reviews/2026-10-12-e6-25-pre-audit.md`, fixed criterion definitions and actual application/group, matrix, inventory/package, issued-document and process-evidence code.
- Initial frozen snapshot: `runs/e6-25-r1`, base `693d683b9a0adcb8f76d5551bf0f121ca6824fec`, **10/10** overlay hashes independently verified. Manifest raw SHA-256 `68b0b34758c88092cffe8415b1fd39bc4fb57f6beb7aeb4cccc4ab521c1e4ce1`.
- Own env-free copy: `runs/e6-25-audit-r1`. Only probes/artifacts in own copies and this report are written; application/source/config files remain read-only. No root `.env`, production, real personal records, messages or approval changes.
- Final verdict: **GO for the bounded reviewed local E01/E02/E03/E05/E07/F01/F02/F03 scope on frozen R3**, identified below. Initial **FIX_REQUIRED on R1** and original failure remain recorded; this verdict is based on corrected-source inspection, independent upgrade/PostgreSQL checks and the separate reviewer's final APPROVE, not previous scope approvals.

## Initial confirmed current-consumer gap — resolved in R3

**P1 — process evidence can still accept a package whose stale passport checks the corrected package reader refuses.**

Locations: `app/domain/entry_process_evidence.py`, `Evidence.package`, calls to `summarize` and `packages.effective_acceptance` omit the new passport date boundary. A validated legacy package has a Sep 3 passport-change fact, later-recorded document checks fact-dated Sep 2 and a retained old approval. `read_document_package(... policy=...)` correctly returns current acceptance false under R1. The process adapter evaluates the same package as `documents_current=True`, reason `approved_current_metadata`, with a legitimate package-event pin.

Actual own probe uses real immutable package writes and actual `Sources`/`Evidence` in a scoped SQLAlchemy transaction. It emulates pre-guard admission by disabling only the new boundary during creation; it does not modify stored rows or hashes. This is not yet an actual archived-runtime upgrade check, which remains a separate final requirement.

Command from `runs/e6-25-audit-r1`:

```text
python -m pytest tests/test_auditor_process_passport_date.py -q --tb=short --basetemp=C:/Users/alanb/AppData/Local/Temp/e625-audit-process-r1 --junitxml=runs/e625-audit-process-r1.xml
```

Result: **1 FAILED**, one dependency deprecation warning, **24.78 s**. Assertion expected process `value=False`, received `True`. Parent and separate reviewer were informed promptly; the reviewer independently identified the same consumer omission.

Required correction: apply the same validated dated passport boundary to all current process consumers, including corrections-needed/completed facts. Preserve historical process observations and exact retry/replay semantics through an explicit evidence-rules version; do not silently recompute old evidence under changed rules. Inspect issued-document process consumers too: they read `issued._view` directly and must preserve old observation semantics while current readiness receives the corrected receipt status.

## Initial source-first assessment and required evidence

- Application identities are case/person scoped; predecessor chains verify the same person/procedure, attempt order and retryable terminal status. Correction events remain within an attempt. Reference claims and event chains are validated together; exact retries precede new CAS checks.
- Whole-case group overview locks the case and application parents, bounds the complete set before pagination, validates all people/events/references/chains, and refuses overflow/corruption rather than silently showing partial totals.
- Typed document matrix is hash-pinned and preserves required/conditional/recommended/dash cells, mixed alternatives, original source text/page and unresolved source labels. It grants no actual source approval.
- R1 inventory/package date checks derive a maximum passport-change date from validated history under existing case/application locks. Current summaries use a date overlay; stored reducers/hashes and old receipts remain unchanged. Full-package legacy import includes validated legacy passport history, and new acceptance checks consult the boundary. The missing process consumer above prevents a complete correction yet.
- Full-package passport-set comparison includes received/withdrawn passport versions. The historical v1 reducer remains distinct from current reducer behavior; its known identity gap is separately refused for current acceptance.
- Issued facts retain file/review/passport/delivery/receipt identities and actual travel observations without claiming travel permission. Separate reviewer has additionally reproduced a stale dated receipt after passport replacement/restoration; its final correction and exact evidence remain pending here.

Final frozen identity, original stale-date negatives and valid same/later controls, real old-handler receipt/replay compatibility, process evidence versioning, actual PostgreSQL serialization/recovery and the separate reviewer's final scoped verdict remain required. UI redesign, E6-24 source approval, full PDF/C05 and production are outside this audit.

## Final frozen identity and correction assessment

Final candidate: `runs/e6-25-r3`, base `693d683b9a0adcb8f76d5551bf0f121ca6824fec`. Own env-free execution copy: `runs/e6-25-audit-r3`. Manifest raw SHA-256: `4531fe3be91624460d4a01b235d913fecd9dd9b5e388edbefd882a65ee34b585`. All **13/13 overlay identities** were independently verified both before copying and at final closure, using the manifest's **LF-normalized file hashes**. Three files contain CRLF bytes; these are line-ending differences, not changed source. Neither snapshot contains a root `.env`. The manifest also includes unrelated UI/scoring files; their presence is recorded but this audit does not approve their changes.

Actual source was inspected before builder/reviewer conclusions. The source comparison covered the application/group services, typed matrix loader/catalog, inventory/full-package services and reducers, issued services/reducer, and process evidence. PDF-derived sections 5.2 (23-row/nine-product matrix, pages 36–37), passport checks (page 41), people/applications (page 63), issue/delivery/identity (page 68) and travel facts (page 69) were checked for the bounded meaning of the fixed criteria. No statement here independently validates current legal policy.

The three known defects are resolved:

1. **Inventory/full-package passport date:** dated review admission and effective currentness use the maximum passport-change boundary from validated history. This includes explicit changes, received passport versions and full-package passport withdrawal. Legacy inventory import preserves the boundary. A newly entered pre-change review is refused; same-day/later controls remain accepted. A previously stored stale approval remains readable but cannot provide current acceptance.
2. **Issued receipt currentness:** a late historical receipt remains a recorded fact. Its identity check is current only when its fact date reaches the current passport-check boundary. Replacement/restoration of a passport cannot rebind the old dated receipt. A later distinct valid proof can establish current receipt status. Stored snapshots and event/request hashes are not rewritten.
3. **Process consumer and replay:** fresh process evidence pins `observed.rules_version=2` and consumes the same validated passport-date boundary as package/issued readers. The package boundary includes pinned package and validated legacy-inventory prefixes. Historical unversioned observations replay v1 semantics; explicit unsupported values, booleans and an explicit attempted v1 downgrade are refused. Thus current package/process readiness agrees while old immutable process observations retain their original meaning.

No schema migration or stored journal rewrite is introduced. Transaction ownership, scoped parent locks, complete history validation and request-key/CAS behavior remain in the existing services. Current summary overlays may intentionally differ from the originally returned summary; immutable record IDs, snapshots, hashes and historical process interpretation remain preserved.

## Auditor's own final executions

These are separate auditor executions, not builder or reviewer results. The original R1 failure above remains in `runs/e6-25-audit-r1/runs/e625-audit-process-r1.xml` (SHA-256 `d184a7ac50ffd427bb9d042d2741a8cefe0fb29decf38706dc59841db4bea4e0`). Both final commands below ran in `runs/e6-25-audit-r3`, with synthetic data only and no production/network service access.

| Command | Actual result / artifact |
|---|---|
| `python -m pytest tests/test_auditor_process_passport_date.py tests/test_auditor_e625_upgrade.py -q --tb=short --basetemp=C:/Users/alanb/AppData/Local/Temp/e625-audit-r3-upgrade --junitxml=runs/e625-audit-r3-upgrade.xml` | **9 PASS**, 44.45s; zero failures/errors/skips. FK-enforced SQLite. JUnit SHA-256 `6a1c13092e7302103b0d9a46e46adea0f2dc017782ef9a479b3260e4e31afe8a`. |
| `python -m pytest tests/test_auditor_e625_postgres.py -q --tb=short --basetemp=C:/Users/alanb/AppData/Local/Temp/e625-audit-r3-postgres --junitxml=runs/e625-audit-r3-postgres.xml` | **9 PASS**, 80.63s; zero failures/errors/skips. Actual temporary PostgreSQL with migrated disposable databases. JUnit SHA-256 `4f17682ce6604b123852dd205ec8cb7a36a64b86458c119d1cfa079d9c7c45b8`. |

Each suite reported one existing dependency deprecation warning. PostgreSQL used only the existing opt-in `FRUNZE_LOCAL_PG_CONNECTION` fixture, which validates the temporary loopback target and reads its private connection file without printing credentials. Tests ran serially; no auditor test process remains active.

Own probes establish:

- The unchanged original R1 process-consumer reproduction now passes.
- Exact archived `693d683` full-package and issued service code creates old journals. Archived issued reducer/summarizer and process `Sources`/`Evidence` are loaded where needed; these are actual archived implementations, not hand-written substitutes. No stored row or hash is edited to construct compatibility evidence.
- Restoring corrected runtime preserves the old package snapshot/hash and its exact approval-retry receipt; current acceptance becomes false. Historical unversioned process packets remain identical. Fresh v2 packets are false and replay identically. Corrections-needed becomes true; a fresh stale approval is refused. Later dated checks and a new approval make current acceptance/process readiness true while the historical snapshot stays unchanged.
- An actual archived stale issued receipt preserves record ID, snapshot and hash on read/retry. Its current derived status is false, historical v1 receipt evidence stays true, and fresh v2 evidence is false. A later valid receipt makes current readiness true without changing the old snapshot.
- Archived process classes create persisted init/attestation/transition rows with unversioned evidence. Corrected runtime reads them, adds a new v2 attestation and replays both old and new revisions. Five malformed/unsupported version cases fail closed.
- PostgreSQL directly repeats four stale-date cases (inventory/full package × explicit change/received passport), legacy inventory import, dated passport withdrawal, and the three archived-handler/process upgrade scenarios. These nine cases are actual PG executions rather than extrapolation from SQLite.

Archived code under `runs/e6-25-audit-r3/tests/auditor_archived_693d/` is pinned to Git base `693d683b9a0adcb8f76d5551bf0f121ca6824fec`. Key LF SHA-256 values: package service `bbc6b72e761f677c33bc7e530bdfd468b3d369c1144616b633ea34b7a20fde4b`; issued service `e98a951bfe471ee063ed0ef46ba29730fb51161c95dd3c277aa4b4cd0674d1db`; issued rules `0e4ea7f03c4d204d0381836e148f65cdf592483645aca98458dc5d9c133d3f02`; process evidence `9ef4bb3c70d890253250638606c46c19e06e17c6dedcd02be6709e85e19dfb49`.

## Separate review and builder evidence

The separate reviewer `/root/calculation_review` issued **APPROVE** on the same R3 manifest in `ai/reviews/2026-10-12-applications-documents-independent-review.md`. Its conclusions were read after the auditor's own source assessment and executions. These are attributed evidence, not counted as auditor runs:

- Original `d847a254` domain/matrix suite: **124 PASS**; native HTTP suite: **83 PASS**.
- Original actual PG suite: **24 PASS / 2 harness FAIL**; the harness expected the wrong exception for an injected pre-insert failure. After correcting that expectation only, the two cases reran **2 PASS / 24 deselected**. This is not represented as a single green 26-test run. Coverage includes wrong scope/reference, CAS/retries, corruption/partial histories, six interrupted-write recovery cases and two observed `pg_stat_activity` lock waits for a passport writer versus a stale review/group reader.
- Final R3 original negative/positive/atomicity probes: **14 PASS**; strict observation-version controls plus five exact native Chromium flows: **11 PASS**; selected old/new compatibility checks: **7 PASS / 9 deselected**.

The auditor independently confirmed unchanged normalized application, application-rules, group-overview, matrix-loader/catalog and process-service/rules identities from the original review base to R3. The reviewer also mapped unchanged lock/history paths; the auditor directly exercised changed behavior on R3 PostgreSQL above. Original failures remain visible in the separate report and run folders.

The auditor separately inspected the reviewer's generated `runs/e6-25-review-r3/runs/e6-02b-inventory-browser/inventory-1365.png` and `runs/e6-25-review-r3/runs/e6-02c-issued-browser/issued-390.png`. Desktop/mobile text and visible control labels are readable; application/attempt context, currentness and the limits on acceptance/admission are visible. This is independent artifact inspection, **not an auditor browser execution**. Reviewer browser executions cover mobile, no-JavaScript desktop and print flows; UI redesign is outside this audit.

Builder final R3 evidence: `python -m pytest tests/test_document_passport_dates.py tests/test_entry_processes.py tests/test_entry_process_dependencies.py -q --tb=short --junitxml=runs/e625-r3.xml`, run from `runs/e6-25-r3`: **78 PASS**, 595.69s, one dependency warning, no skips/failures (16 dated-document checks and 62 connected-process checks). The auditor parsed the resulting JUnit at `runs/e6-25-r3/runs/e625-r3.xml` to confirm counts. This is builder execution evidence. Earlier R1/R2 approval-retry helper failures remain in their artifacts; the helper had recomputed state hash rather than resending the immutable old operation data, and R3 corrects that test setup.

## Fixed-criterion audit decision

| Criterion | Evidence and conclusion |
|---|---|
| E01 | **PASS**: inspected case/person/procedure/attempt identity checks; unchanged-source mapped domain/native/PG scope and linked-attempt controls from the independent reviewer. |
| E02 | **PASS**: immutable dated observations/reference uniqueness, within-attempt correction, CAS and exact retry; mapped recovery/scope checks plus own corrected-journal retry checks. |
| E03 | **PASS**: complete bounded group view validates all relevant applicants/histories before totals; reviewer domain/native/browser checks and actual coherent PG reader lock wait. |
| E05 | **PASS**: linked same-person/procedure refusal recovery retains the original attempt; independently reviewed unchanged implementation and selected actual PG controls. |
| E07 | **PASS on R3**: separately recorded issue/delivery/receipt/travel facts; stale receipt cannot refresh current passport identity; own actual archived read/retry, v1/v2 process replay and later-proof controls on SQLite and PG. |
| F01 | **PASS**: fixed source matrix preserves 23 rows, nine products and mixed/conditional/dash/source-review content; source-first inspection and mapped loader/native/browser checks. No source/legal approval inferred. |
| F02 | **PASS**: scoped immutable inventory/package metadata, history/revision validation and interrupted-write recovery; original independent domain/native/PG evidence plus own final current/historical checks. |
| F03 | **PASS on R3**: dated reviews respect changed/received/withdrawn passport boundaries; legacy import carries the boundary; stale saved approvals/receipts cannot feed current process readiness; old snapshot/retry/replay integrity preserved. Original failures retained and corrected behavior directly verified. |

No required independent-review/final-audit check remains UNKNOWN for this bounded local scope. **GO** means the reviewed local behavior above may be recorded as complete on these exact source identities. It does not certify the whole current working tree.

Full PDF/C05 completion, applicant eligibility, approval of source rules, real-document handling policy, owner/pilot acceptance, production release and any unrelated UI/E6-24/E6-26 work are **N/A to this scoped audit**, because this task explicitly excludes them. Their absence is not converted into broader approval. No deployment, source publication, real-data change, message or production authorization was performed or granted.
