# E6-11 — independent preliminary domain review

- Task: `ai/tasks/2026-10-11-e6-11-portal-notifications.md`; prior requirements audit: `ai/reviews/2026-10-11-e6-11-pre-audit.md`.
- Reviewer: `/root/portal_pre_audit`; builder: `/root`; **INDEPENDENT**. Requirements and actual frozen source inspected before builder test/result conclusions.
- Base: `e9e7c351b493aeb5d78e09f3ccf907107c73a919`.
- Target: `runs/e6-11-preliminary-r1`, uncommitted 9-file domain snapshot. Native UI is intentionally absent from this packet and is being built separately.
- Manifest: `ai/reviews/2026-10-11-e6-11-preliminary-r1-snapshot.json`, SHA256 `13a7b07f4394ce2f9b0adfdd42b02b796c0db8438a64053fb4a0788cc65d9a5f`. **All 9 LF-normalized file hashes match**; no `*.env` in snapshot root.
- Source/archive not edited. Reviewer wrote this report and `runs/e6-11-prelim-independent-probes.py`; tests used only disposable local synthetic SQLite with repository network guard.

## Verdict

**FIX_REQUIRED** for this frozen preliminary snapshot. Two concrete defects were reproduced. This is not a final release review or whole-task approval. Current root may contain fixes reported by builder; they were not substituted into the frozen snapshot or independently approved here.

## Findings

| Severity | Location in frozen snapshot | Trigger / consequence | Evidence | Required correction |
|---|---|---|---|---|
| P1 | `app/domain/entry_portal.py:118`, `:242`, `:382` | Manual receipts derive `raw_sha256` from only `{reference, kind, occurred_on}`. Two separate verified same-day corrections, separated by a resubmission and supported by different archive/verification evidence, collide in the global applied-content claim. The second genuine correction cannot be recorded; application incorrectly remains `submitted`. This is a collision of generated structured content, not a retransmitted email | Independent probe: receipt IDs 1/2; submission cycle IDs 2/4; distinct archive references/proofs and confirmation references/proofs; second confirmation raises `EntryStorageConflict('portal_content_already_applied')`; `can_confirm` was true | Separate manual observation identity from pasted-byte duplicate identity. Preserve actual evidence identity and verified submission cycle for manual observations, while rejecting replay of the same evidence. Keep exact-byte duplicate protection for pasted notifications. Add a test for two genuine same-day correction cycles with distinct evidence, plus negative same-proof/repeated-content cases |
| P1 | `app/domain/entry_applications.py:265` | Refactor moves `_authorize` and input preflight inside `_run`. Public API now accesses engine/session before rejecting an unauthorized actor. `engine=None` produces `TypeError` instead of `PermissionDenied`; with an unavailable database the old fail-before-storage authorization contract also disappears | Existing `test_named_full_admin_precedes_engine_access` fails for all five actors (`None`, non-admin, direction manager, `system`, blank actor) in the independent regression run. Other existing public APIs still reject first | Restore public preflight before `_run`, preferably with one shared pure input validator called by public wrapper and same-session helper. Preserve helper defense before lock/read as well. Do not weaken the existing regression test |

The first probe also exposes a UI-readiness issue at `entry_portal.py:323`: `can_confirm` checks only policy/disposition/current binding, so it advertises an already-known impossible confirmation. When UI is completed, provide a meaningful blocked reason for content conflicts, terminal/incompatible heads, date conflicts and limits; do not present a success-capable action based solely on binding equality. This observation is secondary to the concrete dedup defect, not a separate release claim.

Builder reported fixing authorization preflight in the current root after receiving the finding. **That fix is unverified in this report**; the reviewed frozen r1 still has the regression.

## Reproduction of the manual-observation defect

Run from `runs/e6-11-preliminary-r1`:

```text
python -X utf8 ../../runs/e6-11-prelim-independent-probes.py
```

The probe creates a synthetic submitted application, records and independently confirms a manual portal correction, records same-day resubmission, then records a second manual correction with a different archive reference/proof and different independent verification reference/proof. Both confirmations explicitly verify the cycle. The observed result was:

```json
{
  "first_receipt_id": 1,
  "second_receipt_id": 2,
  "first_cycle": 2,
  "second_cycle": 4,
  "same_generated_raw_sha256": true,
  "second_can_confirm": true,
  "distinct_archive_and_verification_proofs": true,
  "result": {
    "outcome": "EntryStorageConflict",
    "code": "portal_content_already_applied"
  },
  "application_status": "submitted"
}
```

