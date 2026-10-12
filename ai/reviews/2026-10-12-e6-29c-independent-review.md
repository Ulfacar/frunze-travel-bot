# E6-29C independent implementation review

Final independent verdict: **APPROVE — exact R16 / 26 scoped indexed files,
reviewed local E6-29C connected implementation and fixed H02 technical acceptance.**
All six independently reproduced findings are corrected; the final current-version
threshold rerun passes. No known implementation defect remains in this scope.
This is the independent CRITICAL implementation review under protocol v4, solo mode.
The separate final audit remains its own release/completion gate. This does not
authorize production activation, actual source/fact/calendar authority, or the
full PDF project. The earlier two-file question-adapter approval is separate.

## Identity and method

Requirements and the actual changed source were inspected before builder conclusions:
the C task, final incoming/reconciliation and first-privacy addenda to the E629
pre-audit, and the actual adapter, policy, authority, journal, reconciliation,
current-stay bridge, composer, final guard, Wappi/main/orchestrator hooks,
migration/models and native status. The later inbox addendum and implementation
were also read. Journal construction precheck findings were read after actual code.
Final evidence verified2026-10-12 UTC /2026-10-13 local. Broad snapshot R16 has41
verified overlays; approval covers only the26 files in `runs/e629c-commit-scope.json`.
Every indexed file was independently rechecked against R16 after final tests.
Later unstaged E630 changes, including the model extension, are excluded.

Original frozen R7: base `6775d30be496335fc0aad10f6d18e6debc98da25`, 37 verified
overlays; LF-normalized manifest SHA256
`95f48d440ec8e6fe476e2935247fd626c2fb4def53f198438814bb09599b1293`.
Own environment-free Git archive: `runs/e6-29c-review-r7`.
R9 corrective archive: `runs/e6-29c-review-r9`, same base, 39 verified overlays;
manifest LF SHA256
`ba2722cb984278cfedfa66d6379eab0bd87e26fa9a3c949eee9dcbcaede47681`.
No root runtime edits, private env, live services/data, real providers or own PG run
were used for this review. Test databases and facts are synthetic. A fake callback
records invocation; it sends nothing. Original failed evidence remains intact.

## Confirmed original findings

1. **Oversized privacy after ACK is discarded before operational triage.**
   A normally enrolled session requests a human, receives native ACK, then submits
   `65537` ordinary characters followed by `Delete my data`, using a new valid
   provider ID and no current authority. R7 raises
   `invalid_dialogue_incoming_envelope`; the actual interview still has
   `collection_blocked=False`. Stored assignment/identity should retain the
   operational privacy hold even when ordinary parsing limits reject this input.
   The related core packet size gate also preceded privacy triage (source finding).

2. **A contradictory typed passport expiry continues ordinary collection.**
   The current saved profile says `2030-01-01`. The actual displayed/accepted
   enum and boolean prompts are completed through durable claims and the real
   final guard with a fake provider; the next displayed date answer is
   `2099-12-31`. R7 accepts it and prepares another prompt. Treating passport
   expiry and other existing profile facts as nonmaterial does not prove the
   original attestation still applies. This violates the explicit reconciliation
   contract; missing or conflicting profile facts require operator review.

3. **A rehashed header can move the durable route binding and permit a legacy send.**
   Before mutation the actual activated domain final guard refuses a legacy
   callback on the enrolled route. The saved header's delegated recipient,
   channel key and transport hash are coherently changed, and the header is
   rehashed. Its deployed-policy hash is left unchanged. R7 validates this header
   because the original full policy/assignment membership is not retained.
   The original route is now a negative lookup, and its callback is invoked once.
   Restoring the exact original document/key/hash restores denial. This is a
   demonstrated guard failure under saved-record corruption, not an actual send.

4. **A rehashed baseline evidence pointer is accepted without crosslink validation.**
   Replacing only `baseline_check.evidence_hash` by 64 zeroes and recomputing the
   header hash is accepted by journal history. It is not compared to the retained
   result's evidence hash. This was probed in the same independently written
   integrity test as finding 3, with exact restoration between mutations.

