# HANDOFF: 2026-10-10-0300 — E6-02A document checklists

- STATUS: DONE for this STANDARD local slice. Entire PDF and E6-02 incomplete.
- CLASS / MODE: STANDARD / solo; completion target: local change.
- Branch `fix/tours-search-quality`; base `1747d0c`; code
  `1d3372ed7116d99a13b1ef989c9d0c31c5d248a5`. Evidence/report follow in docs commit.
- Task `ai/tasks/2026-10-10-e6-02a-document-checklists.md`; project `ai/PROJECT.md`;
  contract `docs/e6-02a-document-checklists.md`.

## Outcome

All23 matrix rows ×9 product columns from PDF §5.2, with original cells/symbols,
notes and pages36–37 in a pinned reproducible catalog. Mixed mandatory/recommended
cells split; dash annotations retained. Full §§5.1–5.5/11.4 source supplements
available for review. Other visa types remain source text, not invented matrix columns.

Native CRM form with explicit conditional applicability, unknown/missing/received/
correction/checked states and current-version confirmation. Received is not verified;
changed/unknown version requires review again. Source `[ПРОВЕРИТЬ]` cannot be cleared
through answers. Every result denies package acceptance/publication/submission;
supplementary source requirements are explicitly outside automatic assessment.

Existing full-admin/KG-OFF/workday gates, dedicated CSRF, bounded whitelist forms,
stale/corrupt source rejection, no personal fields/upload/domain writes or answer
persistence. Product switch resets the scenario. Mobile/no-JS/print; links from
the entry form and process preview. Dockerfile includes catalog; no build claim.
Coverage/backlog and PDF report builder updated. No migration/deployment/messages.

## Evidence

| Claim | Scenario/command | Environment/revision | Result | Limitation |
|---|---|---|---|---|
| Source identity | Original SHA256 + physical matrix pages36/37 + source rows/cells/supplements | Read-only original94-page PDF; derived source | PASS | Not current legal verification |
| Source/evaluator | `pytest tests/test_kg_document_checklist.py` | Initial uncommitted root, pure functions | PASS23 /0.43s | Synthetic review only |
| New local flow | Domain + HTTP + browser new files | Isolated working snapshot, synthetic SQLite/loopback Chromium | PASS44 /3 deprecation warnings /46.55s | Before final summary/print/screenshot refinements |
| Exact snapshot | Git blobs/workspace/archive compare after LF normalization | Code `1d3372e`, `runs/e6-02a-documents-committed` | PASS20/20, env files absent | Manifest `ai/reviews/2026-10-10-e6-02a-documents-snapshot.json` |
| Static/packaging | py_compile, protocol check, staged whitespace, explicit Docker COPY | Code checkpoint | PASS | No Docker image build |
| Token-shaped text | Regex over20 staged paths | Code checkpoint | PASS0 matches; no env paths | Not a full secret audit |
| Final related regression | Eight selected domain/HTTP/browser files, command below | Exact code copy `1d3372e`, synthetic SQLite and loopback Chromium | PASS121 /3 deprecation warnings /182.03s | No selected-file failures or skips |
| Cold imports | Separate processes: kg_documents, kg_processes, kg_entry, app.main | Exact committed copy, no env files | PASS, all exit0 | Not production runtime acceptance |
| Native/print acceptance | Mobile390 + desktop1365 no-JS, current-version invalidation, reset, focus/no overflow, PDF text and visual checks | Exact committed copy | PASS; final print2 pages, both inspected | Synthetic documents only |
| Current progress PDF | Offline builder + text checks + all5 rendered pages inspected | Current coverage with code `1d3372e` | PASS5 pages;26/26 source headings, revision/checks and30/70 estimate | Expert estimate, not measured requirement fraction |

Final command from `runs/e6-02a-documents-committed`:

```text
python -m pytest tests/test_kg_document_checklist.py tests/test_admin_kg_documents.py tests/test_admin_kg_entry.py tests/test_admin_kg_processes.py tests/test_admin_kg_knowledge.py tests/browser_kg_documents.py tests/browser_kg_processes.py tests/browser_kg_entry.py -q --tb=short
```

Report: `docs/reports/frunze-pdf-progress-2026-10-10-document-checklists.pdf`;
SHA256 `880308dd0755c93d03e98924520db53c45a91a9b5e3d405f1cfa51d8884c7534`.
Synthetic screen/print artifacts: `runs/e6-02a-documents-committed/runs/e6-02a-documents-browser`.
No runtime changes after the tested code commit; final follow-up is evidence/docs only.

Source SHA256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.
Catalog LF SHA256 `81ebf0f41aec18ebe8ada37d3d709fd73114eea250718fc4b66abb63e22b1c6f`.

## Review and limitations

Separate SELF_REVIEW by Codex (same author/context):
`ai/reviews/2026-10-10-e6-02a-documents-self-review.md`. This is permitted for
STANDARD solo local target; SELF_REVIEW PASS with the final evidence above.
Independent CRITICAL review/audit/PG16 remain UNKNOWN.
No new business/privacy/access/storage policy; DEC-04/05/06 and previous release
gates remain open. Real applicant document inventories, files, consent, complete
conditional supplements, acceptance, delivery and operational processes are not done.

No full-suite/traps/build rerun for this isolated no-storage slice. Historical
tour-date failure in `test_facts_live_errors.py::test_still_reads_a_plain_request`
and traps1 ERROR/57 WARN stay historical, not current PASS. Production acceptance
UNKNOWN. Unrelated untracked audio/archive/reports/temp artifacts preserved.

## Current percent / resume

User asked progress: working estimate **about30% complete /70% remaining** for
the entire inbound PDF+CRM engineering scope. Rounded expert judgment, not a
completed-requirement fraction, page coverage, test ratio or launch readiness.
Last historical range20–30% is not a precise earlier measurement. Big remaining
blocks are real processes/documents, dialog/handoff, approved knowledge/calendars/
prices, integrations and end-to-end acceptance.

Next: per-applicant checklist and evidence design under existing consent/storage
decisions; independently review prior CRITICAL foundations and exercise PG16 before
real workflows. Do not convert hypothetical answers into accepted document facts.
Context: STATE, this handoff, contract, full PDF coverage, E6 backlog. General
redesign later. Working-branch commit/push authorized; production release is not.
