# E6-26 separate final audit

**Verdict: APPROVE the exact frozen R1 compatibility correction.** The independent review is complete and its scoped APPROVE is supported by this separate audit. No remaining defect was found in the three-file change. This is local reviewed behavior, not source/policy approval, complete C05 acceptance or release authorization.

Auditor: separate `calculation_review` agent, 2026-10-12. Read the task and its embedded pre-audit, then actual frozen diff and surrounding profile/evaluation/native-route code before examining builder tests or the independent review's conclusions. Root source was read-only; own probes ran in an env-free snapshot. No production data, root `.env`, live service, messages, source approval or E6-25 changes were used.

## Identity

- Task/pre-audit: `ai/tasks/2026-10-12-e6-26-route-profile-compatibility.md`.
- Base: `693d683b9a0adcb8f76d5551bf0f121ca6824fec`.
- Frozen target: `runs/e6-26-r1`; own copy: `runs/e6-26-audit-r1`, reconstructed from its Git archive and only its three manifest overlays.
- `snapshot.json` LF-normalized SHA256: `45e699d155a7602af8aec8a78c62f7c34d1e139d054fbc3b04cda2a5a85db95d`; raw file SHA256: `2683bfda3903be45ab96c9da9c937e9f8f2f04350ea3b669270f1cb86aeb948b`.

| Scoped file | Verified LF-normalized SHA256 |
|---|---|
| `app/domain/approved_qualification.py` | `f0bb665e38fcfa0eca260d87487da411a6f63758e43c4326f7a5dccef2c29243` |
| `app/admin/qualification_copy.py` | `dc32485cd863fa0628883f9039b9710307b6c3c978f4cccf075c86a1154cf409` |
| `tests/test_approved_qualification_legacy.py` | `67e3375d5055f8424e0ca6b93ef0532489d61307c9820fce5c9a878a6377f02d` |

All three matched the frozen target, own copy and root files at audit verification. Preserved UI/E6-25 edits are excluded.

## Findings

The catch covers only the fresh `QualificationReview.evaluate(...)` call and only `QualificationError`. Review construction/bundle validation, stored profile integrity, source/publication/policy checks, authorization and scope checks remain outside it. Existing evaluate call sites use that exception for invalid profile/request semantics. Unexpected runtime errors remain unavailable errors.

An intact old profile whose answers conflict under current validation now returns an explicit translated specialist fallback with no candidate, quote, selected product, visa determination, eligibility or calculation. The fallback preserves the pinned profile/source context. Original inputs, result snapshots, fingerprints and history are not rewritten. RU and EN text explains the conflict and points back to the profile.

No SQL, lock order, schema, public write path or historical replay behavior changed. An AST comparison of `propose_route` after removing only the newly added semantic try/catch exactly matched the base function; no other statement moved or changed. `applicant_profiles.py`, `entry_applications.py`, `entry_storage.py`, `knowledge_publication.py` and `kg_approved_qualification.py` matched the base bytes after line-ending normalization.

## Own executed evidence

Command, from `runs/e6-26-audit-r1`:

`python -m pytest tests/test_e626_final_audit.py -q --tb=short`

**6 PASS, 19.38s**, synthetic local SQLite/native TestClient. One existing Starlette/httpx dependency deprecation warning; no failures or skipped behavior probes.

- **RU and EN actual archived-handler controls:** loaded the real intake function and runtime-fingerprint routine from retained env-free base `d847a254acfd54ec8aeecef529c2885f6ba39bbe` at `runs/applications-documents-review-20261012/snapshot`. Used them to save a profile with `applicants_count=1.0` and one child, and verified exact replay while that historical handler/runtime was installed. Restored the current handler. Current domain proposal and native GET returned `individual_profile_answers_conflict` / HTTP 200 with the correct visible translated explanation, no candidate or internal error code, and no quote/eligibility assertion. SQL observation recorded no INSERT/UPDATE/DELETE/CREATE/ALTER. The complete stored read result remained equal before and after both checks.
- **Actual integrity corruption:** changed the stored profile snapshot hash only in the disposable fixture. Native GET returned HTTP 503 without the semantic fallback or candidate.
- **Unexpected fresh evaluation error:** injected a synthetic RuntimeError; native GET stayed HTTP 503 and did not disclose the exception text.
- **Constructor boundary:** raised `QualificationError('invalid_bundle')` from review construction; native GET stayed HTTP 503, proving the catch does not wrap source construction.
- **Positive control:** a valid current profile retained the expected source-bound nonbinding candidate, exact profile/source identity, unchanged replay and absence of writes/eligibility/quote assertions.

Builder reported 31 PASS; that is not counted as own audit execution. After completing the independent code assessment and own probes, read `ai/reviews/2026-10-12-route-profile-compatibility-review.md`: reviewer APPROVE on the same identities, with 9 PASS actual archived-handler/error/positive controls and 5 PASS actor/native gates. Its preserved original failure and reviewer-only line-ending assertion correction are explicitly recorded there. No contrary evidence remains unresolved.

## Applicability and limits

PostgreSQL rerun: **N/A**, because the AST/byte comparisons above establish unchanged SQL, transaction ownership, read/lock order and persistence behavior; the change is a local semantic exception branch plus reason text. Additional visual browser audit: **N/A** for this bounded reason-text addition; actual native RU/EN output was tested, and the route template/CSS was unchanged. Neither item is claimed as newly executed evidence.

All applicable E6-26 local completion checks have evidence. Full PDF completion, complete C05, actual approved source/policy authority, real applicant decisions and production release remain outside this audit.