Own test sources are `tests/test_review_dialogue_connected.py` and
`tests/test_review_dialogue_integrity.py` in the R7 review archive. Initial command:

```text
python -X utf8 -m pytest tests/test_review_dialogue_connected.py -q --basetemp .pytest-review-connected --junitxml=review-connected.xml -p no:cacheprovider
```

Result: **2 FAIL / 160.09 s**, explicitly **one genuine privacy failure plus one
reviewer fixture error** (passport expiry was not yet in the first prompt batch).
Preserved as `review-connected-initial.xml` and `review-connected-initial-test.txt`.
The fixture was corrected to traverse the actual preceding prompts; the oracle
and required behavior were not weakened.

```text
python -X utf8 -m pytest tests/test_review_dialogue_connected.py::test_future_passport_expiry_contradiction_requires_reconciliation tests/test_review_dialogue_integrity.py -q --basetemp .pytest-review-followup --junitxml=review-followup.xml -p no:cacheprovider
```

Result: **2 FAIL / 226.25 s**, both genuine runtime failures: expiry mismatch and
the combined two-mutation integrity test. Observed integrity result was
`baseline_evidence_detected=False`, original-route callback count `1`,
`refused=False`. Baseline and restoration controls passed. XML:
`runs/e6-29c-review-r7/review-followup.xml`.

## Corrective source assessment and remaining verification

R8/R9 source adds full original authority retention and exact assignment/subset
membership, baseline evidence/source/history crosslinks, profile-bound matching,
and privacy triage before ordinary size limits. R9 additionally removes the new
mutable CRM inbox row as a prerequisite for operational journal/privacy reads,
excludes nontext/media/control-bearing raw inputs from the transcript, and makes
legacy latch presence and current activation distinct in the native status.
The original source-only checkpoint did not certify these fixes; their later
exact repro reruns and PASS results are recorded below.

The reviewer separately flagged R8's mutable inbox dependency, media URL/raw
retention and incomplete native status to the builder. The separate auditor owns
the connected mutable-inbox and causal-stop evidence tampering probes; their
results will be distinguished from this reviewer's evidence.

The initial remaining gates were corrective identity mapping, negative/positive
controls, causal evidence validation, unknown-send/recovery and capability
behavior, actual PG races/recovery, and native/browser evidence. Later sections
record their results rather than inferring completion from earlier A/B components
or the pure adapter's passing suite.

## R9 corrective evidence and an additional confirmed defect

The three original independent tests pass on exact R9: **3 PASS / 508.438 s**,
one existing Starlette deprecation warning. This includes the positive enum/boolean
progression before the passport contradiction, original guard denial, both header
mutations and restoration, and actual collection blocking after oversized privacy.
Artifact `runs/e6-29c-review-r9/review-corrections.xml`, raw SHA256
`0d4ec53c4008e1fb50c99039e89a6414fe3d17fea621c83db27dd78648af1d3a`.
The command used both original test files and the R9 review archive, with
`--basetemp .pytest-review-corrections --junitxml=review-corrections.xml`.

5. **A reconstructed durable send reference can fabricate provider acceptance.**
   After actual enrollment and durable claim, the reviewer constructs a new
   `TypedSend` with the claim's same fields and calls `record_outcome` with
   `provider_accepted`, without invoking any provider callback. R9 accepts that
   outcome; the next typed document answer progresses without stopping. Thus
   guarding only the callback does not protect the acceptance evidence used by
   later turns. This is a demonstrated internal service-boundary flaw, not a
   claim that an external HTTP caller can directly instantiate Python objects.
   Own source: `runs/e6-29c-review-r9/tests/test_review_dialogue_outcome.py`.
   Command: `python -X utf8 -m pytest tests/test_review_dialogue_outcome.py -q
   --basetemp .pytest-review-outcome --junitxml=review-outcome.xml -p no:cacheprovider`.
   Result **1 FAIL / 124.213 s**, zero provider callbacks; XML raw SHA256
   `e52e20f2b89ae7eed956624031cf2ce5bd2f66b3c35dfae49fa70fb913ea92b4`.

