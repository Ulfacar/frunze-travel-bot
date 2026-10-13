# E6-08 independent review and final critical audit

Date: 2026-10-11. Reviewer/auditor: separate Codex agent context `/root/package_review`.
Risk/mode: CRITICAL / solo. Scope: reviewed local E6-08 implementation, not production release.
Base: `a2c2722`; initial target: `26655d4` plus the three staged admin/browser/test changes supplied for review.
Final target: `26655d4` plus the uncommitted fixes identified by the SHA256 manifest below.
E6-09 quarantine work and other unrelated/untracked files are excluded.

## Independence and method

I read repository instructions, protocol/profile, task acceptance, actual changed code and adjacent authorization/storage code. I did not modify implementation, Git state, production, secrets or real data. Test writes used synthetic SQLite in the supplied environment-free `runs/e6-09-local` snapshot. The builder later authorized writing this report only.

Context limitation: my first task-file read returned the entire file rather than only its acceptance section, exposing implementation notes before initial code assessment. I immediately disclosed this to the builder. No handoff or review packet was read. Findings below arose from independent code inspection and my own reproductions; builder test results are not counted as my evidence. This is a separate reviewer context, with that exposure disclosed, not a builder self-review.

## Initial verdict: FIX_REQUIRED

1. **P1 — A full journal could make an approved package impossible to revoke.** Initial locations: `app/domain/entry_document_packages.py:144,188` and `app/admin/kg_document_packages.py:151,164`. An approval could consume revision 500 or the remaining byte allowance; subsequent revocation and consent withdrawal were rejected, while effective acceptance remained true. My synthetic SQLite reproduction scaled the same revision limit to 32: approval at revision 32 succeeded; both withdrawal operations failed with `invalid_document_package_revision`; a reread still reported accepted=true. Required correction: reserve bounded capacity for meaningful withdrawals, enforce it in the service and UI, and retain exact retries.

2. **P1 — Duplicate passport fingerprints bypassed invalidation of other document reviews.** Initial locations: `app/domain/entry_package_rules.py:69,128,146` (the original helper compared only a set of fingerprints). Reproduction: TS passport items `matrix_d01_0=A`, `g02_01=A`, `matrix_d02_0=B`; receive and check photo `t01_02=C`; replace `matrix_d01_0` with B. The fingerprint set remained {A,B}; passport revision stayed 3 and the photo remained effectively checked. This regressed the legacy receipt behavior and allowed reapproval using checks made before a passport-item replacement. Required correction: track passport identity/version, preserve old replay semantics, and block effective acceptance of affected old histories until explicit recovery.

3. **P2 — A practice recommendation became a mandatory tourist invitation.** Initial location: `scripts/build_kg_complete_document_catalog.py:209–210` and the review-2 catalog. `high_risk_country=True` forced g08 and all ten invitation-content requirements, although source clause t02_03 is recommended/practice and t01_03 expressly permits a personal statement. My reducer reproduction selected the personal alternative and completed all other applicable rows; exactly g08/letter01–10 remained mandatory and approval failed as incomplete. Required correction: preserve the recommendation separately from mandatory invitation grounds and register a new definition without altering the old catalog.

## Fix review and independent retest

- **PASS — withdrawal capacity.** Current service reserves two events and 8192 bytes for withdrawal; terminal no-op withdrawals cannot consume that capacity. Exact retry lookup precedes the new-write gates. The UI retains meaningful revocation/consent-withdrawal forms and removes ordinary writes. The reserved size exceeds the two bounded metadata-only withdrawal event payloads. Tests exercise both revision and byte limits, both withdrawals, repeated no-op refusal, historical approval preservation and exact consent retry.
- **PASS — passport invalidation and recovery.** New commands explicitly store rules_version=2 and compare passport item/version/fingerprint mappings. Absent/1 remains strictly versioned historical replay. The service detects an old missed invalidation separately from the immutable snapshots: historical states/hashes remain readable, while current/fresh acceptance fails until an explicit definition upgrade and recheck. The recovery error is explained in the native UI. My original duplicate-fingerprint scenario now increments revision 4→5 and reports the photo as `recheck`.
- **PASS — source distinction.** Review-3 removes high-risk recommendation from mandatory invitation grounds. My original personal-statement scenario now passes `assert_acceptable`; required invitations remain governed by their separate grounds. Review-2 and foundation digests remain registered and unchanged.
- **PASS, code inspection — historical catalog packaging.** The builder separately found that Dockerfile copied only the current catalog. I inspected the correction to copy the complete catalog directory and verified all three registered files exist and match their digests in the test snapshot. This is asset/recipe verification, not a Docker build claim.

