# E6-30C — separate final audit of fixed J02

**GO / PASS for reviewed local J02 only.** The fixed criterion is **“Golden intake/qualification scenarios and adversarial uncertainty cases”**, original PDF Б.8. All three source situations have substantive connected outcomes and uncertainty controls. No open defect was found in this criterion's reviewed scope. This does not close J01, J03, J05, the whole E630C task, or the full PDF.

Auditor: `/root/e622_audit`; independent of the scenario builder and `/root/publication_review`. Date: 2026-10-13. CRITICAL / solo / reviewed local change. The task, pre-audit, original PDF, scenario code and relevant actual services were inspected before reading the peer's conclusions. No runtime/source/configuration, score, real record, production service or owner policy was changed by this audit. No PostgreSQL process was started.

## Source, target and reproducible identity

- Requirement: `docs/pdf-engineering-criteria.json`, J02; task `ai/tasks/2026-10-13-e6-30c-source-acceptance.md`; the exact Б.8 section of `ai/reviews/2026-10-13-e6-30c-pre-audit.md`.
- Original PDF SHA256: `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`. Physical pages 89–90 were directly reread and extracted to `runs/e6-30c-work-task-audit-r44/runs/audit-b8-original.txt`. Source text is the requested technical oracle, not approval of current immigration law or prices.
- Frozen target: `runs/e6-30c-r44`, base `0398bfdd372ecc9e946787913f5b849535075034`; manifest normalized-LF SHA256 `122637da5368c31ba2f0376626a5df866347fb9f0c80e616914ae8e7377df40c`. All **42/42 overlays** were independently verified against the manifest and the auditor's env-free archive.
- Scenario file: `tests/test_source_golden_connected.py`, normalized-LF SHA256 `08a55e7a46522e67b7c2e3845a0d8a68d70eb057e4d1b4c8e741bf453c16785f`; root, R44 and own archive match. This is the reviewed new scenario file, still awaiting the parent's separate save packet at audit time.
- Independently checked **15 historical commit/file correspondences**, the three USA/UZ/India test-function AST correspondences, and **19 relevant runtime files** against R44, the current root and saved commit `5e91ddb2b85563c331f43f24351befd1a255d31a`. New D worktree models/anchors and unrelated UI were excluded.
- App-free verification command, from own archive: `python -X utf8 runs/audit_j02_evidence.py`. Result **PASS**. Its machine-readable file is `runs/e6-30c-work-task-audit-r44/runs/audit-j02-evidence.json`; it records the source, manifests, commit/file hashes, parsed XML cases and own execution result. It independently checks the peer inventory's actual files; it does not treat the inventory's status text as proof.

## Own exact-R44 execution

Environment: fresh Git archive plus hash-verified R44 overlays and the pinned original PDF, synthetic SQLite databases with fixture-enforced foreign keys. No root application import, `.env`, provider, live data or network operation. The inherited directory name `work-task-audit-r44` does not expand this J02 verdict to the adapter or other tasks.

Command, cwd `runs/e6-30c-work-task-audit-r44`:

```text
python -X utf8 -m pytest tests/test_source_golden_connected.py 'tests/test_specialist_decisions.py::test_original_source_india_ten_day_decision_quote_reload_and_withdraw[ru]' -q --tb=short --junitxml=runs/audit-j02-goldens-r44.xml
```

**3 PASS, zero failures/errors/skips, 152.498s XML duration; process exit 0.** One existing FastAPI/Starlette test-client deprecation warning. XML: `runs/e6-30c-work-task-audit-r44/runs/audit-j02-goldens-r44.xml`, raw SHA256 `0c8aee7ae078bf82913ba7310ef3fc831f2c31c59de99190cdbcdb6de131faca`. These are the auditor's fresh executions, distinct from the retained runs below.

| Source situation | Verified actual path and result |
|---|---|
| USA, ordinary tourism, 45 consecutive days | A real unsigned preliminary case becomes the case used for the same applicant's saved profile, complete personal history and English typed interview. Connected assessment returns `planned_stay_exceeds_allowance`, 60-day window, no product/regime selection, quote or entry decision. A second actual history revision marking the history incomplete changes the finding to explicit personal-history review, rather than silently counting zero days. **PASS.** |
| India, ordinary adult, ten-day company meeting abroad | Original-source import under explicit synthetic authority; own profile/history/application, actual saved interview and manager ACK, separately authorized host/purpose findings, then persistent specialist decision → internal quote → reload → withdrawal. The actual decision retains ten days; the linked quote totals USD100 under the synthetic recipe. Withdrawal prevents fresh quote use; original decision and quote commands still return the same immutable receipts with current policies absent. **PASS.** |
| Uzbekistan, already in Bishkek for three weeks, garment employer | Own exact entry/profile and open history, factory and HR facts collected through actual typed interview corrections and ACKs. Unknown TPP membership stays unknown. With no fact authority there is no date. With separately pinned source/calendar/facts, the helper yields 5 November from the 19 November actual-end evidence, 38 inclusive days of current headroom, specialist review and no work/stay permission or quote. Own unified-permit application reaches W02; W03 rejects missing employer prerequisites, and no fake visa is linked. Changing purpose removes the conditional date while the earlier process receipt remains readable. **PASS.** |

