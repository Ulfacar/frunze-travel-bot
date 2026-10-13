# E6-22 bounded route — independent final audit

- Auditor: `/root/e622_audit`; separate from the builder and `/root/calculation_review`.
- Date: 2026-10-12. CRITICAL / solo. Target: reviewed local read-only candidate adapter.
- Requirements read first: `ai/tasks/2026-10-12-e6-22-approved-qualification.md` and `ai/reviews/2026-10-12-e6-22-pre-audit.md`. The agreed narrowed scope returns a possible route only; it must not close full C05.
- Initial actual-source assessment: frozen `runs/e6-22-r4`, base `87ad9e759aae223258742d286310aba2155f112d`, 16/16 overlay hashes independently verified. Manifest SHA-256 `2d06a4d3b032f1b15c1d8e9d23394040080ca02ea3dd4dfa385378b68f4bb9be`.
- Auditor copy: `runs/e6-22-audit-r4`, env-free; only auditor probes added under that copy's `tests/`. Shared source/config files were not edited.
- Independence: actual policy, domain adapter, native controller/copy/template, profile journal, condition evaluator and source schema inspected before reading the independent review's conclusions. No old PASS verdict was inherited.
- Final verdict: **GO for the bounded local R6 route adapter**, after the correction and independent checks below. Initial R4/R5 verdict was **FIX_REQUIRED**; its reproduced failure is retained. This is not approval of full C05, later working-tree edits, legal/source policy, production or customer delivery.

## Original confirmed finding — corrected in R6

**P1 — source predicate for one visa type can produce another product.**

Location: `_policy_rules` and candidate construction in `app/domain/approved_qualification.py`. A normally imported, reviewed and published `visa_required_regime` for CHN has `scope=all_types`, an executable catalog containing country CHN, ordinary document and `visa_type_is=B`, and outcome `gknb_approval=False`. The explicit source-bound policy repeats those exact predicates but maps tourism to TS. A complete current individual CHN profile with condition fact `requested_visa_type=B` produces a TS candidate. Thus the adapter evaluates the source for B and presents TS, without evidence that this rule applies to TS.

This is a candidate-semantics defect; the existing result still leaves `selected_regime`, `selected_product`, `visa_required` and personal eligibility unset. Those conservative fields do not make a contradictory candidate correct.

Required correction: bind any `visa_type_is` predicate to the emitted product, or conservatively reject that unsupported predicate/route combination. Preserve a coherent TS-only conditional positive case. No DB corruption, HTTP-supplied approval or source mutation was used in the reproduction.

Command actually run in `runs/e6-22-audit-r4`:

```text
python -m pytest tests/test_auditor_route_semantics.py -q --tb=short --basetemp=C:/Users/alanb/AppData/Local/Temp/e622-route-audit-semantic
```

Result: **1 FAILED, 1 PASSED**, 1 dependency deprecation warning, 14.87 s. The B-only conditional case fails because `candidate.product == 'TS'`; the coherent TS-only positive control passes. Probe: `runs/e6-22-audit-r4/tests/test_auditor_route_semantics.py`.

## Source assessment

- Candidate-only fields and specialist limitation are retained on every path; there are no source/profile/application writes or customer messages in the adapter.
- The policy is server-configured, immutable, empty by default, separately identified and bound to exact source/bundle/projection/catalog hashes and algorithm version.
- Every regime unit in the source must appear in the policy and be currently published/available. Unsupported special regimes, fallback country sets, scoped GCC residence rules, unresolved/mismatched outcomes and incomplete predicates are conservatively refused.
- Applicant scope and latest profile checks are separate from payer history. Same-day confirmation, future profile timestamp, passport expiry and source/policy coverage through planned exit are enforced. Legacy stored qualification algorithms remain unchanged.
- Lock order is case, individual applicant, knowledge set. Existing interviews are blocked pending reconciliation; no inferred interview facts or handoff resumption is performed.
- Full-admin route and feature gates, no query overrides, escaped native output and explicit uncertainty are present. Concrete translated fallback/stop reasons remain visible in ordinary output and print.

