# REVIEW: E6-22 — bounded current route adapter

- Task: `ai/tasks/2026-10-12-e6-22-approved-qualification.md`; independent risk requirements: `ai/reviews/2026-10-12-e6-22-pre-audit.md`.
- Reviewer: separate Codex agent `/root/calculation_review`; builder: `/root`.
- Risk/mode: CRITICAL / solo. Target: reviewed local read-only route candidate, **not full C05**.
- Independence: **INDEPENDENT**. First assessment without builder conclusions: **YES**. Inspected task/pre-audit and actual new policy, domain adapter, native route/template, adjacent condition evaluator, publication locks and individual-profile journal before receiving builder test results.
- Initial snapshot: `runs/e6-22-r1`, base `87ad9e759aae223258742d286310aba2155f112d`, 13-file manifest `snapshot.json`. Reviewer copy: `runs/e6-22-review-r1`; all 13 SHA-256 entries verified with LF normalization (four originals use CRLF). No local `.env` copied; only tracked `.env.example` is present.
- Runtime/source files remain read-only. Reviewer-only probes are under the copied snapshot's `tests/` directory.
- **Final verdict: APPROVE for the bounded local r6 adapter**, with the scope exclusions below. Final r6 manifest SHA-256: `de7168bfc3cd2bc642e7e0f977373e28b3fee23d714d3a9b8561998db84dff59`. Earlier rejected snapshots are retained as evidence, not approvals.

## Initial r1 findings

| Severity | Location | Trigger / consequence | Actual evidence | Correction required |
|---|---|---|---|---|
| P1 | `app/domain/approved_qualification.py:49`, catalog branch of `_policy_rules` | A legitimately imported, reviewed and published literal VF unit excludes CHN, but its catalog contains only an ordinary-document predicate. A matching explicit policy and CHN profile produce `KG.VF.TEST` / `NO_VISA`. Matching the catalog hash does not preserve the structured source country restriction. | `test_catalog_cannot_erase_source_restrictions[country_guard]` fails because `candidate` is non-null. No SQL corruption or caller-supplied policy was used. | Retain all source country/document restrictions in conditional mapping; refuse missing/contradictory guards. |
| P1 | Same catalog branch | Catalog `source_outcome` explicitly says `visa_type=TS`, while the literal VF unit and policy return `NO_VISA`. The outcome is not inspected. | `test_catalog_cannot_erase_source_restrictions[outcome]` fails with a `NO_VISA` candidate after normal import/review/publication. | Validate structured source/catalog outcome consistency and route product compatibility; refuse unsupported outcome semantics. |
| P1 | `app/domain/approved_qualification.py:56`, literal branch | A published VR unit with `scope=tourist_gcc_resident` and country CHN is accepted using only country/document predicates, without any residence evidence. It produces a TS candidate. | `test_country_only_policy_cannot_erase_gcc_residence_requirement` fails with non-null candidate; no catalog or residence facts present. | Support the complete scoped qualifier explicitly or reject scoped rules without a supported complete interpretation. Country membership alone is insufficient. |
| P2 | `app/admin/templates/kg_approved_qualification.html:8` and `:29` | All specific fallback/stop reasons are raw internal codes in collapsed details, and print hides the entire details element. Revoked source, interview reconciliation and passport expiry have the same generic visible fallback; printed review loses the reason. | Inspected template: report reasons and stop reasons appear only inside `<details>`, and print has `.kg-route details{display:none}`. | Show a short translated, concrete fallback/stop reason in the main content and print; keep diagnostic identifiers optional. |

All findings were sent to the builder promptly. Initial verdict: **FIX_REQUIRED**. This report does not approve r1. Corrected-snapshot verification follows below.

## Checks actually performed on r1

Windows/Python 3.12, env-free copied snapshot, synthetic SQLite; suites run sequentially. No live services, personal data, messages, source approval or production changes.

| Command from `runs/e6-22-review-r1` | Actual result | Meaning |
|---|---|---|
| `python -m pytest tests/test_route_independent_negatives.py -q --tb=short` | **3 FAILED**, 19.64 s | Three confirmed source-semantics defects above. Full connected normal import/review/publication/profile/route calls. |
| `python -m pytest tests/test_route_independent_controls.py -q --tb=short` | **3 passed**, 18.43 s | A genuinely started active individual interview blocks the route and questions; incomplete irrelevant foreign-document sets do not invent a requirement for a literal rule; native missing-policy fallback retains EN and no-eligibility notice. |

