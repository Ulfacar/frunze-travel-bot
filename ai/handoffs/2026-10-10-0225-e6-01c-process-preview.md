# HANDOFF: 2026-10-10-0225 — E6-01C draft process preview

- STATUS: DONE for STANDARD local preview scope. Whole PDF incomplete.
- CLASS / MODE: STANDARD / solo; completion target: local change.
- Task: `ai/tasks/2026-10-10-e6-01c-process-preview.md`; project: `ai/PROJECT.md`.
- Branch `fix/tours-search-quality`; base `735eaf3`; code
  `6af101f5b6482d8db7073d25d2975273f9ebeee4`. Evidence/report in next docs commit.
- Contract: `docs/e6-01c-process-preview.md`.

## Outcome

Reproducible versioned catalog with all 87 codes from PDF §§14.2–14.6/p63–66 and
71 draft edge variants, including two branches of U05→U06. Original rows/paragraphs,
sections/pages retained; flags separated from stages. Deterministic tri-state
condition evaluator and native admin selection/review/print screen, accessible
from the KG entry form. Every result stays hypothetical/unpublished/non-executable
and leaves the current stage unchanged. No application or ServiceCase integration
is implied; source-stated sequence does not approve formalized guards.

Positive/negative scenarios cover consent and current document acceptance, portal
verification/payment/submission/reference, eligibility, escalation, corrections in
the same attempt, refusal/new linked application, issuance/delivery/entry, separate
resident/registration applications and the L-versus-registration branch.

Strict catalog pin/version, detached immutable catalog, typed/bounded facts,
stale-form refusal, dedicated CSRF and existing full-admin/KG-OFF/workday gates.
No domain SQL in the preview, personal-data input, external requests or fact
persistence. Existing write flag may remain off. Dockerfile includes catalog.
Coverage/backlog/report builder updated; whole PDF still incomplete.

## Evidence

| Claim | Command/scenario | Environment/revision | Result | Limit |
|---|---|---|---|---|
| Source identity | SHA256 and PyMuPDF94 pages; source §§14.2–14.6 | Original local PDF, read-only | PASS | Preservation is not current legal verification |
| Draft behavior | `pytest tests/test_kg_process_preview.py` | Initial uncommitted local snapshot | PASS25 | Synthetic facts only |
| New HTTP + old knowledge view | Domain + `test_admin_kg_processes.py` + `test_admin_kg_knowledge.py` | Isolated working snapshot before final print spacing | PASS57 /1 warning /44.88s | No production |
| Native UI | `pytest tests/browser_kg_processes.py` | Isolated working snapshot, Chromium loopback, mobile390 + desktop1365 no JS | PASS2 /3 warnings /29.95s | Initial print hash overflow fixed afterward |
| Committed source identity | Git blobs/workspace/archive compare with LF normalization | Code `6af101f`, `runs/e6-01c-process-committed` | PASS19/19, no env files | Manifest `ai/reviews/2026-10-10-e6-01c-process-snapshot.json` |
| Cold imports | Separate Python processes: kg_processes, kg_entry, app.main | Exact committed copy, no env files | PASS, all exit0 | Import is not runtime acceptance |
| Compilation/structure/whitespace | py_compile, `tools/ai_protocol.py check .`, staged `git diff --check` | Code checkpoint | PASS | Protocol check tests structure only |
| Credential-shaped scan | Staged bounded literal regex over19 paths | Code checkpoint | PASS, zero matches | Not a full secret audit |
| Final related regression | Seven selected domain/HTTP/browser files, command below | Exact committed copy `6af101f`, synthetic SQLite/loopback Chromium, env absent | PASS130 /3 warnings /174.68s | No failures/skips; deprecation warnings only |
| Final print/mobile | Native selection, missing/false/met conditions, U registration branch, focus/overflow/no-JS, print extraction and visual check | Exact committed copy | PASS; print1 page, source/conditions/hash intact | Synthetic artifacts in ignored runs directory |
| Current PDF report | Offline builder + text checks + all5 rendered pages visually inspected | Current coverage, code `6af101f` | PASS5 pages,26/26 source headings and exact revision/checks | No new measured percentage |

Final command from `runs/e6-01c-process-committed`:

```text
python -m pytest tests/test_kg_process_preview.py tests/test_admin_kg_processes.py tests/test_admin_kg_knowledge.py tests/test_admin_kg_entry.py tests/test_admin_kg_applications.py tests/browser_kg_processes.py tests/browser_kg_entry.py -q --tb=short
```

Current report: `docs/reports/frunze-pdf-progress-2026-10-10-process-preview.pdf`;
SHA256 `631fd19340960abffaf6a5d558716d1626bfbf14c15d0d13530a1b22826d32e9`.
Browser screenshots/print: `runs/e6-01c-process-committed/runs/e6-01c-process-browser`.
No runtime source changes after the tested code commit; final follow-up is evidence/docs only.

Original source SHA256:
`141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.
Catalog LF SHA256:
`cc17f508dee484534b9667a0235402630db8848618450109f9bcd746b2d78a6c`.

## Review and remaining gates

Separate SELF_REVIEW: `ai/reviews/2026-10-10-e6-01c-process-self-review.md`, Codex
same context; solo permits this for STANDARD local preview. No independent review
claimed. SELF_REVIEW PASS for this local target with final evidence above.
Prior CRITICAL independent review/final audit/PG16 remain UNKNOWN.
DEC-02/06/07/08/11/12, real evidence bindings, full exceptions, legal timing,
publication and four executable workflows still remain. No new completion percent.

Full suite/traps/image build/PG runtime not rerun: no new migration, dependency,
storage or auth behavior. Prior baseline date failure in
`test_facts_live_errors.py::test_still_reads_a_plain_request` and traps
1 ERROR/57 WARN remain historical, not converted to current PASS. Image build and
production acceptance UNKNOWN; no deployment, env change, live migration or messages.

## Next action / resume

Start from STATE, this handoff, current contract and section coverage. Next useful
scope: source-backed required-document/checklist drafts on synthetic data, then
evidence bindings and approved process publication; do not turn preview answers
into actual application evidence. Resolve existing owner decisions before real
personal data, broadened access, money or executable policy. General redesign later.
Working-branch commits/push authorized. Preserve unrelated audio/archive/reports
and temporary untracked artifacts; never stage env files.