These are source inspection findings, not blanket execution PASS claims. The independent correction, PostgreSQL and artifact evidence follows. Full personal stay-history/allowance, registration, eligibility and actual source/business approvals remain outside this bounded slice; C05 must stay open.

## Final R6 identity and correction

Frozen `runs/e6-22-r6`, copied without local environment files to `runs/e6-22-audit-r6`, retains base `87ad9e759aae223258742d286310aba2155f112d`. All **18/18** LF-normalized overlay hashes independently match in both folders. Manifest raw SHA-256: `de7168bfc3cd2bc642e7e0f977373e28b3fee23d714d3a9b8561998db84dff59`.

- Domain adapter SHA-256: `c1b10162ccface8b5245ee2e508747ec6732a8b9aa4314541aa058ef2b42a9c7`.
- Policy SHA-256: `ee0f6b475ff112fd0f0c329577e47fd2382a1c7b154322bc107601a77573e5ed`.
- Native controller SHA-256: `42f1869cfc8e1aef740341104a0858ef05005cc6f82a4a3fbc71cc5f24726712`.
- Native template SHA-256: `a1078eaeda5832c0faf980f418db6309b11ca689920a0cba78fba6052443bc20`.

Actual R6 `_policy_rules` now requires each `visa_type_is` to agree with the permitted emitted product. A B-only predicate cannot emit TS; the coherent TS-only rule remains usable. It also refuses `stay_within_months`: this slice has no approved month-boundary/counting algorithm, so a saved boolean cannot authorize a month calculation. Unsupported predicates return a visible translated source-semantics reason. No final visa, entry, allowance or registration conclusion was added.

## Auditor checks actually executed

Environment: Windows/Python 3.12, env-free copied R6, synthetic SQLite and migrated disposable databases on the existing validated PostgreSQL loopback cluster at `127.0.0.1:55971`. Only the existing private local connection-file path was supplied through `FRUNZE_LOCAL_PG_CONNECTION`; its contents were not printed. No production environment, real personal records, network sources, source/config mutation or messages were used.

Command from `runs/e6-22-audit-r6`:

```text
python -m pytest tests/test_auditor_route_semantics.py tests/test_auditor_route_conditions_postgres.py tests/test_approved_qualification_postgres.py -q --tb=short --basetemp=C:/Users/alanb/AppData/Local/Temp/e622-route-audit-r6-final --junitxml=runs/auditor-route-r6.xml
```

Result: **10 PASS**, zero failures/errors/skips, one existing Starlette/httpx deprecation warning, **84.07 s**. The suite completed; no audit process remains.

| Executed cases | Evidence |
|---|---|
| Original unchanged auditor B/TS regression and positive control, SQLite | 2 PASS. The original B-only contradiction is refused; a coherent TS candidate still appears. |
| Connected B refusal, coherent TS control and unchecked-month refusal, actual PostgreSQL | 3 PASS. Normal import/review/publication/profile APIs and the permanent adopted regression fixture are used; no direct data corruption. |
| Positive candidate/no writes/retained historical replay and latest individual profile, actual PostgreSQL | 2 PASS. Conservative decision fields and person-scoped latest revision remain intact. |
| Profile revision, publication withdrawal and source-review rejection racing the reader, actual PostgreSQL | 3 PASS. Each observes an actual scoped `pg_stat_activity` Lock wait; the current reader finishes coherently, then the next read sees the changed state and refuses the old candidate. |

Own JUnit: `runs/e6-22-audit-r6/runs/auditor-route-r6.xml`, raw SHA-256 `12b77c67aff9600624b35e3cb113bd9a1604bf75e87a0416edafed09757b6cdb`.
Own unchanged probe: `tests/test_auditor_route_semantics.py`, SHA-256 `7749a8a4aeb873abcebeef5e59ec5aff4dd3e61dce9b864a86ce9870f412b1fd`; actual-PG wrapper: `tests/test_auditor_route_conditions_postgres.py`, SHA-256 `0b4084876404b4b16cca0ee25473f91625c12713446a1b4ec12a2b74262cc22b` (both inside the audit copy).

## Independent artifact inspection and separately attributed evidence