The archived email duplicate test is valid and should remain: replaying identical pasted bytes after resubmission must not create a new correction. Manual checking of a new portal state has different evidence identity and needs a separate rule. Merely adding random request/transport IDs to the dedup key would weaken replay protection and would not be a sufficient fix.

## Positive assessment and limits

- Import is separated from authoritative application facts. The five notification kinds remain observations until a separate explicit confirmation; verification/payment confirmations do not append submitted/payment/process events.
- Correlation uses the global immutable reference claim within the requested case and validated application history. Binding includes exact application identity, head and last submitted cycle hashes; current confirmation rejects a stale binding.
- Application append, existing `sync_enabled`, and action insertion share the same owned transaction. The helper contains no commit or swallowed exception. SQLite fault tests after either half of the write passed.
- Receipt/action immutable payloads and relational scope constraints are present; historic receipt replay pins the applied event while permitting later application progression. ORM/bulk mutation tests and pinned-event corruption test passed.
- Explicit policy is retained in receipts/actions; default missing policy does not authorize fresh imports/confirmation. Exact retry after policy loss is implemented before fresh policy/CAS. Full-admin gates remain in the new domain functions.
- Parser uses bounded literal captures, does not retain full message text, fetch URLs, parse attachments or execute untrusted input. Existing ambiguity/control/bounds tests passed.
- These are local synthetic conclusions. No real portal wording, mailbox authentication, privacy authority, deployment or customer sending was tested or approved.

## Checks actually performed

All commands below ran with working directory `runs/e6-11-preliminary-r1`, Python 3.12 / Windows, environment-free snapshot and synthetic SQLite. Reviewer did not use builder test results as evidence.

| Command / scenario | Result | Evidence / limitation |
|---|---|---|
| SHA256 manifest + 9 file comparisons | **PASS, 9/9** | Exact supplied manifest digest and LF-normalized source hashes |
| `python -m pytest tests/test_entry_portal.py tests/test_entry_portal_parser.py tests/test_entry_applications.py tests/test_entry_deadline_tasks.py -q --basetemp=../../runs/e6-11-independent-prelim-pytest --junitxml=../../runs/e6-11-independent-prelim.xml` | **109 PASS / 5 FAIL / 0 SKIP / 1 warning**, 145.49 s | All failures are the authorization-before-engine regression; warning is existing Starlette TestClient deprecation |
| `python -m pytest tests/test_entry_applications.py::test_named_full_admin_precedes_engine_access tests/test_alembic_domain_migration.py::test_upgrade_head_creates_all_six_domain_tables tests/test_alembic_domain_migration.py::test_downgrade_base_removes_only_domain_tables -q --basetemp=../../runs/e6-11-prelim-auth-schema --junitxml=../../runs/e6-11-prelim-auth-schema.xml` | **2 PASS / 5 FAIL / 1 warning**, 11.43 s | SQLite head upgrade and empty full downgrade pass; five repeated minimal auth reproductions are not additional distinct defects |
| `python -X utf8 ../../runs/e6-11-prelim-independent-probes.py` | **FAIL for intended distinct manual-cycle behavior**, process exits 0 because probe reports outcome | Actual synthetic transaction proof above; temporary SQLite removed by probe; no archive mutation |
| Source inspection: task/pre-audit, provided PDF requirements, policy/parser/domain, models/migration, original writer/deadline hook | **PASS for inspection** | Does not replace missing runtime cases |

## Evidence still required for final review

The following are **UNKNOWN in this preliminary review**, rather than asserted defects in work not yet delivered:

1. Corrected frozen snapshot and fresh evidence closing both findings without weakening pasted-message replay protections.
2. Portal confirmation with an actually enabled deadline task, injected failure inside `sync_enabled`, complete rollback of action/application/task effects, then recovery. The existing deadline tests and two-half flush tests do not by themselves prove this joined path.
3. Portal-specific lost commit acknowledgment, exact retry after later application advancement and policy removal, and native form preservation when the post-write read is also unavailable.
4. Populated downgrade refusal and migration/model parity for the new tables, actual isolated PostgreSQL concurrency with the ordinary application writer, and recovery of populated receipts/actions with dependency journals followed by continued use.
5. Bounded pagination/list growth and byte-limit recovery; adversarial stored-type/hash/pin corruption beyond the one existing event-hash probe.
6. Native UI, current server-side gates, signed forms, escaped values, visible observation-versus-confirmation distinction, unavailable paths, mobile/no-JS/print and actual acceptance flow.

I03/I04/I05 remain unapproved by this review until the complete frozen implementation and required evidence are available. No release permission is implied.