R10 adds an issued-object identity gate, and requires consumed identity for
provider acceptance; an issued but unused claim can still truthfully record
`unknown`. It also requires the persistent panel backend for ordinary collection,
so a SQL inbox row cannot be described as visible through an unrelated memory
store. Retained privacy is independent of that collection configuration.

The reviewer also identified a source-level semantic mistake: `passport_pages_ok`
means available blank pages in the saved profile; it cannot establish
`passport_undamaged=True`. The builder accepted this distinction. R11 makes the
damage field require operator reconciliation rather than inventing the asserted
equivalence. No separate runtime failure is claimed for this source finding.

Final corrective snapshot under review: `runs/e6-29c-r11`, same base, 40 verified
overlays. Own archive `runs/e6-29c-review-r11`; manifest LF SHA256
`6198060a33f42b0d418ec7126b3523d111939d13e93e1ccd0cfc5be22c9123ff`.
All four original controls pass there with unchanged oracles. The sole
fixture addition is importing the documented `persistent_panel` fixture required
by the tightened ordinary-collection deployment contract. No R10 test result is
claimed; its archive was inspected but not executed.

R11 source additionally checks successful current-evidence timestamps/as-of,
the exact reconciliation session/original/current heads and actual answer tail;
strictly binds triage reason to families; and propagates storage unavailability
as HTTP503 instead of acknowledging an uncommitted input.

## Exact R11 independent verification

```text
python -X utf8 -m pytest tests/test_review_dialogue_connected.py tests/test_review_dialogue_integrity.py tests/test_review_dialogue_outcome.py -q --basetemp .pytest-review-final-corrections --junitxml=review-final-corrections.xml -p no:cacheprovider
python -X utf8 -m pytest tests/test_review_dialogue_http.py -q --basetemp .pytest-review-http --junitxml=review-http.xml -p no:cacheprovider
```

Executed sequentially in the environment-free R11 review archive:
**4 PASS / 465.63 s**, then **2 PASS / 5.96 s**. Both emit only the existing
Starlette test-client deprecation warning. No own test process remains active.
The first suite closes all original runtime findings from this reviewer. It
includes actual durable normal prompt admission and callback controls before the
negative material answer, exact original binding denial and restoration, and
rejection of fabricated acceptance followed by an unseen-prompt stop.

The second suite uses the actual Wappi webhook/parser/orchestrator with isolated
domain/provider boundary doubles, no lifespan startup or network. A partially
committed batch gets 503 on unavailable privacy persistence; resubmitting that batch
redispatches the same provider IDs to durable dedup, and returns 200 once handled.
A separate scenario performs one fake provider callback, fails saving its outcome,
returns 503, then accepts duplicate intake without another claim, callback or
outcome attempt. This proves local response/retry behavior; it does not claim that
the external provider guarantees redelivery.

The R11→R12 manifests independently show no changed `app/` or `alembic/` file.
R12 adds test/evidence coverage; review scope can map to that runtime identity.

Builder XML independently parsed so far (not reviewer executions):

| Artifact | Observed result | Exact scope |
|---|---|---|
| R10 `e629c-r10-compat.xml` |224 PASS, 0 skips, 189.560 s|110 questions, 18 hook, 18 guard paths, 51 channel stops, 17 native stops, 10 Wappi|
| R10 `e629c-r10-connected.xml` |4 PASS, 0 skips, 687.877 s|Actual RU/EN webhook progress, persistent panel and outcome identity|
| R11 `e629c-r11-hook.xml` |129 PASS, 0 skips, 10.315 s|Questions and hook, including 503 behavior|
| R11 `e629c-r11-pg-diagnostic.xml` |1 FAIL, 128.568 s|Original concurrent first-receive expectation, kept as FAIL|

The diagnostic concurrency failure is the established 2 s route-lock timeout,
SQLSTATE 55P03 `LockNotAvailable`, wrapped as unavailable; it is not evidence that
both initial requests succeeded. The revised bounded contract permits only this
verified contention failure and requires exact retry after the winner commits,
with the original receipt and no duplicate turn/inbox/claim. Production lock
timeouts were not relaxed. Final PG evidence for this contract subsequently
passed in R12, as detailed below.