I visually inspected the builder-generated R5 `candidate-390-dark.png`, `fallback-1365-light.png`, `print-candidate.png` and `print-fallback.png` under `runs/e6-22-r5/runs/approved-route-browser`. Mobile Russian dark and desktop English light output have readable text, scope and reasons. Candidate and fallback printouts each fit one page; the caveat that personal history, allowance, registration, visa requirement and eligibility remain unresolved is visible. The withdrawn-publication fallback explicitly explains unavailable rules and shows no selected route. I additionally parsed both PDFs and confirmed their header, complete disclaimer, relevant reason and profile identity remain inside the page bounds. A transient partial tool rendering was rechecked against the complete PNG and PDF; no cropped artifact defect remained.

This is the auditor's inspection of actual artifacts, **not** an auditor browser run. Direct byte comparison confirms the R5/R6 native controller, template and browser harness are identical; R6 only adds the translated new refusal to existing reason rendering.

- Builder R5 combined browser/PG JUnit `runs/e6-22-r5/runs/e622-final-r5.xml` independently parsed: 7 tests, zero failures/errors/skips. Builder reported 50.65 s; its two browser executions and five PG executions are separate from the auditor's counts.
- Builder R6 scoped command: `python -m pytest tests/test_approved_qualification_conditions.py tests/test_approved_qualification_source_integrity.py tests/test_approved_qualification.py -q --tb=short --junitxml=runs/e622-semantics-r6.xml`; builder reported 35 PASS / 120.76 s. Artifact is `runs/e6-22-r6/runs/e622-semantics-r6.xml`; independently parsed before closing this report.
- Separate reviewer `/root/calculation_review` issued **APPROVE for bounded R6** in `ai/reviews/2026-10-12-e6-22-route-independent-review.md`: its own R6 8 PASS include B/TS/month correction, genuine positive and four document-completeness conditions; its earlier actual R5 PG 5 PASS map to unchanged transaction code. I read this after my actual-source assessment and checked the final identity. These are reviewer evidence, not my test executions.
- Initial R1 semantic failures, R2 positive regression and R4 auditor B/TS failure remain recorded in the two review reports. They are not silently converted into passing runs. R4's two browser harness failures were corrected in R5; the failed historical run is not final browser acceptance.

## Final coverage and limits

| Requirement | Verdict and basis |
|---|---|
| Explicit approved mapping bound to current exact source/projection/catalog; all competing rules represented and available | PASS within supported literal/catalog scope. Inspected validation plus original semantic regressions and coherent positive controls; omitted, unsupported, unknown, multiple, conflicting or unavailable routes refuse a candidate. |
| Source country, outcome and emitted-product semantics preserved | PASS. Separate review's country/outcome/GCC fixes plus the independently reproduced and corrected B/TS mismatch; unchecked month semantics now refuse. |
| Latest individual profile and coherent server-time/source view | PASS. Actual R6 PG latest-profile and three writer-lock cases; current-day, future timestamp and expiry/source-through-exit checks present in actual code. |
| Stops, missing facts, scope and interview boundary | PASS for this bounded adapter. Legacy review is rerun without changing its algorithm; stops suppress questions/candidate; existing interviews refuse pending explicit reconciliation. Source inspection and separate review controls support this boundary. |
| Native full-admin gates, no request policy override, escaped output, readable reason/print | PASS in reviewed scope. Actual controller/template inspection, scoped builder native checks and independent render/PDF inspection. |
| Read-only candidate with no visa/entry/remaining-day assertion or messages | PASS. Direct R6 positive/no-write/replay checks and actual return contract; selected regime/product and visa requirement remain null, eligibility/calculation/quoting false. |
| Full C05 personal history, allowance, registration and final qualification | OPEN, expressly outside bounded acceptance. No C05 completion points are earned by this adapter. |
| Real legal/source/catalog approval, pilot, production release or customer delivery | N/A for this local audit; no such authorization or approval is asserted. Configured policy defaults empty. |

**GO for the exact bounded R6 local change.** No confirmed blocking defect remains in that scope. Later unrelated E6-24 working-tree edits are not covered; this report does not approve the whole current working tree. Complete C05 and any release require their separate missing implementation, evidence and applicable authorization.
