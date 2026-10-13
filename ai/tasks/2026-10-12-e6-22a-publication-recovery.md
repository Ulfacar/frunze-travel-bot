# TASK: E6-22A — reliable rule withdrawal and publication history

- Date: 2026-10-12; branch `fix/tours-search-quality`, base `8062f80`.
- CLASS: CRITICAL; mode solo; completion target reviewed local correction.
- Authorization: user “делай”, continuing local PDF work. No deployment, production changes or actual source approvals.
- Builder: root. Independent reviewer: publication_review. Separate auditor: e622_audit.

## Problem and acceptance

Independent source review reproduced two defects in the existing D03–D05 implementation: a late-inserted backdated review changes the historical publication manifest; journal capacity prevents withdrawal of active rules.

1. Sample review timestamp under the existing set/version locks. New decisions must not precede their prior decision or be at/before the latest publication event. Reject without writing; exact retries retain their original receipt. Revalidate decision dates against the sampled timestamp.
2. Reserve one event and bounded bytes for withdrawal in new publication histories. Permit one terminal withdrawal for an existing full 250-event/16MiB history, keeping count and size bounded. Preserve historical receipts and validate the terminal event's action and position.
3. Native publication form offers withdrawal at the boundary. Server enforcement remains authoritative. Oversized ordinary events cannot consume recovery capacity.
4. Local migration extends only the publication revision constraint to 251. Downgrade with terminal data refuses before changes. Real PostgreSQL constraint/migration/concurrency and synthetic recovery are tested.
5. Exact independent defect reproductions pass; publication/runtime/answer and native compatibility checks pass. Separate final independent audit required.

## Risk pre-audit and recovery

No normal publication may use the recovery slot or byte reserve. No second overflow event. Enforce limits in both write and replay, while preserving formerly valid records. A retry at a now-full journal must still return its original result. Clock validation precedes insert but follows duplicate lookup. UI must not offer approval/activation after normal capacity. Locks remain set-before-version, with existing actor/policy/CSRF gates unchanged.

Migration is local only. Fresh migrated synthetic PostgreSQL and populated downgrade refusal provide recovery evidence; no claim about production backups. D03/D04/D05 reviews remain FIX_REQUIRED until independently corrected; the earlier 92-point checkpoint is historical, not proof against these findings. E6-22 approved qualification remains active and depends on this correction.