Fixed H02 is **“Interrupts, stop factors and specialist escalation in dialogue
flow”**, PDF 4/17/Б.6, weight2. At the R11 checkpoint H02 remained UNKNOWN pending
actual PG, recovery/native/browser and final correction evidence. Those checks
are now recorded below. This review does not reduce H02 to passing pure parsing
or A/B component checks; the separate final auditor must issue its own verdict.

## Additional provider-boundary finding

6. **Malformed provider response IDs become accepted-prompt evidence.**
   The existing Wappi helper stringifies any truthy value. A200 response with
   `message_id={"error":"NOT_ACCEPTED"}` becomes a nonempty Python-dictionary
   string; boolean `True` becomes `"True"`; whitespace remains a nonempty string.
   The new C callback therefore treats all three as provider acceptance.
   This is a defect in the newly connected evidence chain even though the
   permissive legacy extraction predates C.

   Independent exact-R11 test uses the actual Wappi `send`, `httpx.MockTransport`,
   webhook/parser/core classifier, and isolated domain/guard boundary doubles.
   No external network or DB writes are involved. All three malformed cases
   record `provider_accepted` instead of `unknown`; an ordinary string ID is a
   positive control. Source:
   `runs/e6-29c-review-r11/tests/test_review_provider_acceptance.py`.
   Command: `python -X utf8 -m pytest tests/test_review_provider_acceptance.py -q
   --basetemp .pytest-review-provider --junitxml=review-provider.xml -p no:cacheprovider`.
   Result **3 FAIL + 1 PASS / 5.93 s**, original evidence preserved in
   `runs/e6-29c-review-r11/review-provider.xml`.

The implemented correction is strict, bounded, opt-in C acceptance-identity
validation on original JSON types, with the unrelated legacy extraction default
preserved. Unsupported numeric/container/boolean, whitespace/control-bearing or
conflicting recognized IDs must remain unknown. A usable response ID is still
only provider acceptance, not delivery or reading. R16 correction verification
passes below; prior six independent passing controls remain valid for their scope.

Separate auditor's exact R11 artifact was independently parsed and its tests
inspected: `runs/e6-29c-audit-r11/runs/auditor-r11-correction-reserves.xml`,
**5 PASS / 558.390 s**, raw SHA256
`e5cb45f17754d3f8b38a5b03cfa8610513cfd6991c5301490b34d769c7c1861c`.
It covers coherent triage and successful-evidence rehash mutations, foreign
subject terminal evidence, deleted mutable inbox/privacy retry, actual journal
count1018→1023, and a byte budget derived from real serialized usage. The byte
scenario uses a reduced test budget; it is not a claim that16 MiB was filled.
The reserve cases preserve the old card through native ACK, later privacy,
outstanding unknown outcome and exact retry. These are auditor executions,
not additional reviewer test runs.

## Exact R16 provider correction and native evidence

All 41 R16 overlays were independently verified, then applied to a fresh
environment-free Git archive of the same base, `runs/e6-29c-review-r16`.
LF manifest SHA256:
`cd649c6138f6513be7602a6412f373e2ec2254d4081b2be7bf73cae8d00e51f3`.
The runtime delta from R11 consists of exactly three files: native print CSS,
the opt-in Wappi strict ID extractor, and the C-only callback keyword. All
domain, journal, authority, guard and migration files are unchanged.

The original four provider controls and two HTTP503/retry controls ran with
unchanged oracles: **6 PASS / 7.290 s**, existing Starlette warning only.
Command: `python -X utf8 -m pytest tests/test_review_provider_acceptance.py
tests/test_review_dialogue_http.py -q --basetemp .pytest-review-provider-correction
--junitxml=review-provider-correction.xml -p no:cacheprovider`.
Artifact `runs/e6-29c-review-r16/review-provider-correction.xml`, raw SHA256
`250f9bd4225119819ff57189401e12776471c4d54112c4f0c6c646f052da0c9c`.
The original R11 3 FAIL / 1 PASS artifact remains intact. No own process or
PostgreSQL run is active. The actual database malformed-response→unknown→
unseen-answer rejection control subsequently passed in the final builder run below.

