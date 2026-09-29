# RELEASE: <target/environment>

- Task / version / exact revision: <references>
- Owner and authorized scope: <who, action, environment, source/date>
- Risk / mode: <classification>
- GO / NO-GO: <verdict and blockers>

## Before release
- Requirement coverage and independent review: <evidence>
- Required checks / CI / baseline failures: <evidence>
- Data/schema changes and compatibility: <scope or N/A reason>
- Backup/restore evidence, if needed: <location, timestamp, restore check; no credentials>
- Rollback trigger, command/procedure, owner, expected recovery: <concrete>

## After release
| Check | Expected | Actual | PASS / FAIL / UNKNOWN |
|---|---|---|---|
| Delivered revision | | | |
| Health | | | |
| Approved business smoke scenario | | | |
| Errors/logs and relevant invariants | | | |

- User/business acceptance if required: <who, when, scenario; otherwise UNKNOWN/N/A reason>
- Handoff: <path>