Each command reported one existing Starlette/httpx deprecation warning. No PG or browser evidence is claimed at this stage. Builder evidence is not included in these counts.

## Correction verification on r3/r4

The r2 correction introduced a separate ordinary-positive regression: the predicate validation loop overwrote the literal `countries` variable, so its final ordinary-document clause left an empty country list for the no-catalog comparison. The reviewer identified this in source inspection before running negative tests, avoiding a vacuous PASS caused by rejecting every candidate. The builder corrected the variable name in r3. The initial r1 snapshots/probes remain unchanged.

Final runtime inspected so far: frozen `runs/e6-22-r4`, copied to `runs/e6-22-review-r4`; 16 overlay hashes verified with LF normalization against base `87ad9e759aae223258742d286310aba2155f112d`. Runtime is identical to r3; r4 corrects test fixtures. Manifest SHA-256: `2d06a4d3b032f1b15c1d8e9d23394040080ca02ea3dd4dfa385378b68f4bb9be`.

| r1/r2 finding | r4 resolution | Reviewer verification |
|---|---|---|
| Catalog erases literal country guard | Literal source countries must exactly match an explicit policy country predicate in either branch. | Original connected wrong-country negative now passes alongside a normal positive candidate. |
| Catalog outcome ignored | Supported catalog outcome must exactly match structured source values. VF routes are limited to NO_VISA; VR routes to tourism/TS. | Original conflicting TS outcome negative now passes. Separate accepted catalog positive proves conditional candidates still work. |
| Unsupported GCC residence scope treated as country-only | Unsupported scopes, special regimes and all-others sources conservatively refuse executable selection. | Original fully published GCC-resident fixture without residence evidence now returns no candidate. |
| Hidden/unprintable raw-code reason | New RU/EN copy supplies concrete labels; `#kg-route-reasons` is in the main notice outside collapsed details. Print hides source identity only. | Actual template/copy inspection, plus native EN fallback control. No independent browser execution is claimed here. |
| r2 ordinary-positive regression | Loop uses `predicate_countries`, preserving the literal source list. | Positive control passes on r3 and r4. |

Checks independently executed:

- r3: positive no-writes/historical-replay control + original three semantic negatives + three additional controls: **7 passed**, 27.37 s.
- A proposed broad r3 compatibility run was interrupted immediately on the builder's fixture-correction notice. It had emitted four progress dots; **no completed suite result is claimed**.
- r4, `python -m pytest tests/test_approved_qualification.py::test_candidate_has_current_exact_identity_but_no_eligibility_or_writes tests/test_route_independent_negatives.py tests/test_route_independent_controls.py tests/test_route_independent_conditions.py -q --tb=short`: **11 passed**, 46.14 s.
- The four additional connected catalog cases distinguish incomplete empty document inventory, complete empty inventory, uncertain matching document and confirmed matching document. Expected results are respectively unknown, no matching regime, unknown and a bounded candidate. Visa requirement/selected regime remain null; eligibility/quoting remain false in all four.

Reviewer-only probe hashes in `runs/e6-22-review-r4/tests/`:

- `test_route_independent_negatives.py`: `2f74022ed86fb70bf5c44016cba2428c41e52174a684771d4bed14501e81edab`.
- `test_route_independent_controls.py`: `3c821fb4b852b11221297397abd1eb5e961c6c3e648a3a6975a224ffe931aaf5`.
- `test_route_independent_conditions.py`: `b1597178cdf91a3df89daa3cbf6892510531c1c7fc2a4525002c03af297f557a`.

## Independent PostgreSQL check on r5

Verified and copied frozen `runs/e6-22-r5` to `runs/e6-22-review-r5`. All 16 LF-normalized manifest entries match. The only manifest difference from r4 is `tests/browser_approved_qualification.py`; implementation/runtime is unchanged.

Executed `python -m pytest tests/test_approved_qualification_postgres.py -q --tb=short` with the existing private `FRUNZE_LOCAL_PG_CONNECTION` pointing only to the validated temporary loopback cluster: **5 passed**, 32.36 s, zero failures/skips; one existing Starlette/httpx warning.

These tests use actual migrated PostgreSQL and confirm the positive/no-writes/retained profile replay case, latest individual profile scope and three concurrent writers (profile revision, publication withdrawal, source review rejection). Each concurrent case checks a real `pg_stat_activity` lock wait while the reader holds its source/person snapshot, then verifies the first candidate and subsequent updated fallback. No credentials or connection-file contents were printed. The shared PG slot was released before other suites resumed.

