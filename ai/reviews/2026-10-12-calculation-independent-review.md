# REVIEW: E6-23 — C01/C02/C03 arithmetic and immutable replay

- Task: `ai/tasks/2026-10-12-e6-23-calculation-review.md`.
- Risk/mode: CRITICAL / solo; target is reviewed local behavior.
- Base and tested runtime: `8062f80e89f60c9b42ec74457fd6275bd038e3bd`.
- Reviewer: separate Codex agent `/root/calculation_review`; builder/context owner: `/root`. The reviewer did not change implementation files.
- Independence: **INDEPENDENT**.
- First assessment without builder conclusions: **YES**. Read the task, fixed criterion definitions, source fragments and implementation before tests; did not read previous builder reports or review verdicts.
- Verdict: **APPROVE**, scoped to C01/C02/C03 below. Separate final critical audit remains required.

## Exact snapshot and source requirements

Created an env-free `git archive` of the base into `runs/calculation-independent-20261012/snapshot`. Only `.env.example` is present, with no local credentials or production configuration copied. Added two reviewer-only test files within that archive; runtime files remain the archived revision.

Archive `runs/calculation-independent-20261012/source.zip` SHA-256:
`115767ca1a1f7d8fa2a101e7846f4110844ee13c784facef448b46706b572d2b`.

Source inspected: `knowledge/kg_entry/search_v1_1/corpus.json`, fragments `KG.KB.2.1`, `KG.KB.2.9`, `KG.KB.13.2`, `KG.KB.13.3`; source PDF SHA-256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`. These require passport-specific context, all historical stay intervals, rolling windows, uncertainty at boundaries, distinct duration units and explicit holiday calendars. This review verifies software against the supplied source; it does not verify or approve the source as current law.

Inspected implementations and schemas: `app/knowledge/stay_days.py`, `stay_schema.py`, `deadlines.py`, `deadline_schema.py`, `work_calendar.py`, `storage_schema.py`; `app/domain/entry_storage.py`, `entry_calculations.py`; relevant model constraints/immutability hooks and calculation-storage migration tests. Also inspected the named-administrator authorization and isolated PostgreSQL fixture before use.

`git diff --exit-code 8062f80 --` over the eight arithmetic/schema/storage implementation files above returned success during review, confirming this scoped runtime is unchanged in the working repository. This is not a review of unrelated publication/UI changes.

## Findings

No confirmed defects or missing technical acceptance evidence within C01/C02/C03 after source inspection and the checks below. No implementation correction was necessary.

The following boundaries are deliberate and remain material:

- Computed results are proposed arithmetic scenarios. `publication_approved` and `may_quote` remain false; exact customer deadline/remaining-days fields remain null. Unknown history, passport continuity or legal basis remains visible.
- History/calculation storage is scoped to a contact. This review does not establish the individual applicant history and approved qualification bridge required by C05.
- Calendar completeness, counting policy and rule applicability are input/source responsibilities. Tests use synthetic calendars and proposed counting policies; no real policy or holiday approval was granted.
- Runtime/code/tzdata drift prevents verified replay, while the stored historical result remains readable after integrity checks. A historical result is not silently recalculated under a different runtime.

## Acceptance coverage

| Criterion | Result | Actual evidence |
|---|---|---|
| C01: deterministic interval/window arithmetic and boundaries | PASS | Inclusive interval union avoids double counting overlapping/adjacent visits. Each planned day has a rolling-window result. Existing 200-case day-set oracle plus reviewer 120-case open-continuation oracle cover entry/exit counting combinations. Leap/date extremes, open-history conflicts, malformed dates, input bounds and missing context pass. |
| C01: uncertainty and passport/basis context | PASS | Incomplete/unconfirmed history and unknown/changed passport or basis are retained as findings. Source-rule absence/mismatch and unresolved open stays refuse a scenario where required. No exact remainder, regime decision or quoting permission is produced. |
| C02: versioned calendars and distinct duration units | PASS | Explicit per-year calendars, overrides, transferred work/rest days, floating holidays, version/hash pins, crossing year boundaries and missing/provisional calendars pass. Calendar days, workdays, months and elapsed hours remain separate. |
| C02: timezone, endpoint and error behavior | PASS | Before/after and anchor-inclusion combinations, month clamp/reject, elapsed UTC hours with Bishkek display, missing timezone data, unknown offset, range limits and date overflow pass. Failed calculations return no partial date or trace. Existing 120-case independent workday-sequence oracle passes. |
| C03: immutable storage, provenance and historical replay | PASS | Both SQLite and actual isolated PostgreSQL verify history/calendar versions, source identity, scoped links, retained old revisions, mutation rejection, exact replay and result/runtime drift detection. |
| C03: transaction/retry/failure behavior | PASS | Actual PostgreSQL verifies same-request concurrency, competing history revisions, rollback after child-write failure, lost commit acknowledgment reconciled by exact retry, cross-contact/revision FK enforcement and integrity rejection for corrupted parent/child/source/result/link data. |
| Real legal/source/calendar policy approval; personal eligibility; C05 | N/A | Outside these fixed arithmetic/storage criteria. No business/source approval or qualification completion is inferred. |
| Production release and owner acceptance | N/A | Target is reviewed local behavior; no deployment, production data or customer messaging was performed. |

## Checks actually performed

Environment: Windows, Python 3.12, env-free archived revision; synthetic SQLite and PostgreSQL 16 on the explicitly isolated `127.0.0.1:55971` rehearsal cluster. PostgreSQL fixture validates host/port/user/database and creates individual disposable databases from an empty migrated template. Connection values were not printed or copied into artifacts. Suites ran sequentially.

Commands ran from `runs/calculation-independent-20261012/snapshot`:

| Command/scenario | Result | Limitations |
|---|---|---|
| `python -m pytest tests/test_kg_stay_days.py tests/test_kg_deadlines.py tests/test_entry_storage.py tests/test_entry_storage_migration.py -q --tb=short` | **246 passed**, 73.54 s | Scoped suites; not a full repository or browser run. Migration checks include additive schema parity, populated downgrade refusal, PostgreSQL DDL and synthetic CLI replay. |
| `python -m pytest tests/test_calculation_independent_oracle.py -q --tb=short` | **1 passed**, 0.86 s | Reviewer-added test executes 120 deterministic open-continuation examples, independently materializing observed/projected day sets and checking every window. |
| `python -m pytest tests/test_calculation_independent_pg.py -q --tb=short` with `FRUNZE_LOCAL_PG_CONNECTION` pointing to the existing private temporary local connection file | **31 passed**, 69.71 s | Actual migrated PostgreSQL. One existing Starlette/httpx deprecation warning, no failures or skips. This is local recovery/concurrency verification, not production verification. |

Total actually run: **278 passed**, zero failures/skips.

Reviewer probe artifacts and SHA-256:

- `runs/calculation-independent-20261012/snapshot/tests/test_calculation_independent_oracle.py`: `9c0f33f5d3b2e03b3052546323acc6fa03595a8304983224e233a74feb8ac84d`.
- `runs/calculation-independent-20261012/snapshot/tests/test_calculation_independent_pg.py`: `bbc658f0a561eb919571226d630eb2bdd2bc97905f27838386293b4005e9cedc`.

## Verdict

**APPROVE** the existing local implementation for fixed criteria C01, C02 and C03. Independent review evidence is now present for these three criteria. The separate final auditor must still assess the critical scope before the parent marks the reviewed task complete. This review does not add technical score, complete C05, approve real sources/calendars/policies, or authorize a pilot/release.
