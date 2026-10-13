# E6-28 independent review — APPROVE

Reviewer: `/root/calculation_review`, 2026-10-12. CRITICAL / solo.
Requirement: `ai/tasks/2026-10-12-e6-28-connected-qualification.md` and the
source-first `2026-10-12-e6-28-pre-audit.md`. This report approves the exact local
implementation and judges the fixed C05 technical acceptance below. It is not
a production, source/legal approval, or an edit of the score ledger.

Final review status: **APPROVE** for the R8 runtime exactly mapped to final R9
and current root. R5 was FIX_REQUIRED; all confirmed findings are corrected and
the original positive/negative controls pass. Eleven final independent controls
pass, and completed builder core, compatibility, actual PostgreSQL and native
browser evidence is reconciled below. No confirmed runtime defect remains.
The separate final audit is still a distinct required protocol gate.

## Scope and inspected design

The chosen matrix is internal NO_VISA regime selection for a current adult,
ordinary-passport, individual, single-entry tourism plan abroad. A current
complete same-passport personal journal and complete ACKed interview are
required. Other purposes and circumstances return explicit uncertainty or
specialist referral. Business B selection and full golden scenarios are not
claimed by this matrix.

Reviewed actual authority, rule interpretation, interview bridge, connected
service and protected native route/template before test conclusions. The
connected authority is separate, immutable, server-owned and empty by default.
Its full VF/VR/SP set and exact source pins support explicit manual exclusions;
true/unknown manual applicability cannot select. Counting remains a separately
approved interpretation around the unchanged review-only arithmetic. The
connected service composes validated personal profile/history/interview and
publication reads in one transaction, under case → applicant → publication
locking. It never saves a calculation against payer history.

The native route is GET-only, behind the existing full-admin/case gates, refuses
query-supplied authority, returns no-store content and keeps internal counts,
registration status, source references and referral messages separate. Native
runtime/browser evidence is recorded below.

## Confirmed findings and correction record

1. **Hard-deadline field mismatch (R2 source inspection; shared finding).**
   `assessment_interview` checked `profile.deadline`, although v2 uses
   `urgency_deadline`. Root independently found/fixed this before the reviewer's
   runtime confirmation. The original R2 runtime attempt never reached assess:
   all three tests failed in the immature fixture publication step. Do not
   present that attempt as a reproduced runtime defect. Corrected R5 normal
   save/history/full interview/ACK controls pass for no deadline, a future
   deadline and a past deadline; known dates contradicting interview
   `hard_deadline.exists=False` cannot select.

2. **Unmapped material purpose detail selected NO_VISA (confirmed R5).**
   Valid normal save of `purpose=tourism` plus
   `purpose_details='Synthetic plan: paid employment at a sewing factory.'`,
   followed by a matching complete tourism interview/ACK, returned
   `qualified_recorded_plan`, `selected_product=NO_VISA`, `reasons=[]`.
   The service ignored the additional recorded purpose rather than requiring
   reconciliation. Root added an explicit source-authority-pinned PROFILE_MAP,
   with material purpose/event/other unsupported fields causing referral.
   No free-text classification is required to detect that the narrow supported
   scope has unhandled material facts.

3. **Nested ban date ignored (confirmed R5).**
   Valid normal save of `violations.deportation_or_ban=False` together with
   `violations.ban_until='2027-01-01'`, while interview risk flags were false,
   also returned qualified NO_VISA with no reasons. Merely marking the whole
   `violations` object as mapped was insufficient. Root added a nested map and
   an explicit known-ban-date guard. The same ordinary-flow regression and
   positive control pass on R7, whose corrected path is unchanged in R8/R9.

Original probes and archives are preserved; runtime source was never edited
by this reviewer. The residence-country improvement and suppression of
unapproved registration counts were inspected as builder corrections, not
claimed as reviewer-discovered runtime failures.

## Independent evidence

All runs use env-free Git archives of
`30b12b1097ddbd8c74a2d54bf38cec1a98647553` with frozen manifest overlays.
No `.env`, live service, real data, outbound message or PostgreSQL was used by
this reviewer. SQLite runs use the existing hermetic fixtures and actual
domain APIs. Only one own suite runs at a time.