Source review confirms strict validation precedes coercion; unsupported original
JSON types, invalid characters/length and inconsistent nonempty recognized IDs
return no usable acceptance identity. The local keyword is not sent to Wappi.
Legacy extraction remains the default outside C. Empty/null aliases supply no
identity; they cannot by themselves establish acceptance. This is a conservative
local evidence contract, not a claim that every provider response format is supported.

Additional builder XML personally parsed:
- R14 `e629c-r14-delivery.xml`: **2 PASS / 192.913 s**, real managed timeout and
  cancellation, one callback/claim/outcome and no duplicate attempt. Raw SHA256
  `620bf6029c2fe9e0a9505bb61f15754a4c12f359f6b34e3885ea8ab25d391d9d`.
- R15 `e629c-r15-browser.xml`: **1 PASS / 138.599 s**, actual Chromium mobile390
  and desktop1365 with JavaScript disabled for desktop, native status and print.
  Raw SHA256 `bf9fd29c71cc8036e1e5ad53cfdd8bb6ce3a69faada81c0b1c4d6b75221b672c`.

Both screenshots and both distinct print-page rasters were personally viewed.
The corresponding mobile/desktop page rasters are byte-identical. Both PDFs
have exactly two pages, containing1583 and716 extracted characters; collection
stop, no deletion claim, missing old text, unknown send/no automatic retry and
prepared questions remain readable. This is Russian native UI evidence; RU/EN
client prompt evidence comes from the actual incoming-flow checks. The previous
R13 empty-page layout failure is corrected by the R15 print-only CSS, retained
unchanged in R16.

## Final PostgreSQL, adapter and scope mapping

R12 `runs/e6-29c-r12/runs/e629c-r12-postgres.xml` is **10 PASS / 1011.941 s**,
zero failures/errors/skips; parent confirmed process exit0 and released the PG
slot. Raw SHA256 `d463733066d23a1d15cd9dec8445a251742046fbcd30c6f18a63b7bd033818b0`.
The actual tests and XML were independently read; these are builder executions
on isolated synthetic local PostgreSQL, not reviewer executions or production.

Evidence includes concurrent first intake and claimants with exact retry after
verified bounded55P03 contention; both orderings of send versus privacy; actual
profile/history/publication writers waiting on locks while the callback is held;
before/after claim-commit uncertainty; terminal count/byte reserve; actual0037
upgrade/downgrade and metadata parity with populated downgrade refusal; and
binary COPY to a fresh isolated database preserving journal/inbox/prompt hashes,
original retries and no second send claim, followed by a fresh privacy stop.
The PG reserve uses reduced limits; the auditor separately exercised the real
1018→1023 count boundary. Local COPY recovery is not a production backup claim.

R16 `runs/e6-29c-r16/runs/e629c-r16-adapter.xml` is **52 PASS / 8.008 s**, zero
failures/errors/skips, raw SHA256
`8b741a2885692d377a6efc6095b6f72ca81b75f7b2ffead6754ccd5281845fba`.
It covers strict original-JSON identity cases, installed hook gates and unchanged
legacy Wappi behavior. The separate auditor's R16 actual adapter controls are
**8 PASS / 0.398 s**, XML raw SHA256
`eca03e50aefd30f806811bcf7736838afcc51bd7c96fee885801385642232c9a`;
supported consistent aliases/length-bound identity are positive controls, with
conflicting/malformed aliases and nonprintable values denied. The flag remains
local to the adapter. Both XML files were independently parsed.

All26 files in `runs/e629c-commit-scope.json` independently match root and exact
R16 LF hashes. Unrelated CRM base/boards/style files included in the broad frozen
manifest are excluded from this scope. Builder mapping and complete case names
are retained in `runs/e6-29c-review-r16/review-builder-mapping.json`.

