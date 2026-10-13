# E630D — conditional deadline integration independent review

Independent CRITICAL implementation review by `calculation_review`, 2026-10-13. **APPROVE — bounded domain implementation at exact R20: the original twelve rules reviewed at R19 and the five separately reviewed source-clause additions below.** All eight confirmed conditional-domain findings are closed by inspected changes and corrective evidence. This is not whole-D, J01, source/legal approval or release approval. The earlier bounded R2 anchor-stream review remains separately recorded in `2026-10-13-e6-30d-anchor-initial-review.md`. Native acceptance, actual PostgreSQL capacity/concurrency/recovery and separate final audit remain separate gates.

Requirement/source-first assessment covered the task, original PDF §13.2 and §19.9–19.12, the remaining-deadlines pre-audit, actual conditional rules/policy/source/evidence/service, and the adjacent legacy deadline/task paths. Original PDF SHA256: `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.

The review uses own env-free Git archives and synthetic SQLite records. Root implementation and tests were not edited or imported; no private environment, production data, provider, PostgreSQL or release action was used.

## Frozen identities

- Original target `runs/e6-30d-r4`, own copy `runs/e6-30d-conditional-review-r4`, 54 verified overlays, manifest LF SHA256 `850f43bd26bcebd0c9285c77a340536f4b8d13a15d621c66d09635d9ee79399e`.
- Corrective target `runs/e6-30d-r6`, own copy `runs/e6-30d-conditional-review-r6`, base `5e91ddb2b85563c331f43f24351befd1a255d31a`, 59 verified overlays, manifest LF SHA256 `2110a06aa84553c3e5eace6ad6eb3575ab8bb7ee938862bef0cf6de52a4e1dcc`.
- Renewal/source target `runs/e6-30d-r8`, own copy `runs/e6-30d-conditional-review-r8`, 59 verified overlays, manifest LF SHA256 `ffaee59607ee524534274247295971af757e4a33cfb4a952c6505cd7060626c0`.
- Next correction `runs/e6-30d-r10`, own copy `runs/e6-30d-conditional-review-r10`, 61 verified overlays, manifest LF SHA256 `502f7e41d034f592bc1d09b56be01b7835709cd8d5b4dabf731e49e6d4067be1`.
- Corrective R14, own copy `runs/e6-30d-conditional-review-r14`, 59 verified overlays, manifest LF SHA256 `db9b2a9f54002e5a51acab32fb1e4c7cc163ff47ac7ccf5465a7c9cc34b8620e`.
- Final delta under review R16, own copy `runs/e6-30d-conditional-review-r16`, 59 verified overlays, manifest LF SHA256 `05ca620b1de9343390843dbe48243f59e1305f230b431e1e898c3163351c6ae2`.
- Final bounded domain target R19, own copy `runs/e6-30d-conditional-review-r19`, base `7f7a59a2c17033f3ae45a5434c1087d1fdfe7ea1`, 65 verified overlays, manifest LF SHA256 `b79d52ab5036039ef3d40369d4f77f3d0f50c3aa8be7c750bde10372e53f0655`. The whole manifest includes unrelated already-reviewed work; this verdict covers the eleven domain/schema paths listed below, not every overlay.

## Confirmed original failures

1. **Future receipt reported current after clock reversal.** Save an actual EAEU registration review at 10:00:02; all source facts already exist at 10:00:00. Reading at 10:00:01 still returns `current_conditional_review` and the calculated date. The current overlay must reject a receipt created after the shared observation time while its historical exact retry remains available.
2. **Restore after anchor loss silently changes a manual calendar task.** Create and enable the real conditional task, manually reschedule it to November 2, then withdraw the actual period. The task is correctly shown with no due date and a schedule conflict; requesting `restore` nevertheless succeeds and follows the cancellation branch. A restore command must refuse missing evidence and preserve the manual task; explicit reconciliation/cancellation remains a distinct action.
3. **Contradictory closed stays manufacture a 31-day absence.** The paired positive has August 1–31 and October 1–5 stays. Adding a confirmed July 1–September 30 interval leaves the generic history as `recorded_inputs`, by design, but the new consumer still takes the last two start dates and emits a 31-day absence review. The consumer must establish a coherent sequence or refuse the overlapping history. The existing general history reducer need not change.
4. **Historical selection restores the apparent current date of a cleared track.** Save then clear a conditional review without changing its source facts. Latest read correctly has no date, and the original command retries exactly. Selecting revision1 still exposes `conditional_current.review_due_on`. A selected old receipt must remain historical; the latest track head determines current applicability.

These are actual connected failures with positive controls, not only unimplemented coverage. They concern internal review dates and task behavior; the code retained `filing_allowed=False` and did not demonstrate a legal-permission claim.

5. **Native interview consent withdrawal is ignored without a channel stop.** On R8, a valid own EAEU review date remains available after starting the real interview and recording its native `interrupt(consent_withdrawn)` action. The interview confirms `collection_blocked=True` and a retained `consent_withdrawal`, but a new conditional preview still returns October19. The consumer checks `specialist_interruptions` channel/cause evidence while omitting the validated interview state's own privacy latch. Paired pre-interview and active-interview controls both produce the valid date. Parent added the state check in R10; current correction does not require inventing consent when no interview exists.

6. **A later same-person passport replacement is ignored by the absence consumer.** R8 correctly excludes another person's replacement, but a replacement in the subject's separate REG application, recorded one second after the confirmed history, still leaves the 31-day review trigger available. Parent's R14 correction checks the validated own-person replacement journals and requires a later history confirmation, conservatively including equal timestamps. It does not compare incompatible 32- and 64-character passport reference schemes. Both subject isolation and the original failure correction pass on R14.

7. **Projected cross-application capacity is checked only before insertion.** R14 accepts 32 actual passport-change application scopes and its current read works. A new passport change in a 33rd own-person application also commits, although `passport_observations` rejects that resulting scope. The original no-lowered-limit negative fails because the 33rd write succeeds. R16 adds a projected distinct-application admission check before insertion; the own unchanged correction passes. Existing withdrawal and exact-retry branches remain outside the new admission guard.

8. **Explicit current presence contradicts the actual absence history.** The R16 own test first establishes a valid 31-day absence with a current profile whose entry date matches the actual October1 return. Three separately saved/reconfirmed cases then still expose an October13 review date: profile entry September3 inside the absence; profile abroad while the latest actual stay remains open; profile in Kyrgyzstan while the latest stay has closed. R19 explicitly refuses those contradictions with `conditional_deadline_absence_presence_conflict`. The exact original test passes on R19, retaining its valid positive. Unknown or omitted profile presence is not treated as a contradictory assertion. This is fact coherence, not automatic registration or lawful-stay policy.

## Preserved execution evidence

| Own R4 artifact | Result | Scenarios |
| --- | --- | --- |
| `runs/reviewer-conditional-boundaries-r4.xml` | 2 FAIL, 74.68 s | Future receipt; missing-anchor restore |
| `runs/reviewer-conditional-history-r4.xml` | 2 FAIL, 63.77 s | Overlapping absence; old selection after clear |
| R6 `runs/reviewer-conditional-atomicity-r6.xml` | 1 PASS, 79.11 s | Inject a real calendar-task-event SQL failure after new receipt/pin creation: all new rows and task changes roll back; unchanged command recovers, exact retry adds nothing |
| R8 `runs/reviewer-conditional-privacy-r8.xml` | 1 FAIL, 46.70 s | Actual native interview withdrawal remains ignored |
| R8 `runs/reviewer-conditional-renewal-r8.xml` | 1 PASS / 1 harness FAIL, 132.94 s | Typed renewal positive/negative matrix passes; a four-field interview correction violates the existing three-field batch bound |
| R8 `runs/reviewer-conditional-absence-passport-r8-corrected-harness.xml` | 1 FAIL, 46.63 s | Actual own-person cross-application replacement is ignored; the earlier separate run stopped on a reused fixture portal reference |
| R14 `runs/reviewer-conditional-final-r14.xml` | 4 PASS / 1 harness FAIL, 254.30 s | Native privacy correction; old exact receipt and denied new write after withdrawal; typed renewal matrix; passport correction pass. Interview date fixture still grouped dependent fields; actual catalogue requires separate location→basis→type confirmations |
| R14 `runs/reviewer-anchor-application-bound-r14.xml` | 1 FAIL, 57.23 s | Actual projected 33rd passport-application admission |
| R16 `runs/reviewer-conditional-final-delta-r16.xml` | 4 PASS, 185.65 s | Unchanged 33rd-application negative; two legitimate source prefixes through cached history/exact retries; correctly sequenced real interview date conflict; native privacy current refusal and historical exact retry |
| R16 `runs/reviewer-absence-presence-r16.xml` | 1 FAIL, 54.46 s | Positive followed by all three genuine profile/history contradictions |
| R19 `runs/reviewer-absence-presence-r19.xml` | 1 PASS, 57.86 s | Exact unchanged positive/three-negative correction |

Promotable own probe files in the R4 and R6 review copies:

- `tests/test_reviewer_conditional_boundaries.py`
- `tests/test_reviewer_conditional_absence.py`
- `tests/test_reviewer_conditional_historical_selection.py`

The first R6 invocation used a wrong relative copy path and collected no tests; that is a reviewer setup error, not a product failure. The corrected invocation ran the four original tests unchanged: **4 PASS, 149.05 s**, `runs/e6-30d-conditional-review-r6/runs/reviewer-conditional-correction-r6.xml`. The run exited0; one existing Starlette deprecation warning is unrelated. It confirms the future-receipt refusal, restore refusal with preservation of the manual task, overlap rejection after the valid absence positive, and historical-only selected receipt after clearing. Exact old retries remain unchanged.

## Source contract still under implementation

The twelve explicit rule identities distinguish actual permit termination from dismissal planning, an actual registration end from a synthetic duration, and an observed absence trigger from a fictitious exit-plus-30 filing date. Imported null deadline units remain null; separately configured server authority supplies the conditional interpretation. This is appropriate for the bounded internal reminder contract and does not approve the source, policy or legal action.

The R6 visa-extension gate lacked all §19.11 renewal premises. R8 adds a typed actual renewal-context record in the existing anchor stream: own period id/hash, current and proposed product/purpose, explicit renewal/change-status intent and stable inviter references with proof. Own R8 and R14 matrices verify that missing context, current-type mismatch, excluded target type, proposed-purpose mismatch, inviter mismatch and a superseded period pin refuse a date; an explicitly corrected context recovers the date and the old exact command still retries. This records operator-attested premises for an internal review date; it does not qualify the proposed visa product or grant filing permission. R16 confirms native interview date reconciliation using separate real location, basis, type and date confirmations, as required by the original catalogue.

R16's history cache was reviewed separately: it is freshly allocated inside one scoped track verification, loads the matching independent pins with a count check, and retains each row's own source selection, timestamp, hash, identity and arithmetic checks. Keys for authority and interview context preserve their distinct identities. It is not a cross-request cache. The connected two-profile/two-anchor-prefix replay control passes: both original requests retry exactly, an old selected receipt stays historical, and the latest receipt retains its own new date. The R19 domain delta relative to R16 is only the five-line presence reconciliation in `conditional_deadline_sources.py`.

## Connected source acceptance and historical meaning

The original twelve identities cover the scoped visa/permit/resident dates, actual registration end and payment-code date, distinct effective changes, dismissal versus permit termination, EAEU actual pending period and actual absence trigger. Authorizations pin the original PDF, imported projection/catalogue/publication and separate complete calendar. Null source units remain null. No test authorization is an owner approval. Expired actual evidence can produce an overdue internal date without granting permission to work, stay, submit or quote.

Independently inspected and parsed builder evidence supplements the own adversarial tests: R7 actual branch matrix `4 PASS /153.55 s`; R10 legacy deadline compatibility `34 PASS /59.91 s`; R17 real absence29/30/31 `1 PASS /76.14 s`; and R18 `tests/test_conditional_deadline_sop.py`, `1 PASS /105.006 s`. That last scenario imports the original PDF and keeps one own EAEU registration through typed handoff, incomplete-package refusal, actual portal approval and R08; a certificate boolean alone remains insufficient. Recording the actual60-day period then creates the conditional receipt and assigned Medina task. Withdrawal cancels that same task; the original receipt retries without current authority. This establishes the connected seam rather than merely exercising an offset formula.

The later planned TS/B/RL/S source-clause extension is excluded from this R19 verdict. Full J01 requires the parent's complete connected source matrix and final audit; this review does not award it by renaming conditional arithmetic. The existing old official-manual branch is retained. An archived old handler's explicit `replay=True` may refuse a changed runtime hash by design; that is distinct from preserving the immutable receipt, exact original request, current manual view and task. Separate auditor evidence must state that distinction.

## Final bounded identity

LF SHA256 for exact R19 paths (models only the D additions, existing deadline/task modules only their D integration):

| Path | SHA256 |
| --- | --- |
| `app/domain/entry_anchor_rules.py` | `da1f65eca3b77b96028e616c46f2ddb69b97cb7b2c1253d8e94d3a010407c0f3` |
| `app/domain/entry_anchors.py` | `4de7dd05533664a3dcfdc97552eb0cade4e01d1e068d4e82093503a67ac9b10c` |
| `app/domain/conditional_deadline_rules.py` | `d1b42f882150acdcfba720c6cd2c9d8e61e287fbf14b11d0cca560d6b733abeb` |
| `app/domain/conditional_deadline_policy.py` | `0a8632f5bde22c0ce8042b73f7aa8e54c93059ef35d46685e78700adf3382d74` |
| `app/domain/conditional_deadline_sources.py` | `d7d1360b4b186a849f5a8ffb82056f8f2b721644aeab4bb4db443b495cb0ff43` |
| `app/domain/conditional_deadline_evidence.py` | `f29b040cd774191b97c11ee78466b1f664c4ab2f2946c9b508790a3285c88305` |
| `app/domain/conditional_deadlines.py` | `8467f55992f777e5c5ea979e296791484a6b41008b69d50435d6bbe168c1e127` |
| `app/domain/entry_deadlines.py` | `97e828e1c831a08e11dbcc0baa75031d16e5a1d3fc7239ed06990ab4987a4c9f` |
| `app/domain/entry_deadline_tasks.py` | `7dfbc5ae4417b394542bcd31482085818b1826ac2ea18e329779d5a69b97381f` |
| `app/domain/models.py` | `9c7a352576018e4f66b1b298d709d5acf151eb4e68301853083dfa1163822b79` |
| `alembic/versions/e6_actual_anchor_events_0042.py` | `2c647d693fad86bdcac453e97d01d23294b47b9c6b4ba6f0b535320973c8a5f2` |

Final own R16 XML SHA256 `49c142557de588c26dd7af6ca43804ece7fb8651e7e11ee97ed03f1b6ff51791`; original R16 presence FAIL XML `893c04530c62fcea027cca086622e44e0f26986a4fc875f6bef2947da69f2c13`; exact R19 corrective XML `74132c64e941f88b8c0808723098ec3882f460ff2dfa124b418918e04d321614`; R18 connected SOP XML `8aef9747b036595b9a27a36c00fde809ec6eb18db525489b1a5ea664ac5f96ea`. The corrective command in the env-free R19 copy was `python -m pytest tests/test_reviewer_absence_presence.py -q --junitxml=runs/reviewer-absence-presence-r19.xml`; it exited0. All original failed snapshots and separate harness failures are preserved. Newer coherent-presence requirements must be reflected explicitly if the older overlap/passport fixture positives are promoted; their previously executed evidence is not rewritten.

Remaining whole-D obligations are unchanged: connected acceptance across the applicable source matrix, native/security checks, real PostgreSQL concurrency and schema/recovery evidence, exact final scope identity, independent review completion and separate final audit. Pure offset tests alone do not establish the connected source behavior or parent acceptance points.

## R20 source-clause extension — separately reviewed APPROVE

Own env-free `runs/e6-30d-conditional-review-r20` verifies all72 frozen overlays and the original PDF. Manifest LF SHA256: `012156250f6afe5a3cac0655e2b12849fb9fbd93f7218ae3ca2f4781edfc84c3`. Original printed pages80–81 were extracted and examined before builder conclusions. Added rules map TS actual visa end minus5 calendar days, B renewal preparation minus15 working days, RL actual visa end minus15/minus10 working days and S actual visa end minus10 working days. They do not invent an FF/SW offset, replace a visa period with a permit period, or approve the later resident application. Annual follow-up is not silently converted into a fixed document validity period.

Only three domain files differ from R19; other eight domain/schema hashes above map exactly. Final LF hashes:

| Path | R20 SHA256 |
| --- | --- |
| `app/domain/conditional_deadline_rules.py` | `2977d3b480dcb5b2c32f1496b2acb5ec70ac87f24e04c83803baac5223df2d8c` |
| `app/domain/conditional_deadline_sources.py` | `6d7a4cddaa4e0f50c71cb5563cac4ffa9b01570916a7027481e6374870a34f8e` |
| `app/domain/conditional_deadline_evidence.py` | `de837c91ee710ab8bd55b91b812cc0e5f494e612f9f135b7293a47887e182324` |

The source evaluator checks exact current visa type/purpose, actual visa period and supplied interview type. TS does not require fictitious renewal premises. B preparation uses the same explicit renewal-context gate as the original visa extension; retained verification also requires that context pin. The five new definitions do not change the original twelve definition hashes or semantics. R20's separate native label change is outside this domain verdict.

Own command in the R20 copy:

`python -m pytest tests/test_reviewer_visa_source_delta.py tests/test_reviewer_conditional_absence.py tests/test_reviewer_conditional_absence_passport.py -q --junitxml=runs/reviewer-source-delta-r20.xml`

**3 PASS /129.02 s, exit0, no skips.** XML SHA256 `33be4f90123fce79930eeb26cdcf2faac9c65b3ad895827be4f881fc89d1e206`. The first composite independently proves TS without renewal-context positive, real interview B-versus-TS conflict and recovery, B missing premises then admitted actual premises, both RL positive dates from actual visa and refusal of an actual permit. The other two preserve the original overlap and cross-application passport negatives while explicitly correcting their old positive profile fixtures to match R19's new presence contract: closed latest stay uses an abroad profile; open October1 return uses `in_kg_since=2026-10-01`. Both new profiles are saved through the real journal and the actual history is freshly pinned. Original failed and corrective artifacts remain unchanged.

Builder's `runs/e6-30d-r20/runs/visa-sop-reviews-r20.xml` was independently parsed: **5 PASS /262.134 s**, SHA256 `6b15545bcf87e6afea0fbe769f1d7b9786d87c5c7f0ce8acf183f669021ef0ae`. Its actual test source was inspected: each new clause runs actual own visa evidence→conditional receipt→assigned task, then explicit wrong-purpose evidence→current unknown/task cancellation, with old exact retry and historical replay retained. This supplements the independent negative controls; it is not counted as independently authored testing.

Promotable final files are under `runs/e6-30d-conditional-review-r20/tests/`: `test_reviewer_visa_source_delta.py`, `test_reviewer_conditional_absence.py`, `test_reviewer_conditional_absence_passport.py`. Earlier promotion paths remain as communicated: R6 boundaries/historical-selection/atomicity; R16 privacy/renewal/application-bound/cache; R19 exact original presence control. No open confirmed domain finding remains in the reviewed R20 scope. No running reviewer process, PostgreSQL use, root runtime edit or release action remains.
