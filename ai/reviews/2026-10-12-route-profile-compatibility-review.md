# E6-26 independent review — legacy profile compatibility

Verdict: **APPROVE**, scoped to the three frozen E6-26 R1 files below. The previously reproduced P2 defect is corrected: an intact historical profile which fails current answer semantics now produces an explicit RU/EN specialist-review fallback instead of generic HTTP 503. No remaining defect was found in this correction. Separate final audit remains required; this report is not release authorization or C05/source approval.

Reviewer: independent `publication_review` agent, 2026-10-12. Read the task/pre-audit and actual runtime diff before builder conclusions. Source, tests and configuration in the working tree were read-only; reviewer probes ran in an environment-free Git archive with synthetic local SQLite fixtures. No PostgreSQL, production data, root `.env`, source-status changes, deployment or outbound messages were used for this review.

## Exact scope and identity

Task: `ai/tasks/2026-10-12-e6-26-route-profile-compatibility.md`.
Base: `693d683b9a0adcb8f76d5551bf0f121ca6824fec`.
Frozen target: `runs/e6-26-r1`; its `snapshot.json` LF-normalized SHA-256 is `45e699d155a7602af8aec8a78c62f7c34d1e139d054fbc3b04cda2a5a85db95d`.

| File | LF-normalized SHA-256 |
| --- | --- |
| `app/domain/approved_qualification.py` | `f0bb665e38fcfa0eca260d87487da411a6f63758e43c4326f7a5dccef2c29243` |
| `app/admin/qualification_copy.py` | `dc32485cd863fa0628883f9039b9710307b6c3c978f4cccf075c86a1154cf409` |
| `tests/test_approved_qualification_legacy.py` | `67e3375d5055f8424e0ca6b93ef0532489d61307c9820fce5c9a878a6377f02d` |

All three hashes match the frozen target, reviewer archive and working-tree files at review completion. E6-25 and unrelated preserved UI changes are excluded. The reviewer archive is `runs/route-profile-compatibility-review-20261012/source.zip`, raw SHA-256 `d165afa8aaa7f320c86e685ea9fef1626cc1316a97b1f03f6ad704faca630ae3`; extracted base plus only the above overlays is under its sibling `source/`. `identities.json` records base and overlay identities. The independent probe's LF SHA-256 is `8a746dd081aacd5c39f5d4a6c9fd0fc52e4c39f4aa7eeea8efe874183c22b42b`.

## Findings and reasoning

**Closed P2 — current route check of a valid older receipt returned generic 503.** A profile with `applicants_count=1.0` and one accompanying child was accepted by the original intake handler. Its immutable receipt remains readable, but the corrected current intake handler raises `family_exceeds_applicants`. Previously this escaped through transaction error translation to the route's generic unavailable response. The earlier independent failure remains recorded in `runs/source-profile-independent-20261012/route-legacy-numeric-r2.txt`.

At `app/domain/approved_qualification.py:163`, construction and bundle validation stay outside the new catch. Only `QualificationReview.evaluate(...)` is wrapped. The caught type is `QualificationError`, whose current evaluate call sites represent invalid profile/request semantics. Actor authorization, case/applicant scope, stored history integrity, publication context, source checks and policy checks all precede it. The fallback retains the pinned profile/source context and explicitly sets `individual_profile_answers_conflict`; default fields remain no candidate, no selected regime/product, no eligibility or calculation, no quote, specialist review required and no delivery. No storage write path was added.

The RU/EN copy explains that the saved answers conflict and directs the operator to clarify the profile. Original inputs/results, schema, read/retry behavior, replay fingerprint rules and lock ordering are unchanged. Unexpected runtime exceptions and constructor/source failures remain outside this semantic fallback; this is substantiated by actual HTTP probes below, not only static inspection.

## Independent verification

Commands were run from `runs/route-profile-compatibility-review-20261012/source` on Windows/Python 3.12. Each fixture used a separate synthetic SQLite database and actual native HTTP handler via TestClient. Only one reviewer suite ran at a time.

1. `python -X utf8 -m pytest tests/test_route_profile_compatibility_independent.py tests/test_approved_qualification_legacy.py -q` — **9 PASS / 28.67s**, captured in `../independent-results-final.txt`.
2. `python -X utf8 -m pytest tests/test_approved_qualification.py::test_access_before_engine_or_data tests/test_approved_qualification.py::test_native_page_defaults_approval_gates_query_scope_and_safe_print -q` — **5 PASS / 7.97s**, captured in `../access-results.txt`.

The first command includes seven independent adversarial/positive cases and two supplied regression cases. Independent coverage:

- **PASS, RU and EN:** load the actual original `87ad9e759aae223258742d286310aba2155f112d` intake handler from the retained Git archive, verify its hash, and use its captured qualification runtime fingerprint to save the historical numeric profile through profile persistence. Restore the fixed handler; domain proposal and native GET return bounded specialist fallback/HTTP 200 with the correct translated explanation. No candidate/internal exception appears. SQL statement observation sees no DML; full read history remains equal; exact retry returns the original receipt unchanged.
- **PASS, valid positive control:** current valid profile still yields the expected nonbinding synthetic candidate and native candidate page; no quote or selected product is inferred and history stays equal.
- **PASS, actual corruption:** independently alter the selected stored profile snapshot hash and source projection hash in disposable SQLite fixtures. Both native requests return HTTP 503 and do not show the answer-conflict fallback or candidate.
- **PASS, unexpected runtime failure:** an injected `RuntimeError` from fresh evaluation still returns HTTP 503 without leaking its synthetic message; history stays equal.
- **PASS, constructor boundary:** `QualificationError('invalid_bundle')` raised by review construction remains HTTP 503, proving the new catch is limited to evaluation.
- **PASS, existing gates:** four unauthorized actor variants fail before engine/data access. Native checks retain configured-authority gating, query rejection, wrong-case 404, feature-disabled 404, no-store/no-referrer headers and the existing bounded claims.

The original-handler artifact is `runs/source-profile-independent-20261012/source.zip`, raw SHA-256 `37c4fc3a60c4a766cce1ebe4bba3bfadd8f5b52732de4c33859475cd212fe24d`. Its intake LF SHA-256 is `2d5200a730cb8d9e349b00f3292a1ca086091f34b77e91ec93f79f9c8fa840a3`; the runtime capture is `baseline-qualification-runtime.json` in the same directory. This probe executes the real historical intake function, not a stub that suppresses validation. Surrounding persistence and native HTTP execution use the reviewed current archive.

Initial reviewer run recorded **2 FAIL / 7 PASS** solely because the probe compared raw CRLF bytes to an LF-normalized historical hash, before either affected behavior probe executed. Correcting that reviewer-only identity assertion produced the final nine passes. Runtime/source code was not changed. Both final runs have only the existing Starlette/httpx deprecation warning.

## Limits and disposition

This is approval of the local compatibility correction, not the entire qualification feature. Actual source/policy authority, complete C05, production deployment and real client decisions remain outside the task. No PostgreSQL lock probe was repeated because this change adds only a read-path semantic exception branch after the existing lock/integrity checks and changes no SQL or lock behavior. Native HTTP content and RU/EN behavior were exercised; a new visual browser audit is unnecessary for the added reason text and is not claimed. Historical receipts are preserved; this change deliberately does not rewrite them or claim they pass current validation.

The scoped correction is ready for the separately required final audit on these exact identities.