| Snapshot / command | Actual result | Meaning |
|---|---|---|
| `runs/e6-28-review-r2`, own `test_review_assessment_negatives.py` | 3 FAIL, 36.76 s | Fixture-only `publication_rules_unavailable`; no assess call and no runtime defect conclusion |
| `runs/e6-28-review-r5`, same file before later probes | 3 PASS, 92.72 s | Full-source positive and corrected future/past urgency contradiction controls |
| R5 `-k 'adversarial_heads or ack_correction'` | 2 PASS, 99.60 s | Eight adverse personal-history heads, recovery and withdrawal; ACK correction/restore and consent-withdrawal latch |
| R5 `-k unmapped_profile` | 1 FAIL, 33.54 s | Normal-flow purpose-detail false positive, finding 2 |
| R5 `-k nested_ban` | 1 FAIL, 33.97 s | Normal-flow nested-ban-date false positive, finding 3 |
| `runs/e6-28-review-r7`, all seven own tests with JUnit `review-r7-controls.xml` | 7 PASS, 246.47 s | Corrections plus the original positive/adversarial controls |
| `runs/e6-28-review-r8`, own `test_review_registration_delta.py`, JUnit `review-r8-registration.xml` | 3 PASS, 108.84 s | RUS full-source positive; MDA blocked exemption despite TERM90; UZB DEFAULT obligation despite TERM60; no actual registration/deadline |
| R8 same own file, `-k complete_in_kg`, JUnit `review-r8-in-kg.xml` | 1 PASS, 20.85 s | Normal saved complete in-KG profile has no missing facts and returns explicit scope referral, no selected product/visa requirement |

The history sequence checks unconfirmed and unknown-basis evidence, known
non-VF basis, different country/passport, open visit, closed boundary overlap,
and disagreement with the interview; each asserts its expected reason instead
of accepting any generic fallback. Restoring valid empty history selects
NO_VISA again, then withdrawal blocks selection. The ACK test changes age,
asserts `interview_changed_after_ack`, restores the acknowledged fact and checks
positive selection, then withdraws consent and checks its persistent block.

R7 manifest contains 19 overlays. Its normalized-LF SHA256 is
`26cf8081ef7b3cb07181c13d8e24f8e09b2468fc1a02de350a24ce77ce3b4ad7`.
Own archive verifies every listed file hash. Evidence is scoped to that
snapshot unless a later exact delta is separately mapped.

Read-only byte comparison confirms unchanged old route, interview reducer,
interview domain, personal-history domain, arithmetic/schema and saved
calculation files. AST comparison of `knowledge_publication.py` confirms the
only change is optional `at` and selection of that timestamp instead of `_now()`;
the prior default behavior and locking code remain unchanged.

R8 has 20 overlays and normalized-LF manifest SHA256
`0b48da35cad1f5d84697dba58527ce6a1d59672f7d264a0062c65cba9c6383c0`.
All own archive hashes were verified. Exact R7→R8 runtime diff is only the early
`registration.status=requires_review` return: it preserves blocked/missing/
conflicting registration reasons and cannot select or compute an allowance on
that branch. The original seven controls remain on unchanged paths; the three
independent R8 controls exercise the delta plus a positive control. All R8→R9
runtime hashes are identical and current root runtime hashes match R8.

The final R9 manifest has normalized-LF SHA256
`a73c351149923f3f03a4ad7424aece68e5ba30be00dbe0a0cf9d6e35658f3e26`.
At final review, all 13 manifest-listed `app/` files independently match root.
The base remains `30b12b1097ddbd8c74a2d54bf38cec1a98647553` plus the explicit
uncommitted overlays. Preserved unrelated base/board UI edits are not claimed
as this reviewer's changes.

Additional builder evidence was inspected as artifacts, not counted as the
reviewer's own executions:

- `runs/e6-28-r8/runs/e628-r8-core-compat.xml`: **54 PASS, 601.332 s**, zero
  failures/errors/skips, independently parsed after completion. This comprises
  17 connected assessment cases, 29 prior approved-route cases, three condition
  controls, three source-integrity controls and two actual legacy-profile
  compatibility cases. The source-shaped positives retain all 18 VF/VR/SP
  regimes and cover empty/nonempty history, 60/120/180-day windows, old days
  leaving the window, planned overflow/margin, and registration distinctions.
  The ordinary existing Starlette deprecation warning does not change the
  result. This is completed evidence, not the earlier running-suite claim.
- `runs/e6-28-r7/runs/e628-r7-native-pg.xml`: **5 actual PostgreSQL writer-lock
  cases PASS**, for profile/history/interview/publication withdrawal/review.
  The test observes `pg_stat_activity.wait_event_type='Lock'`, a coherent
  positive before the blocked writer, and the expected refusal after it.
  The combined run was **5 PASS / 1 FAIL, 233.043 s**: its later native test
  incorrectly forbade the existing global logout form. This failed assertion
  was fixed test-only to inspect the assessment's main content; it is not hidden
  or counted as a passed native check.
