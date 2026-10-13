# E630C current aftercare reader: separate final audit

Auditor: independent `/root/e622_audit`; 2026-10-13. CRITICAL / solo,
reviewed-local target. **GO for the exact two-file R28 aftercare current reader
and native display.** No open scoped defect remains. This does not complete
E630C, its source/product/golden scenarios, J03, or the new work-task adapter.

## Requirements and source before conclusions

Read the task `ai/tasks/2026-10-13-e6-30c-source-acceptance.md`, source-first
pre-audit, applicable protocol/profile/state, actual code and Git delta before
the separate review verdict. Protocol mode is solo; this is the required
separate final audit following independent implementation review.

Directly extracted original PDF physical pages 81, 82 and 84: sections 19.5-8
distinguish RL/FF/S/SW visa work from separate resident-card medical documents,
decision and collection. Section 19.13 permits the special-registration branch
without inventing an L visa, departure or root closure. Original PDF SHA256:
`141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.
The source is requested behavior, not legal or business approval.

Accepted bounded behavior: display current evidence for each own linked RES or
REG application, preserve separate official decisions and documents, prefer an
initialized REG child's current receipt, expose missing/withdrawn/invalid
evidence, and keep parent stages and immutable historical receipts independent.
This reader does not calculate a registration period or authorize lawful stay.

## Exact scope and isolation

Base: `7b0475b536592f6d254d607fb4baf3619a6e7fff`.

| Scoped file | Final normalized-LF SHA256 |
| --- | --- |
| `app/domain/entry_processes.py` | `700af9a4d7d5a4a51c4281cd3fda6e27c1d5d66c313a955aa355cc8aaa8e54d3` |
| `app/admin/templates/kg_process_journal.html` | `d88a511f57338133d35e580edfccaf1872b1fabd650e8fde09a00ad4ed564f96` |

Frozen R28, root and own audit copies match both hashes. R28 manifest LF SHA256
`963218af4092993995ac24084055dbe568f573f9aa4cee46d554bb1de3e33956`
identifies the containing snapshot, not approval of every overlay. To exclude
the unreviewed 0041/model/task changes, own archive was built from the Git base
plus all verified R25 overlays, then only these exact two R28 files. R25
manifest LF SHA256
`aea8100f1529972097daedeeb2cddadecc591efe619f470baaac4f8f06c66a40`.
R25 and R28 reader bytes are identical; the template delta localizes known
decision enums through the existing escaped label macro.

Own archive: `runs/e6-30c-aftercare-audit-r28`.
Identity evidence: `runs/audit-identity.json` there. Confirmed no `.env`, no
0041 migration, no root application imports. PostgreSQL checks used the
explicitly validated private loopback connection and fresh disposable migrated
databases. No secrets, live data, providers, messages or deployment were used.
Only own harness/artifacts and this audit report were written.

## Source assessment

- `read_process_history` retains the existing case lock and samples one current
  timestamp after acquiring it. Parent and linked child journals are read in
  that transaction. There is no added lock order or external side effect.
- Each link is validated as the same case/applicant and expected procedure;
  `decision` comes from that application's own journal. The parent's visa
  approval cannot supply a resident or registration approval.
- The current receipt uses the configured manual-source authority, profile
  continuity where pinned, observation validity, own official approval and
  actual observation date. An observation dated before that approval is
  unknown. This date comparison does not invent a sub-day official timestamp.
- A separately initialized REG child's validated state supplies its receipt.
  Withdrawal, stopped state or catalog mismatch cannot fall back to the
  duplicated parent observation. Full child history is bounded and replayed
  through `_history`, without recursively calling the current dependency reader.
- Current application/package identity and source journals use existing
  `Evidence.prefix` checks; future source rows fail the read. A future parent
  process head suppresses the new dependency panel; a future child head makes
  its receipt unknown. Equality is permitted. The historical selected record
  remains available according to existing integrity rules.
- Process authority absence/expiry/catalog mismatch suppresses current
  dependencies; revoked receipt-source authority yields unknown. Package
  acceptance and official decision remain separate facts. The view does not
  claim source publication or an automatic official lookup.
- The new panel is explicitly current, linked to the correct child application,
  and separate from parent stage/history. It has no action form or write path.
  Known decision enums are translated; Jinja escaping remains enabled.

Independent AST comparison with actual base `7b0475b` confirms eleven old
functions, including `_history`, `_evidence`, `_readiness`, `_view` and
`record_process_operation`, are unchanged. Only `read_process_history` changes
and `_current_dependency_receipt` is added. Exact artifact:
`runs/retained-handler-ast.json`. No new journal format, migration or historical
reducer is introduced by this scope.

## Own actual PostgreSQL evidence

Executed only in the isolated audit archive, with private connection-file path
supplied explicitly through `FRUNZE_LOCAL_PG_CONNECTION`; no DSN was printed.

```text
python -X utf8 -m pytest tests/test_audit_aftercare_pg.py -q --tb=short --junitxml=runs/audit-aftercare-pg.xml
```

Original run: **1 PASS / 1 harness FAIL / 21.01 s**, one dependency warning.
The passing case builds actual parent/child journals with duplicated parent
receipt, reads the exact historical selection, checks native localized approval
and observes no INSERT/UPDATE/DELETE during a current read. It pauses a real
child withdrawal while holding the case lock, observes a scoped
`pg_stat_activity.wait_event_type='Lock'` for the concurrent parent reader,
and proves the current-clock sampler has not run while waiting. After writer
commit, the reader samples exactly once and returns unknown from the child's
withdrawn receipt, despite the duplicated parent attestation. Historical
selection remains exact. Original pre-withdrawal request retry with policy
absent returns the same receipt/hash without another revision.

The second case's deliberate corruption injection initially used ORM mutation;
the existing immutability guard correctly blocked setup. Its first correction
used ORM bulk UPDATE and was also correctly rejected by the bulk-write guard:
**1 harness FAIL / 12.67 s**, artifact
`runs/audit-aftercare-corruption-corrected.xml`. Both original harness versions
are preserved in `tests/audit_aftercare_pg_first.txt` and
`tests/audit_aftercare_pg_second.txt`. Neither failure reached the corruption
reader oracle or establishes a runtime defect.

The final harness uses a bound Core connection UPDATE only within its synthetic
database to simulate hostile persisted data, without weakening application
guards. Narrow rerun:

```text
python -X utf8 -m pytest tests/test_audit_aftercare_pg.py::test_current_authority_removal_and_rehashed_child_corruption_preserve_original_receipts -q --tb=short --junitxml=runs/audit-aftercare-corruption-raw-pg.xml
```

Result: **1 PASS / 12.70 s**, exit 0, one dependency warning. It proves missing
authority preserves historical selection while removing the current panel;
revoking only the receipt source returns unknown and restoring it returns true.
A child snapshot moved to the parent root and fully rehashed is rejected by the
domain; native GET returns no-store 503 without a positive dependency panel.
Restoring the exact record recovers the true receipt and original request/hash.

Thus **two distinct own actual-PG controls pass**. The initial suite is not
represented as wholly green. Exact XML hashes/counts are recorded in
`runs/own-evidence.json`. No active auditor test or PostgreSQL process remains;
the slot was explicitly released to the parent.

## Independent review and native evidence

Read the separate source-first review after own source assessment:
`ai/reviews/2026-10-13-e6-30c-aftercare-review.md`, final R28 APPROVE.
It preserves four genuine defects and their corrective evidence: ignored child
receipt, resurrection of duplicated parent receipt after child withdrawal,
receipt actually dated before own approval, and a future child process head
accepted as current. They were corrected before this audit's target; no
original failure is rewritten as a passing run.

Independently parsed final reviewer XMLs: R25 original corrective run contains
10 PASS and one separate read-view/write-receipt shape assertion error; its
narrow equality correction plus browser run has 2 PASS. R28 localized browser
rerun has **1 PASS / 22.402 s**, raw XML SHA256
`b5b43343f2a0108a37cea59eafc3c57d6e16b37076fd51deb26143a04edeef0a`.
This is reviewer execution, not an auditor browser rerun. The reader is
byte-identical across those candidates.

Personally viewed both final R28 screenshots under
`runs/e6-30c-aftercare-review-r28/runs/review-aftercare-browser`:
`dependency-390.png` and `dependency-1365.png`. Mobile text fits and clearly
shows the own registration link and localized approval; the desktop no-JS
historical view shows unknown after actual child withdrawal. Both explain that
current confirmations are separate from the parent's stage. These cropped
panel images support this bounded display, not a whole-page redesign, dark
theme, print, or unrelated root base-shell changes.

## Final boundary

The exact two-file current reader/display is **GO for reviewed local work**.
Own adversarial and actual-lock checks, unchanged historical handler mapping,
separate implementation review and final native artifacts support this verdict.
No further change or new schema is needed for this read-only component.

This report does not award whole E630C/J01/J02/J03/J05, certify all five RES
source stories, provide an actual registration-period adapter, accept the new
0041 work-task schema, activate source/calendar/business policy, or authorize
production/pilot use. Those scopes remain separate. Later changes to either
scoped file require an explicit delta assessment.