The explicit in-KG headroom2/3/4 and working-calendar4/5/6 controls were originally
executed in R7, **13 connected PASS / 1596.018 s**, along with normal RU/EN and
native-drift cases. R7 is not relabeled as R16: later universal journal proof
validation tightened. Final threshold confirmation was requested before the
whole H02 verdict. Final R16 connected malformed-ID/timeout/cancellation/RU/EN
evidence passed: **5 PASS / 521.327 s**, zero failures/errors/skips, parent-confirmed
exit0. Independently parsed `runs/e6-29c-r16/runs/e629c-r16-connected.xml`, raw
SHA256 `c71c3a7e039b355eb9c1c9b595e233a955546aebc7a50debc8ec0c6957300990`.
The malformed response now persists one unknown outcome through actual storage;
duplicate intake cannot resend and a labelled reply to that unseen prompt stops
without becoming an interview answer. Both RU/EN actual webhook flows preserve
the original attestation through enum→boolean→date progression and stop on
bot-output-disabled privacy. Final threshold rerun used the exact R16
archive; no implementation change was needed to run it. It completed
**6 PASS /443.536 s**, zero failures/errors/skips, with all exact cases present.
Artifact `runs/e6-29c-r16/runs/e629c-r16-thresholds.xml`, independently parsed raw
SHA256 `db4e1b0c1339d1a5e5c81fd528f19ae7c98425c09954332b2978bf9eeb93265a`.
Thus the threshold claim no longer relies on transferring R7 results to the new
validators. Positive headroom4 and calendar5/6 cases each obtain a real admitted
prompt and persist an ordinary typed turn; headroom2/3 and calendar4 stop and
deny the legacy callback, with exact retry and changed-envelope controls.

## Fixed H02 acceptance assessment

The fixed criterion is assessed as installed interruption, stop-factor and
specialist-escalation behavior for the explicitly managed private Wappi route,
not merely as a new parser or an operator button. This is the same supported
channel boundary already used by the PDF's existing channel integration; it
does not claim global or other-channel suppression.

| Required behavior | Evidence and current assessment |
|---|---|
| Incoming interruption precedes ordinary processing | Actual parser/webhook/handle gates; whole-input exception triage before typed parsing, media/STT and legacy buffering. Source families are candidate references, not claims that every listed incident occurred. Unrecognized/unsupported answers require specialist handling. PASS for this bounded contract. |
| Ordinary conversation can genuinely progress | Durable prompt/claim/provider-acceptance and exact labelled answer; saved enum→boolean→date; original attestation remains immutable with proved ancestry and current dependencies. R11 own positive controls and final R16 RU/EN actual webhook rerun PASS. |
| Material drift and unsupported facts do not silently renew authority | Own contradictory expiry and rehashed binding/evidence failures corrected; separate auditor rehashed terminal/success proof cases corrected; absent/ambiguous material values require operator reconciliation. PASS. |
| Actual current-stay factors stop selectively | Headroom2/3 versus4 and work-calendar4 versus5/6 are implemented with current source/fact/calendar gates. Exact final R16 six-case rerun PASS after universal validator corrections. |
| Human/privacy escalation persists through ACK and removed collection authority | Actual durable interview/card/session stop, retained scoped operator authority, no legacy/send continuation; privacy raw omitted and old mutable transcript not required. Own/auditor privacy, count and byte-reserve cases PASS. |
| Send uncertainty cannot manufacture a seen prompt or trigger a retry | Issued consumed capability required for acceptance, original provider JSON identity checked before coercion; unknown/timeout/cancellation and failed persistence preserve no automatic retry. Own R16 boundary/HTTP checks and final R16 actual-DB malformed-response case PASS. |
| Concurrent writers, migration and recovery preserve the contract | Final R12 actual PG10 PASS, including both stop/send orderings, three actual waiting writers and fresh-database COPY restore. Domain/guard/migration runtime unchanged through R16. PASS. |
| Operator can review the real status | R15 actual mobile/no-JS/refresh/print, visually checked; current activation, canonical collection stop, optional old channel latch, unknown send and missing raw text are distinct. PASS. |

With all exact-version cases now passing, this connected A+B+C scope is
sufficient for the fixed H02 technical criterion. No claim is made that all57
source situations receive their full business/SOP execution: that was explicitly
outside the interruption/escalation criterion and has not been substituted for
it. Case creation, all product journeys and other open PDF criteria are separate.
Real source/policy/calendar/factual approvals and managed-route activation remain
owner gates; local synthetic tests neither provide them nor authorize production.