The USA dates are explicitly **1 November–15 December 2026**, not a claimed May-effective authorization. This preserves the 45-consecutive-day source question with a coherent synthetic authority interval; it does not infer a year or exact dates from the literal “in May” narrative. The fixed J02 judgment concerns clarified structured intake and qualification. Literal sample-message extraction, a word-for-word bot answer, provider delivery and a May-specific legal answer are **not demonstrated by this file** and are not represented as PASS. The pre-audit's warning against applying a 2026-only grant silently to May 2027 remains intact.

## Adversarial coverage and retained evidence

Inspected current code and actual test oracles, not just test names:

- Connected qualification requires the current own-person profile/history, full competing-regime census, exact source authority and reconciled interview. Missing/withdrawn/stale history, passport or scope conflicts, prior occupied days, unknown alternative basis, corrected material answers, consent withdrawal and unavailable publication cannot become a positive empty-history result. The shorter USA trip is an existing positive control; the new 45-day case does not replace it.
- India source-specific reconciliation rejects hidden or unknown qualifying residence/long-visa alternatives, incompatible purpose or host, in-country/medical/renewal scope, material profile contradictions, future evidence, unsafe handoff, changed source census and unreviewed or substituted capability/recipe. A known nonqualifying visa is not falsified as “no visas.” Ten days is not reduced to the seven-day alternative. Pending host/company/document requirements and legal eligibility remain distinct from the internal arithmetic.
- The work-deadline helper keeps the draft source NULL unchanged and requires its separate exact interpretation, factual own stay end and complete pinned calendar. Missing source/fact/calendar, changed current purpose/head, publication withdrawal and privacy after ACK remove the usable date. It does not use the five-working-day lower-bound helper as an exact ten-day calculation.
- UZ's raw registration term 60 is not an exemption: the source exemption remains NULL and the term is not inserted into the executable visa-free value. Garment work and an unknown TPP fact confer no discount or permission.

The following retained XML files were independently parsed, hashed and checked against their recorded identities. These overlapping runs are **not a new combined/full-suite count**:

| Artifact | Verified result / use |
|---|---|
| `runs/e6-28-r8/runs/e628-r8-core-compat.xml` | 54 PASS / 601.332s; connected positive, history, scope, source, consent and legacy controls. |
| `runs/e6-29b-r6/runs/e629b-r6-guard-compat.xml` | 3 PASS / 96.637s; corrected manual-regime guard plus valid assessment. |
| `runs/e6-29b-audit-r6/runs/e629b-audit-r6.xml` | 1 PASS / 37.814s; earlier independent actual-PG manual-guard attack. No new PG execution here. |
| `runs/e6-30b-r13/runs/specialist-final-core.xml` | 48 PASS / 647.461s; India RU/EN, source/fact negatives and connected decision/quote. |
| `runs/e6-30b-audit-r16/audit-quote-clock-r16.xml` | 2 PASS / 127.744s; earlier auditor's corrected nested quote chronology. |
| `runs/e6-30b-r16/runs/specialist-clock-postgres.xml` | 2 PASS / 134.034s; corresponding actual-PG correction. |
| `runs/e6-30c-r18/runs/source-uz-r18.xml` | 1 PASS / 64.944s; earlier exact UZ golden. It was also rerun fresh in this audit. |
| `runs/e6-30c-r33/runs/aftercare-promoted-usa-r33.xml` | 12 PASS / 229.064s; includes one strengthened USA case, separately rerun here. The other eleven cases are not claimed as J02 goldens. |
| `runs/e6-30c-deadline-audit-r9/audit-deadlines-r9.xml` | 3 PASS / 111.539s; independent source, calendar, no-DML, current-purpose and privacy controls. |

The R44 renewal XML was additionally verified by the collector but is excluded from J02 acceptance. No pending all-products/SOP run or new D anchor implementation is needed or borrowed as evidence for this criterion.

Historical corrections are not hidden by these passes: E628's ignored material purpose/ban evidence, E629B's manual-source narrowing, E630B's original native/integrity and nested-clock defects, and the deadline reader's ignored current interview purpose retain their earlier failing artifacts and corrective reports. This audit found no new J02 failure. It does not relabel earlier harness failures as runtime findings or older artifacts as fresh R44 execution.

## Separate review and disposition

After source/code assessment, read `ai/reviews/2026-10-13-e6-30c-golden-acceptance-review.md`: **independent J02 APPROVE**, normalized-LF SHA256 `73e7c162fe7c83718adbd0c2fb1f374adab485fa0c6eb38a345457d71d4a1f67`. Its substantive source, identity and uncertainty conclusions agree with this audit. Its lack of a new pytest execution is explicit; the fresh three-case execution above supplies separate auditor runtime evidence.

**Final scoped disposition: J02 technical acceptance PASS and separate final-audit GO for the reviewed local change.** The parent may save the exact reviewed scenario/evidence packet and reconcile that single fixed criterion. No score or criterion JSON was edited by this auditor. J01's full source SOP coverage, J03's affected-project audit, J05/owner acceptance, real source/calendar/tariff approval, activation, messaging and deployment remain separate. The full CRM/PDF is not certified complete.
