# E6-20 — bounded application-deadline review closure

CRITICAL / solo. Target: independent review and separate audit of the existing
E6-05 application-deadline journal and native flow, fixed G01/G02 criteria.
This is a remaining parent J03 review obligation, not a new feature or score.
Initial action is source-first review of unchanged committed runtime dc474d8.

Requirements: original `2026-10-10-e6-05-application-deadlines.md`, fixed
`docs/pdf-engineering-criteria.json` G01/G02 and actual implementation. Inspect
source before the historical builder handoff. E6-18's typed-boundary review is
supporting narrow evidence, not blanket approval of the original deadline scope.

Use immutable `runs/e6-19-review-r2` (base d1c9a38 + verified five overlays), whose
715 non-ai/docs committed files match dc474d8. Make own environment-free copies;
do not modify the frozen source. Only synthetic FK SQLite/native/browser and
guarded isolated PostgreSQL. Never legalize draft rules, infer dates, activate
policy, migrate production or send messages.

Verify authoritative current anchors/source/calendar versions, manual override
and correction/clear provenance, stale/unknown behavior, receipt retry/CAS,
runtime upgrade compatibility, dependencies and owner tasks, scope/authorization,
migration integrity and meaningful recovery. Use existing tests plus independent
negative or concurrency probes justified by source findings. Prefer bounded
scenario coverage over another full suite; serialize own jobs for host resources.

Reproduce any material defect on this snapshot before suggesting a correction.
Root must perform a pre-audit and narrow implementation only if warranted; then
new exact-snapshot re-review/audit is required. Do not fabricate completion to
meet the time limit or silently claim the ongoing old-snapshot full run covers
later code. If review cannot close, preserve an actionable packet and UNKNOWN.

Hard parent deadline03:00UTC; reserve final15minutes. Target initial findings by
01:50UTC and review-only closure by02:15UTC if evidence permits. This task must
not delay saved final report/authorized user Telegram. No builders delegated.

## Confirmed finding and corrective pre-audit

Auditor independently reproduced count and canonical-byte capacity failures on
the unchanged dc474d8 snapshot, two SQLite and two actual PostgreSQL failures:
valid manual deadline withdrawal is refused and its planned task remains active.
These are reduced-limit boundary reproductions, not claimed actual250/4MiB runs.
Original failures remain under runs/auditor-e620-r1. G02 cannot be reaffirmed
until this material defect is closed; no score/review promotion while pending.

Root correction authorized within local scope after separate reviewer/auditor
pre-audit: unchanged ordinary250-revision/4MiB prefix, one final clear receipt
whose size is bounded by the preceding canonical row bytes+1024. This covers
the inherited snapshot and existing bounded actor/key/reason metadata. Validate
the same terminal rule on reads and writes; preserve old exact receipts/retries,
deny any later append, cancel the task atomically, expose native clear/history.
New0033 changes only the SQL revision cap to251. PostgreSQL locks the table;
SQLite uses a dedicated FK=OFF migration connection, explicit transaction and
pre/post foreign_key_check; it refuses FK=ON before changing anything. Never
toggle FK enforcement inside a transaction. The final r3 downgrade refuses ANY
populated deadline journal: a byte-triggered terminal clear can be below251 and
still requires the new reader. This conservative restriction preserves data;
do not downgrade schema/runtime over such evidence. Empty migration cycles are
supported. Local COPY recovery is checked separately; no production recovery claim.
Check populated chains/inbound tasks, receipt equality, negative FKs, rollback,
old module compatibility and separate recovery before scoped closure.

Builder initial local run:6PASS/2FAIL/19.34s. Both failures revealed an existing
Jinja dict.clear attribute collision that rendered an empty clear form when no
clear envelope existed; changed the template to explicit forms.get('clear').
Original XML retained at runs/e620-builder-initial.xml. Rechecks pending.

R2 follow-up: independent reviewer reproduced a new optional minimum_revision
API bound that still rejected terminal251 (reduced-limit unchanged r2 probe).
Root r3 changes it to MAX_REVISIONS+1, preserving strict positive integer checks.
Both reviewers supported conservative populated-downgrade refusal above instead
of copying mutable canonical byte accounting into migration code. No policy or
source activation changed. Separate new snapshot/re-review required.