Commands I ran from `runs/e6-09-local`:

```text
python -m pytest tests/test_entry_document_packages.py tests/test_admin_kg_document_packages.py tests/test_entry_document_packages_migration.py tests/test_kg_complete_document_checklist.py -q --basetemp reviewer-package-tmp --junitxml reviewer-package.xml --tb=short
```

Initial snapshot: **67 PASS**, one Starlette/httpx deprecation warning, 119.91s. This covered domain/HTTP/source/migration checks before the above fixes. An earlier invocation used a nonexistent nested basetemp parent and produced 27 PASS/40 setup errors; correcting my harness path produced the successful run. Those setup errors were not application failures.

```text
python -m pytest tests/test_entry_document_packages.py::test_passport_replacement_invalidates_checks_despite_duplicate_fingerprints tests/test_entry_document_packages.py::test_v1_passport_gap_preserves_history_but_requires_definition_upgrade -q --basetemp reviewer-passports-tmp --junitxml reviewer-passports.xml --tb=short
```

Final snapshot: **2 PASS**, one warning, 68.79s. The old-version test includes an actual persisted historical approval, unchanged historical snapshot/hash, current rejection, and explicit-upgrade/recheck/reapproval recovery.

```text
python -m pytest tests/test_entry_document_packages.py::test_full_journal_preserves_revocation_and_consent_withdrawal tests/test_admin_kg_document_packages.py::test_journal_limit_keeps_only_meaningful_withdrawal_forms tests/test_kg_complete_document_checklist.py::test_risk_recommendation_does_not_mandate_a_tourist_invitation -q --basetemp reviewer-final-limits-tmp --junitxml reviewer-final-limits.xml --tb=short
```

Final snapshot: **4 PASS**, one warning, 28.55s. A preceding intermediate-fix run of these four tests also passed; the final run above includes the subsequent rules-version changes. I also ran the standalone reducer and SQLite reproductions described in the findings. No builder-run PASS is inherited here.

## Final critical audit

The risk checklist here derives from the acceptance requirements and inspected implementation; it does not claim I performed a separate pre-implementation audit before this feature existed.

| Critical risk / recovery requirement | Audit result |
| --- | --- |
| Wrong case/application, unauthorized reviewer, missing policy, forged or cross-session form | PASS: service scope checks, composite FKs, named full-admin authorization, server-owned policy, signed CSRF form envelope; initial independent HTTP/domain negative checks passed. |
| Duplicate/concurrent/uncertain writes | PASS: immutable request-hash/key lookup before mutation gates, parent locking/CAS, exact retry and transaction-fault tests; version dispatch preserves the old command request hash. |
| New passport/file/facts/policy changes leave false acceptance | PASS for inspected scope: state/policy pinning, invalidation and strict current acceptance; reproduced passport defect fixed, historical affected state fails closed with explicit recovery. |
| Journal capacity prevents withdrawal | PASS on updated writer: reserved events/bytes, meaningful terminal writes, native withdrawal controls, final independent boundary checks. |
| Source alteration or recommendation promoted into obligation | PASS for changed catalog behavior: pinned registered definitions and reproducibility checks, review-3 distinction verified; historical artifacts remain exact. This does not approve the source as current law. |
| History lost by definition/rule change or schema rollback | PASS locally: old rule replay and snapshot preservation, explicit upgrade recovery, additive migration/model parity, populated/offline downgrade refusal and PostgreSQL DDL tests. |
| Container lacks definitions required for historical recovery | PASS for inspected COPY recipe and matching files; container build/runtime UNKNOWN. |
| PostgreSQL transaction/runtime/recovery behavior | UNKNOWN: no PostgreSQL instance exercised by this reviewer. |
| Current legal/source/privacy/role approval and real owner acceptance | UNKNOWN: no real policy approval was inferred or configured; policy remains absent by default. |
| Final browser/mobile/print acceptance | UNKNOWN in this independent pass: browser test code/template inspected, but browser scenarios were not run by this reviewer. Builder's final browser evidence belongs separately. |
| Production release | N/A: not the authorized completion target; no deployment or production mutation occurred. |

