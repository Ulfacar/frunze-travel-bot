# E6-30C — independent J02 source acceptance review

**Verdict: APPROVE for the fixed local J02 criterion, subject to the separate final audit.** No unmet J02 acceptance case was found in the three source goldens and the mapped uncertainty controls. This is not approval of J01, the whole PDF, real legal/source authority, activation, or release. No score or runtime file was changed.

Reviewer: `/root/publication_review`, independent of these scenario builders. Date: 2026-10-13. Mode: solo; parent CRITICAL review protocol. Requirement and actual source/tests were examined before the builders' conclusions. This pass independently checked retained XML, source identities and relevant changes; it did **not** execute another pytest/PG suite. The earlier independent deadline/component reviews remain separately identified.

## Requirement and frozen identity

The unchanged criterion in `docs/pdf-engineering-criteria.json` is J02, PDF Б.8: **“Golden intake/qualification scenarios and adversarial uncertainty cases.”** It requires meaningful intake/qualification outcomes and refusal under uncertainty. It does not substitute for J01's full connected SOP continuations or require automatic positive eligibility for every narrative.

- Original PDF: `runs/e6-30b-r16/runs/specialist-source.pdf`, SHA256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`. Б.8 is on physical pages 89–90; the earlier direct comparison with the complete source archive is retained. The text was reread for this assessment.
- Current target: `runs/e6-30c-r44`, base `0398bfdd372ecc9e946787913f5b849535075034`; all **42/42** manifest overlays independently hash-verified. Raw manifest SHA256 `6a18b59e6a5f01598558b9abd72b6cbf0a73c5642db66c733cc4a33628d182e3`.
- Current `tests/test_source_golden_connected.py`, normalized-LF SHA256 `08a55e7a46522e67b7c2e3845a0d8a68d70eb057e4d1b4c8e741bf453c16785f`.
- Reproducible, app-free evidence check: `python -X utf8 runs/e630c-j02-evidence.py` — PASS. Output `runs/e630c-source-acceptance-review/j02-evidence.json`, raw SHA256 `52bd71b6e544b576ca7f4af96377af73245b919b5c4e2ad3b3d7cf8d5ad9d06b`. It records 15 commit/file identities, eight further unchanged supporting files, eight AST correspondences, XML hashes and every testcase result. Historical XML hashes recorded in previous evidence manifests still match.

## Three source goldens

| Б.8 input and required distinction | Actual connected evidence | Assessment |
|---|---|---|
| **USA, tourism, 45 consecutive days.** The source's 30/60 regime cannot accommodate 45 uninterrupted days; do not silently issue another product or treat registration as permission. | R44 `test_b8_usa_45_days_english_intake_exceeds_short_regime_and_retains_uncertainty`: actual unsigned case, own saved profile, own stay history and English interview, then `connected_qualification.assess`. It asserts 45 inclusive days, window 60, `planned_stay_exceeds_allowance`, no selected regime/product, no quote and no entry-eligibility determination. Updating the same person's history to incomplete produces `personal_history_review_required` / `history_incomplete`, not empty-history approval. Function AST equals the executed R33 test. | **PASS.** This is an explicit specialist result with preserved uncertainty. Dates are deliberately adapted to 1 November–15 December 2026; this is not a May-effective legal approval. |
| **IND, ten-day company business meeting abroad.** Resolve material purpose/host/passport facts and the alternative residence/long-visa questions before the bounded B plan; documents and quote remain separate from permission. | Current committed `test_original_source_india_ten_day_decision_quote_reload_and_withdraw[ru/en]`: original-source import under synthetic reviewed policies; own case/applicant/profile/history/ACKed interview; closed, separately authorized specialist findings; saved ten-day internal decision and linked internal quote, reload and withdrawal. Quote totals are USD100 from the separately pinned synthetic recipe; source-fact tests retain pending invitation/company/documents and no automatic eligibility. The connected test AST equals executed E630B R13. | **PASS.** Both RU/EN paths exercise persistent services, not a product enum or hand-assembled answer. Residence/long-visa uncertainty is a refusal of this narrow capability. No automatic alternative seven-day route, client offer, price approval or processing-time guarantee is claimed. |
| **UZB, already in Bishkek for three weeks, garment employer.** Distinguish 60/120 stay arithmetic from permission to work, collect actual employer/HR facts, retain unknown TPP status, evaluate the separately authorized ten-working-day condition. | R44 `test_b8_uz_garment_exact_entry_employer_handoff_deadline_and_own_permit`: unsigned case, latest own actual-entry profile and open stay history; 21 elapsed / 22 inclusive days at 12 October; own typed `work_hire` interview and ACKs in bounded batches; factory and HR contact retained; TPP explicitly unknown. No fact authority gives no date. Under synthetic exact source/calendar/fact authority, due date is 5 November from the 19 November factual end, reported headroom 38. `requires_specialist=True`, `operational_action_allowed=False`, no quote, no work/stay permission. Own unified-permit application reaches W02 employer review; W03 refuses absent prerequisites. A subsequent business-purpose correction removes the date and preserves the old receipt. Function AST equals executed R18. | **PASS.** Unknown TPP membership is not a discount. The source's registration term 60 remains raw source text and is explicitly absent from executable registration values. The conditional date does not create a task or approve filing/employment. |

These flows call persisted production-domain services through synthetic test fixtures. Their case/applicant continuity, refusal reasons, changed current facts and immutable historical results are asserted. They do not claim free-text extraction or provider delivery of the sample dialogue itself; the installed dialogue boundary has its separate H02 review.

## Adversarial requirement mapping

| Uncertainty that must not become a positive answer | Inspected concrete controls and result |
|---|---|
| Unknown, obsolete or foreign-person history; payer inheritance; own passport mismatch | E628 `test_personal_history_gates_and_withdrawal`, `test_case_person_payer_isolation_and_profile_corruption`, and the new same-person USA incomplete-history mutation. Incomplete/withdrawn/overlapping/unconfirmed/open or mis-scoped evidence refuses; it is not silently treated as zero days. **PASS.** |
| Changed interview, consent, profile or purpose | E628 `test_interview_correction_consent_and_profile_change`; India changed-profile/old-ACK controls; actual UZ purpose change; independent deadline audit's current-head, missing purpose, tourism and consent-withdrawal-after-ACK cases. Historical receipts stay readable while fresh results refuse. **PASS.** |
| Incomplete source authority, stale source, overlapping manual/conditional regime | E628 authority/partial publication/source-expiry/competing-set tests; E629B's corrected literal manual-country guard with a rehashed but unsupported extra predicate. No absent/unknown guard becomes false. **PASS.** |
| A positive manual India decision ignores another material fact | Source-specific parameterized controls cover unknown/positive foreign residence and long visas, hidden profile alternatives, company creation, minor age, fines, missing/wrong host, purpose, damaged passport, previous visits, country, consent, event dates, family/count and inconsistent profile answers. Known nonqualifying visas are not rewritten as “no foreign visas.” **PASS.** |
| Source/recipe/capability substitution or foreign applicant quote | India source-census and applicability drift, fee-only/missing-regime/unreviewed-clause/recipe-scope/unknown-capability policies, wrong recipe and cross-person controls. Future evidence and nested quote-clock rollback refuse; valid equality and retained recovery remain covered. **PASS.** |
| UZ dates fabricated from a planned trip, null source value or wrong calendar | Work deadline audit covers source NULL remaining NULL, separately delegated exact ten-working-day interpretation, calendar trace, no DML/permission, publication withdrawal, current purpose/head and privacy changes. UZ fixture binds actual own open history and factual end. Unknown authority yields no due date. **PASS.** |
| Registration term mistaken for exemption or permission | E628 registration distinctions/manual unknowns and the UZ raw-60/non-executable-value assertions. **PASS.** |

## Actual retained execution evidence

The following are separate, overlapping executions; their counts must not be added as a new full-suite result. Durations below are the actual XML `testsuite.time`, not an inferred sum of testcase durations. All listed suites have zero failures/errors/skips.

| Artifact | Actual result and use |
|---|---|
| `runs/e6-28-r8/runs/e628-r8-core-compat.xml` | **54 PASS / 601.332s**: connected qualification and related source/scope/legacy controls; includes USA positive-short and 45-day rejection. |
| `runs/e6-29b-r6/runs/e629b-r6-guard-compat.xml` | **3 PASS / 96.637s**: changed shared source guard and valid connected assessment. |
| `runs/e6-29b-audit-r6/runs/e629b-audit-r6.xml` | **1 PASS / 37.814s**: separate auditor's actual-PG literal manual guard attack. This pass only read the retained artifact. |
| `runs/e6-30b-r13/runs/specialist-final-core.xml` | **48 PASS / 647.461s**: source-specific India positives/negatives, connected internal decision/quote, native/browser/schema evidence. |
| `runs/e6-30b-audit-r16/audit-quote-clock-r16.xml` | **2 PASS / 127.744s**: separate auditor's corrective nested-clock controls. |
| `runs/e6-30b-r16/runs/specialist-clock-postgres.xml` | **2 PASS / 134.034s**: actual-PG corrective clock controls; no new PG use by this review. |
| `runs/e6-30c-r18/runs/source-uz-r18.xml` | **1 PASS / 64.944s**: exact UZ connected golden described above. |
| `runs/e6-30c-r33/runs/aftercare-promoted-usa-r33.xml` | **12 PASS / 229.064s**: one strengthened USA golden plus eleven separate aftercare checks. Only the relevant USA identity is used for J02. |
| `runs/e6-30c-deadline-audit-r9/audit-deadlines-r9.xml` | **3 PASS / 111.539s**: independent source/calendar/current-fact deadline controls. |

The R44 renewal XML also exists and independently parses as **1 PASS / 342.844s**. It corrects the earlier R43 dependent-batch fixture failure. It is recorded in the evidence JSON, but is **not** counted toward J02 or used to close J01.

## Correspondence and its limits

The current connected assessment, policy and interview reconciler are byte-identical to reviewed commit `9bd6e926d4649b4d57152e0ce07491353767bc7f`. `assessment_rules.py` and its extended fixture are identical to `9b60f51421b9466b6e22e4c5679407e0273486a2`: the actual diff extracts the shared source check and closes the unsupported manual-regime predicate loophole; the default old fixture and goldens keep their meanings.

The current current-stay reader is identical to `e08338b1db4df887a54ccc4efc6c2661d7072738`, not the older E629B reader. Its inspected later diff introduces a separately authorized dialogue reconciliation entrypoint. The ordinary entrypoint used here retains exact current-head checks with no dialogue session argument. It is also byte-identical R18→R44. No blanket “all dependencies unchanged since E628” assertion is made.

The six specialist domain modules and the two source/connected test files match reviewed commit `14583342ff53c099d720af4e52e59071510bfde9` exactly. R13→current specialist runtime differs only by the nested quote timestamp ordering check in `specialist_decisions.py`; the later R16 corrective artifacts above cover that change. It does not relax the India source or fact gates.

The current `work_deadlines.evaluate_in_session` calculation body is AST-identical to the nested reader actually executed in R18. The wrapper extraction/preflight behavior was independently reviewed with the later work-review adapter. Shared deadline/profile/history/interview fixtures and source policy/rules match R18. `open_case`, the work test fixture, and work attestation/transition helpers have matching ASTs. Later `entry_processes.py` changes add reviewed current RES/REG dependency observations on read; its operation writer and W02/W03 gates are unchanged. The UZ test has neither linked resident nor registration objects, so it does not exercise those new observation branches.

## Remaining scope and disposition

No additional case is required to establish the **fixed J02 intake/qualification** outcome. A seven-day alternative visa route, a promised client SLA, actual messaging, automatic work approval, every SOP tail, actual registration-period anchors and operational deadlines must not be inferred from these tests. Those are separate capabilities/acceptance gates; several remain active under J01. The new unwired entry-anchor implementation was not reviewed here.

All approvals and personal facts in these executions are synthetic, local and explicitly supplied. Real source/business authority remains unapproved; owner acceptance/J05 remains separate. Prior original failures stay preserved, and no existing evidence was rewritten as a success.

**Independent scoped disposition: J02 APPROVE / requirement evidence PASS.** Separate final audit remains required before the parent changes the criterion's review state. Whole-PDF status and J01 are unchanged by this report.