- `runs/e6-28-r9/runs/e628-r9-native-browser.xml`: **5 PASS, 127.266 s**, no
  skips/errors. Three native/schema checks and actual Chromium RU 390px dark /
  EN 1365px light with JavaScript disabled. Source inspection confirms checks
  for full-admin/query/body authority gates, no-store failures, publication
  withdrawal, horizontal overflow, keyboard focus, text/link contrast ≥4.5,
  and extracted PDF text. Reviewer independently opened the generated mobile
  positive/fallback screenshots and EN print image: readable labels and
  warnings, intact counts/registration/source text, no visible clipping.
  Both generated PDFs were independently checked with PyMuPDF and contain
  exactly one page each.

The actual PG lock path and positive/refusal path are unchanged in R8; its new
early registration branch only returns a more specific refusal while retaining
the same enclosing transaction/locks. This is an explicit evidence mapping,
not a claim that the reviewer reran PostgreSQL.

## Fixed C05 requirement judgment

Fixed acceptance is unchanged: **Product/regime qualification using approved
versioned rules and explicit uncertainty**, PDF blocks 1/2/4/8, weight 2.
The chosen matrix was written before final acceptance and is explicit above.

**The demonstrated matrix is sufficient for C05's technical regime
qualification acceptance, subject to the separate final audit.** It performs
an actual NO_VISA selection for the recorded personal plan after all required
checks, and changing personal stay facts changes that selected conclusion.
It is not only a route candidate, pure day arithmetic, renamed status or an
always-referral service. All 18 source regimes remain accounted for; difficult
manual regimes are excluded only by separately pinned applicability authority
and proved facts. Unknown or applicable manual regimes cannot produce the
selected result. The implementation therefore meets both the substantive
regime and explicit-uncertainty parts of the fixed acceptance.

| Required behavior | Evidence and conclusion |
|---|---|
| Versioned, approved, complete competing rules | Separate immutable assessment authority binds qualification policy, source/unit hashes, interpretation and profile/interview maps. Full 18-regime positive fixture, missing-authority/coverage/hash/date negatives and publication withdrawal controls PASS. Real authorities remain empty. |
| Personal whole-trip qualification, PDF 2.1 steps 1–8 | Full-source empty and nonempty history selects NO_VISA; 60/120/180-day regimes, days leaving the window, excess and margin change/refuse the selected result. Latest same-person profile/history/interview are pinned. Own adverse history, restore and withdrawal controls PASS. |
| Registration contributes to the conclusion | RUS exemption positive; trip over exemption, UZB DEFAULT obligation and MDA blocked exemption despite TERM90 refuse selection with exact reasons. Own three R8 controls PASS. Term, exemption and actual deadline stay distinct. |
| Stops and uncertainty, PDF 1/4 | Business needs B mapping/specialist; work, special passport, family, in-KG, material purpose/ban/event details and legal flags have explicit referrals. Builder source matrix and own complete in-KG control PASS. No missing-facts shortcut was used for the in-KG case. |
| Reconciled typed interview and personal evidence, PDF 8 | Fresh complete ACK, dependency/profile/history agreement and consent are required. Own age correction/restore, withdrawal, urgency contradiction and history conflict controls PASS. Material unmapped profile fields cannot be ignored. |
| Coherent protected current read | Five actual PG writer-lock cases PASS; old lock path unchanged. Scope/payer isolation and corruption controls in completed core/native suite PASS. GET-only full-admin native adapter refuses client authority, does not write and returns no-store failures. |
| Reviewable result and compatibility | RU/EN mobile/no-JS/print browser evidence PASS; own visual/PDF inspection completed. Internal regime, source pins, duration, registration and reasons remain separate; old route tests and archived-profile compatibility PASS; old arithmetic/interview/history algorithm bytes unchanged. |

This judgment does **not** claim substantive B selection. The fixed criterion
permits regime qualification with explicit uncertainty; it does not say that
every visa product must be automated. India/business gets the explicit
`business_mapping_requires_specialist` result, not an invented B outcome.
Routine B selection requires its own source-bound mapping, inviter/material
facts and positive control; B.8 business/all-product golden coverage and
J01/J02 remain unproved by this task. That limitation is not hidden by the
C05 judgment. Likewise USA 45 days is an overflow/referral case, not approved
visa-free travel or a proven alternative visa selection.

No actual source, counting interpretation, registration policy or owner
approval has been fabricated. Synthetic approval proves executable engineering
behavior; it does not authorize live operation. Pure arithmetic remains
`review_only`; `may_quote=False`, no border-admission conclusion and no actual
registration deadline are preserved. Production, delivery, all-PDF completion,
all-product automation and commercial authorization are outside this approval.

Final disposition: **APPROVE reviewed local E6-28 change; C05 technical evidence
sufficient under the stated fixed criterion; separate final audit required
before the parent records completion.** No additional runtime fix is requested.