**Final review verdict: APPROVE for the bounded reviewed local change. Final audit verdict: GO for the local implementation/check target.** All three reproduced findings are corrected in the identified snapshot; no further confirmed code blocker was found. This is neither production release authorization nor confirmation of the UNKNOWN evidence above. The full final regression/browser run and any future production-specific gates remain separately accountable.

## Exact reviewed snapshot

SHA256 below uses file bytes with CRLF normalized to LF. Each listed workspace file was compared with the corresponding `runs/e6-09-local` file and was equal. Unchanged scope outside this final-fix manifest remains identified by base/HEAD above. JSON serialization of the ordered objects `{path,sha256,snapshot_equal:true}` using sorted keys and compact separators hashes to `b4aade12c5ce2c7d6a57436caffe42a36224bddef4b5bab942481b554d6d3952`.

| File | SHA256 |
| --- | --- |
| Dockerfile | `187b65fbe42d10dd5a6f33c6b92fb868b120479615f0ea6eb8ab461f78242301` |
| alembic/versions/e6_document_packages_0025.py | `86055a543ce58a5519a2fcbe67a1ac99c6875e092e180a9dfc63675f7ace5953` |
| app/admin/kg_document_packages.py | `f82b0d09404118e09234f2f935586945414aca0635ef865eda153868b7baae7e` |
| app/admin/templates/kg_document_package.html | `ecb93e879227e23b384b19ff07ab827fbcac9a8844ae7884a544e77e334eaec7` |
| app/domain/entry_document_packages.py | `9d491ae8b52ab6fa2770eaa7a86f8a5d7375c789e816aea0905dbe0aefe8fbe5` |
| app/domain/entry_package_rules.py | `4460467d35f8c64fd753dee09b6a1a11070094a346abae92051e5b9ddeb3ae17` |
| app/domain/entry_package_policy.py | `5977118f631f971ae94f091f85d9433d6271bf1d1ef06bc7d8fa2531057f3060` |
| app/knowledge/complete_document_checklist.py | `f1d8438a9fb748d0e7f8f33028f9f24c12d4eef67de8455737c4805ba0540b8f` |
| knowledge/kg_entry/complete_documents_v1_1/catalog.json | `555f15c6befb85da5c5386b2981d94897891aecafbce4e0edbb5362897e049f9` |
| knowledge/kg_entry/complete_documents_v1_1/catalog-review-2.json | `f176ab74144a593fd9ff644ba219d6731205c5fd232f1a661616c0223d40ad1a` |
| knowledge/kg_entry/complete_documents_v1_1/catalog-foundation.json | `5014a02c362964d74f0c55915dd2045c040ea513f9d9488585f745c0a67401d0` |
| scripts/build_kg_complete_document_catalog.py | `c7f50996bffc95eb2e260f243270fdb87c7e08b03ed3f9a359eda263379773f0` |
| tests/test_entry_document_packages.py | `f6c5863cc79f679fd970e5bf293cc415ea0c440b6f6249982b65a711c9a23458` |
| tests/test_admin_kg_document_packages.py | `1b2f4b278942500922ac745c06daab94f9d49143b6f8f5c1d2d19de8412787a2` |
| tests/test_entry_document_packages_migration.py | `a6247a981003cf978d32e778aeb6f28830e304726303c0f7b3cba12de7fb75c6` |
| tests/test_kg_complete_document_checklist.py | `74327a6a9c3a603c1bf71e855077a6771d4dc72a286a58083e0f1bd3e0888649` |
