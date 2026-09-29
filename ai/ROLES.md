# Roles and review contracts

Assign capabilities, not permanent model versions. Record actual assignments in the task/review.
One agent can plan and build. Reviewing one's own work is always SELF_REVIEW.

| Role | Responsibility | Input | Output |
|---|---|---|---|
| Director | Observable acceptance and bounded scope | Request, current repository | Task card; unresolved decisions |
| Builder | Complete change and relevant checks | Task, repository, instructions | Change + reproducible evidence |
| Reviewer | Independently find defects/missing acceptance | Task, base/target, actual repository | APPROVE / FIX_REQUIRED / NEEDS_HUMAN_DECISION |
| Auditor | Examine critical risk before/after implementation | Requirements, code/data, recovery plan | Required checks; final GO / NO-GO |
| Human owner | Business policy and applicable release gates | Concrete alternatives, impact, evidence | Scoped decision/acceptance |

## Independent review packet

Supply the task, exact base/target, relevant files and commands. For uncommitted work,
include untracked files and a reproducible snapshot; `git diff` misses untracked files.
Do not supply the builder's summary/verdict or old review conclusions before the first assessment.
Do not grant mutation/deployment permissions for a read-only review.

A human or a separate agent context can provide independence. Prefer another provider when
available; do not require purchasing/accessing one. Follow host rules for delegation.
In strict CRITICAL work, Builder, Reviewer, and final Auditor are separate contexts/people.

Each finding needs location, trigger, consequence, evidence, and a suggested correction.
Sort by severity. Separate confirmed bugs, missing verification, and stylistic suggestions.
Record commands the reviewer actually ran; never inherit PASS from the builder's report.

## Copyable prompts

**Plan:** Read current context and code. Turn the request into ai/templates/TASK.md. Set risk
and completion target. Resolve technical choices from evidence; ask only consequential questions.
If I requested only a plan, do not implement yet.

**Build:** Follow AGENTS.md and the task. Implement and verify through completion within
authorized scope. Preserve unrelated work. Report missing evidence honestly; leave a handoff.

**Review:** You have the task and base/target snapshot. Inspect actual files and adjacent behavior.
What can still be wrong? Check acceptance and credible regressions. Run relevant available checks
when permitted. Do not read the builder's handoff before your first verdict. Use ai/templates/REVIEW.md.

**Audit:** Pre-audit: list critical failures and required evidence. Final audit: verify requirements
against actual code and recovery evidence. Return GO/NO-GO with precise reasons.

**Solo self-review:** Re-read the task, inspect the final diff including untracked files, challenge
assumptions, and reproduce the highest-risk behavior. Record SELF_REVIEW and its limits.
