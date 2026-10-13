# HANDOFF: 2026-10-12-1200 — E6-21 approved source answers

- STATUS: **DONE for reviewed local H03**; full PDF **PARTIALLY_READY,92/100,8 remaining**.
- CLASS / mode: CRITICAL / solo. Completion target: reviewed local change, no release.
- Task: `ai/tasks/2026-10-12-e6-21-grounded-answers.md`.
- Branch: `fix/tours-search-quality`; code `c73745744b46f5b3b8029baba201c2506e4c4a06`.
- Reviewed frozen source: `runs/e6-21-r5`, manifest in `ai/reviews/2026-10-12-e6-21-snapshot-r5.json`.

## Result

Full-admin native `/admin/kg-entry/answers` and deterministic RU/EN answer API
consume the current publication. Up to three exact rules; all source values and
qualifiers, kind/registration country, source excerpt and version/citations remain
visible. Unavailable, incomplete or ambiguous rules require a specialist. The
screen performs no external asset requests and needs no JavaScript.

Publication runtime now supplies semantic/source metadata and refuses review
clock inconsistencies that could otherwise resurrect an earlier decision. No
source/policy is approved by code; all208 actual units remain draft. No personal
eligibility, free-text dialogue, new permission, durable handoff or client message
is implemented by this slice. Contract: `docs/e6-21-grounded-answers.md`.

## Evidence

| Claim | Scenario/environment/revision | Result / limit |
|---|---|---|
| H03 source answers | `pytest tests/test_knowledge_answers.py tests/test_admin_kg_answers.py tests/test_knowledge_answers_postgres.py tests/browser_kg_answers.py` inside recorded combined r4 run |43 PASS:24 domain,10 native,7 actual isolated PG,2 browser. Runtime and these tests identical to final r5. |
| Shared shell | `pytest tests/test_admin_shell_and_direction_split.py tests/test_admin_new_look.py` exact r5 |42 PASS/29.65s. Pilot-OFF route belongs in existing excluded-path lists; dedicated real ON/OFF/role coverage passes. |
| Supporting source regression | Six related publication/decision/projection/retrieval files, r2 |165 PASS/136.71s. Publication runtime identical to final; not a new final/full-suite run. |
| Identity | LF-normalized snapshot/root/commit hashes |13 changed source files and620 app/tests/migrations files match final snapshot; committed13 identity PASS. |
| Independent review | Fresh `/root/e621_review`, source-first; own tests and actual PG read/withdrawal lock probe |APPROVE, report in `ai/reviews/2026-10-12-e6-21-independent-review.md`. |
| Separate final audit | Fresh `/root/e621_audit`, own original issue probes, PG and browser evidence |GO for local H03, report in `ai/reviews/2026-10-12-e6-21-final-audit.md`. |
| Native UI |390mobile,1365desktop/noJS, empty/approved/withdrawn,2 print pages |PASS, images visually inspected; zero attempted third-party answer-page requests. |
| Temporary database |Loopback55971, local PG16.15; pg_ctl fast stop + status |PASS, stopped after independent checks. No production service accessed. |
| Updated progress report |`build_kg_progress_report.py --checkpoint grounded-answers --date 2026-10-12`; score checker and extracted headings |PASS:5 pages visually inspected,26/26 source headings,92/8 fixed score. `ai/reviews/2026-10-12-e6-21-report-evidence.json`; no send. |

Exact commands, XML hashes, counts and carried-source identity are in
`ai/reviews/2026-10-12-e6-21-runtime-evidence.json`. R1 test assumptions, r2 external
assets/semantic gaps, r3 catalog-fixture path and r4 legacy OFF-route expectations
are preserved, not relabelled as PASS. R4 whole combined run83PASS/2FAIL; only the
43 feature cases are cited from it. Final changed legacy42 checks pass separately.
No full repository suite was rerun; no external-network test was enabled.

## Remaining work and recovery

C05/H02/J01/J02/J03/J05 remain, totalling8 points with definitions unchanged.
21 earlier PASS criteria still have review UNKNOWN (mixed risks). H03 does not
close overall J03. Continue with approved-rule qualification and interview/dialogue
integration, precontract intake-to-case link and source scenario coverage. Existing
SRC/DEC owner decisions on legal rules, money, privacy, roles and messages remain.
Actual approval/owner acceptance and pilot authorization are still human gates.

Recovery: revert the new read-only adapter/route and scoped presentation changes;
no tables, migrations, journal writes or domain data were changed by answer reads.
Code is saved locally on the existing working branch. No deployment, remote push,
Telegram report resend, real client data or source approval occurred in this session.
Preserve unrelated untracked audio/briefing/host artifact/Bitrix text/CRM zip/old
E6-08 snapshot. The new progress report is local and must not auto-send.