## Final r6 correction and verdict

The separate auditor confirmed another conditional-source mismatch in r4/r5: a B-only visa-type predicate and matching B profile could emit a TS candidate. The reviewer then inspected the actual r6 correction and independently executed the adopted connected regression, including its coherent TS positive control. r6 requires `visa_type_is` to equal the allowed route product, and conservatively rejects `stay_within_months` because this slice has no approved date/counting bridge; a saved boolean cannot supply that calculation.

Final inspected/tested copy: `runs/e6-22-review-r6` from frozen `runs/e6-22-r6`, all 18 LF-normalized manifest entries verified against base `87ad9e759aae223258742d286310aba2155f112d`.

- Manifest SHA-256: `de7168bfc3cd2bc642e7e0f977373e28b3fee23d714d3a9b8561998db84dff59`.
- `app/domain/approved_qualification.py` SHA-256: `c1b10162ccface8b5245ee2e508747ec6732a8b9aa4314541aa058ef2b42a9c7`.
- Compared r5/r6 function ASTs directly: `_base` and the entire `propose_route` transaction/locking/read function are identical; only `_policy_rules` changes. Other implementation change is the translated explanation for the new refusal. Thus the independently executed five r5 PostgreSQL cases cover the unchanged r6 locking/read path; they are not mislabeled as an r6 execution.

Actual r6 command:

`python -m pytest tests/test_approved_qualification.py::test_candidate_has_current_exact_identity_but_no_eligibility_or_writes tests/test_route_independent_conditions.py tests/test_approved_qualification_conditions.py -q --tb=short`

Result: **8 passed**, 42.91 s, zero failures/skips, one existing Starlette/httpx warning. Covers genuine literal positive/no-write/retained replay, four independent document-completeness states, B/TS consistency and unchecked-month refusal. The latter checks include a permitted TS positive, so refusal tests cannot pass just because every route is disabled.

Also visually inspected the actual builder-generated r5 `candidate-390-dark.png` and `print-fallback.png` under `runs/e6-22-r5/runs/approved-route-browser/`. The mobile RU candidate is readable with the unresolved eligibility notice above it; the EN printed withdrawal fallback retains its concrete source-unavailability reason. This is independent inspection of rendered artifacts, **not a claim that the reviewer executed the browser harness**. Template is unchanged in r6, and the new refusal uses its existing visible reason list.

### Final acceptance coverage

| Bounded acceptance | Result | Reviewer evidence and limit |
|---|---|---|
| Separate source-bound executable mapping; complete competing regime set; consistent source predicates/outcomes/product | PASS | Actual code inspection and connected source-semantic negatives/positive controls, including the final B/TS correction. Unsupported special/all-others/GCC/month semantics fail closed. |
| Current exact individual profile, scope, stop and interview boundary | PASS | Current/sibling/stale scope checks in actual PG; active interview control; exact profile/policy/source identities in genuine positive; inspection of current-day/expiry checks. No reconciliation bridge is claimed. |
| Coherent current source/profile under concurrent changes | PASS | Five actual r5 PG checks, mapped by unchanged r6 `propose_route` AST. Real lock waits and subsequent changed fallback observed. |
| Read-only candidate, no eligibility/visa/day assertions; retained profile replay | PASS | Actual SQL-statement capture and positive replay control on r6; null decision/date fields and false quoting/eligibility checks in all independent conditional cases. |
| Native reason visibility and print | PASS within reviewed artifact scope | Inspected actual mobile/print renders and unchanged template; independently executed EN fallback control. Browser execution and broader compatibility remain separately recorded builder evidence. |
| Full C05, individual history/calculation/registration bridge, legal/source/pilot acceptance | N/A for this bounded slice | Explicitly incomplete/outside this approval; no technical points or human decisions are granted by this review. |

**APPROVE** the bounded local r6 route adapter. All confirmed review findings have corrections and relevant evidence; no confirmed blocking defect remains in this scope. This satisfies the independent-review component only. The separate critical final audit and parent task completion evidence remain separate requirements. No full repository, production or customer-delivery readiness is asserted.

## Scope retained throughout review

The reviewed design may only expose a possible route for specialist review. Individual stay allowance, registration, personal eligibility, visa requirement and exact deadlines/days remain unasserted. Real configuration defaults empty. Presence of an individual interview blocks the adapter until explicit reconciliation is implemented. This bounded slice cannot earn full C05 completion, approve actual law/policies, or authorize a pilot/release. Independent critical final audit remains separate from this review.
