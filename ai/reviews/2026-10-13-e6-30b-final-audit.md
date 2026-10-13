# E630B — separate final audit of specialist decision and internal quote

Auditor: `e622_audit`. CRITICAL / solo; completion target is a reviewed local
change. **GO / DONE for the bounded E630B reviewed-local change**, exact R17
scope of 36 staged files. Both temporal write defects proved on R14 are corrected
and independently pass on R16, whose runtime is identical to R17. Independent
domain and native reviews are APPROVE; actual PostgreSQL correction/recovery and
final identities are verified. No open material finding remains in this scope.
This is not full J01/J02 completion, actual policy approval or a production gate.

## Scope, independence and identity

Requirements were read before builder conclusions: the E630B task, its original
pre-audit, bounded India/business/ten-day acceptance and source distinctions.
Actual code was then inspected: catalogue/builder, specialist policy/facts,
evidence, immutable journal, existing quote extraction, model/migration0039,
native route/template and existing scoped dialogue readers. The independent
implementation report was read only after this source assessment and the first
own temporal probe were established.

The original PDF was independently opened at physical pages 30, 81 and 90:
product selection, B purpose/host requirements and the exact India example.
Source preservation is not legal approval. The source catalogue remains
`unapproved_source_evidence`; real specialist policy defaults to empty.

All own application imports and executions used new verified Git archives without
`.env`; root application imports, runtime edits, PostgreSQL, providers, live data
and production access were not used. Base throughout:
`ad9e0bd4d7403f05cb8e7178a0d5f738a0cd4356`.

- R14: 32 overlays, LF manifest SHA256
  `afbb5b064b07a8a2ba4663233ab06815a959964928295b1adc012a1ab817eb51`.
- R16: 36 overlays, LF manifest SHA256
  `04b43bb7d2ddb4cc75323046e23cdefb424013289d354cb0cfdde953e7f8e399`.
- Final R17: 38 overlays, LF manifest SHA256
  `9231d033b08f149d10875eb45f7c0c2efaba9587d1d9eca02ed64700a22bf288`.
  Its 36 scoped source/test files independently match the frozen manifest,
  working-tree bytes and Git index after LF normalization. The index contains
  exactly these files; task/state documentation and unrelated UI are excluded.
  `git diff --cached --check` passes.
- Every overlay was hashed before extraction/import. Own copies:
  `runs/e6-30b-audit-r14` and `runs/e6-30b-audit-r16`.
- Original PDF SHA256:
  `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.
- R14→R16 runtime delta was inspected: bounded UTF-8 native payload limits and
  the two-line precommit quote/decision/link timestamp guard. Earlier interruption
  approval maps by unchanged runtime identities, not by assuming the entire
  intervening snapshot is unchanged.
- R16→R17 adds only the two native reviewer test files; they are byte-identical
  to the independently executed native probes. All application, migration,
  catalogue and builder files are unchanged. Full mapping and raw XML/image
  hashes: `runs/e6-30b-audit-r16/final-audit-identities.json`.

## Contract assessment

The implemented positive is deliberately one capability: a single adult Indian
ordinary-passport applicant abroad, genuine non-profit business meeting, suitable
Kyrgyz host, no contradictory work/family/residence/long-visa/history facts, and
one future trip within the delegated duration. Source data preserves all eighteen
regime applicability shapes; the general procedure's availability and exact unit
pins are checked, while excluded conditional outcomes are not promoted. Explicit
specialist clause review and price-recipe delegation remain separate from source
publication and interview authority.

Personal reconciliation uses the current applicant profile, own recorded complete
history, current interview answers and original immutable header/ACK. It checks
mapped fields and refuses unsupported material branches, withdrawn consent,
retained unsafe causes and conflicting or stale facts. Typed supporting findings
bind host identity and purpose text; their reference/proof describes recorded
evidence, not independent government verification. Actual document collection,
passport margin, registration, processing calendar and entry-point checks remain
pending. The result neither grants entry/stay/work rights nor sends a client offer.

The specialist journal reconstructs closed command/result schemas, subject,
revision/predecessor, authority, policies and original source/fact pins. A quote
event links the actual existing quote receipt for the same application/person;
the deterministic quote request key is bound to the specialist command. Exact old
receipts are located before current-policy authorization can reject a new action.
Withdrawal retains history and changes current use. Count and byte reserves are
independently exercised by the reviewer, not inferred from constants alone.

The quote extraction was compared to its base transaction body. The public v1
preflight, command, result, policy, arithmetic, duplicate semantics and calculator
remain unchanged; only the private same-session seam is added. No contract amount,
payment, refund, portal submission or client-send mutation is introduced.

Lock order is existing case, application where applicable, applicant, publication
context; time is sampled after those locks. Profile/history/interview/application
writers share those parents, and publication/review writers share the source
locking seam. The nested quote and link use the same transaction, with no provider
callback. No route/global advisory lock is introduced after the case lock.

Migration0039 adds one immutable journal, composite person/application/predecessor/
decision/quote FKs, revision/request/quote uniqueness and shape constraints. The
model is included in existing immutable JSON/ORM/bulk guards. Populated downgrade
refuses deletion under an exclusive lock. Actual migration and recovery evidence
was inspected and matched to the completed artifacts below.

Native source uses existing full-admin and write gates, read-only GET, bounded
stream parsing, exact field sets, CSRF/HMAC bound to actor/route/action/payload,
typed editable findings and explicit confirmation. Known historical records can
render without current authority. Wrong targets fail scope checks; storage
uncertainty preserves a signed exact request. R15 expands the signed payload
bound to the already accepted event envelope while retaining streaming and
UTF-8 byte checks, so valid larger quote previews are not unsaveable.

## Auditor findings, originals retained

**F1/F2 — interruption history**, documented fully in
`2026-10-13-e6-30b-interruptions-audit.md`: R8 omitted a corrupted tail when its
STOP discriminator changed, and allowed an omitted cause at the exact observation
timestamp. R9 validates the complete observed journal prefix and refuses omitted
facts timestamped at or before observation. Five own final R9 checks passed;
the same interruption code remains in R16. This includes a legitimate late
delivery outcome preserving STOP pins and historical context. Equal-time
ambiguity is intentionally refused, not claimed readable without ordering proof.

**F3a — quote newer than its link. Confirmed R14 FAIL.** The actual save sampled
12:01 for initial specialist work, 12:03 for the nested quote, then 12:02 for the
outer link. It committed both rows. Ordinary `read_decisions` subsequently
rejected the timestamp relation required by its own historical validator. No
stored data was tampered with; only clock samples were controlled.

```text
python -m pytest tests/test_audit_specialist_quote_clock.py -q --tb=short --junitxml=audit-quote-clock-r14.xml
```

Result: **1 genuine FAIL, 70.84 s**, own R14 archive. The test verifies the committed
counts (two specialist events, one quote) and the subsequent integrity failure.
Artifact: `runs/e6-30b-audit-r14/audit-quote-clock-r14.xml`.

**F3b — quote older than its decision. Confirmed R14 FAIL.** A quote timestamp
strictly after the application event but before the specialist decision also
committed, followed by the same unreadable journal. This is the opposite boundary
of the same missing precommit contract, not a raw-record corruption experiment.

```text
python -m pytest tests/test_audit_specialist_quote_before_decision.py -q --tb=short --junitxml=audit-quote-before-decision-r14.xml
```

Result: **1 genuine FAIL, 60.57 s**, own R14 archive. Artifact:
`runs/e6-30b-audit-r14/audit-quote-before-decision-r14.xml`.

R16 now requires `decision.created_at <= quote.created_at <= link.created_at`
before the second observation or link append. The enclosing transaction
rolls back both new rows on either violation. The original probes were copied
byte-for-byte into the own R16 archive. They also verify same-request recovery,
exact replay with all current policies removed, and acceptance of the exact
equal-time boundary. Corrective execution: **2 PASS / 127.75 s, exit 0**.

Other original reviewer findings remain in the independent implementation
report: conditional literal source divergence, omitted historical interview,
missing-authority historical display, future active-decision use, and full-admin
registry growth consuming the terminal byte reserve. Native findings and their
corrective evidence are recorded by the separate native reviewer. They will not
be silently replaced by a single final-green claim.

## Own verification and external evidence gate

Own R14 deterministic source build was executed read-only with `runpy.run_path`
and compared to the installed catalogue bytes. Result **PASS**: catalogue SHA256
`4d6f964df3052dd1f70614b76913a6975a99fb2617e728e622852acafd2ac28e`,
22 source sections, one enabled catalogue capability, all 18 regime shapes,
and approval marker unchanged. Artifact:
`runs/e6-30b-audit-r14/audit-source-catalog.json`.

The own R16 two-case corrective suite completed:

```text
python -m pytest tests/test_audit_specialist_quote_clock.py tests/test_audit_specialist_quote_before_decision.py -q --tb=short --junitxml=audit-quote-clock-r16.xml
```

Artifact: `runs/e6-30b-audit-r16/audit-quote-clock-r16.xml`. Two corrected cases,
zero skips/failures, one existing Starlette deprecation warning. Both use actual
quote save transactions; the negative paths leave only the original decision and
zero quotes. Recovery creates one quote/link and the exact original retry remains
readable without current policies. Combined with the five mapped R9 interruption
controls, this auditor has seven final or exactly mapped successful behavioral
checks, with the original four genuine failures retained separately.

Builder/other-reviewer results below are **not auditor executions**. Exact XML
counts and times were independently parsed, and relevant code/tests inspected.
Overlapping runs are not added together as unique coverage.

| Evidence | Result and significance |
| --- | --- |
| Builder R2 `runs/quote-seam.xml` | 50 PASS / 63.906 s: existing quote/native compatibility, mapped to the byte-identical final quote extraction. |
| Builder R13 `runs/specialist-final-core.xml` | 48 PASS / 647.461 s: 40 source/fact cases, four connected domain cases, two native RU/EN cases, one real browser flow and one migration-table inventory regression. |
| Builder R10 `runs/specialist-postgres.xml` | 11 PASS / 685.241 s: actual competing request/revision locks, both quote/withdraw orders, five fact/source writers, cancellation and post-wait date checks, actual migration/FK/parity/populated downgrade refusal. |
| Builder R15 `runs/specialist-recovery-concurrency.xml` | 3 PASS / 199.103 s: fresh binary-COPY recovery plus same/different request concurrency after compact-authority correction. |
| Builder R16 `runs/specialist-clock-postgres.xml` | 2 PASS / 134.034 s: both auditor temporal negatives and actual PostgreSQL rollback, same-request recovery, equality and exact replay on final domain code. |
| Domain reviewer R4 `review-component.xml` | 22 PASS; pure component files still match final source, including complete source applicability and conflicting-literal controls. |
| Domain reviewer R12 `review-domain-reserves.xml` | 6 PASS / 297.362 s: original historical authority/omission and atomicity findings, future active-decision refusal, real 64-event limit and administrator-growth withdrawal. |
| Domain reviewer R12 `review-bytes.xml` | 1 PASS / 38.522 s: actual archived R9 writer fills 4,186,112 ordinary bytes, unchanged receipts replay, an ordinary append is denied and a 1238-byte withdrawal still fits. No constants lowered or fabricated padding. |
| Domain reviewer R16 `review-atomic-final.xml` | 1 PASS / 80.896 s: exact final runtime ordinary quote/link, injected rollback and same-request recovery. |
| Native reviewer R14 `runs/reviewer-native-r14.xml` | 5 PASS / 278.089 s: corrected labels/incomplete totals/outages/healthy-read lost acknowledgement, target/auth bindings, exact conflict/invalid/uncertain retries. |
| Native reviewer R15 `runs/reviewer-native-r15-bounds.xml` | 2 PASS / 89.311 s: real 32-line signed quote save/retry and retained stream/pre-offer bounds. |

The domain clock/compact-authority corrections were source-mapped separately.
Migration0039 is identical from R9 through R16; quote extraction is identical
from R2 through R16; pure component files are identical from reviewed R4. R15's
native handler/template/router/application link match R16 byte-for-byte after LF
normalization. The earlier R13 core is not described as an exact R16 full rerun:
the final domain guard and native corrections have their own focused evidence.

Recovery code was inspected and the produced `specialist-recovery.json` parsed:
62 tables, retained two specialist events and one quote, matching receipt reads,
original retries, restored sequences, then withdrawal and new decision revision4.
It restores binary COPY data into a freshly migrated schema with live FKs; a
test-owned fresh database is dropped afterward. Backup SHA256 recorded there is
`84d469d140a3ddd87f93b4801fe618b28ed04b651a8449c0cef0d40d307e6400`.
This is verified local recovery evidence, not a production backup/recovery claim.

The native scoped independent report is APPROVE. This auditor also viewed all
six R13 `review`, `quote`, and `saved` images for 390px dark/Russian and 1365px
light/English. Amounts, internal-only meaning, buttons, labels and history are
readable; the actual browser has JavaScript disabled and denies off-loopback
requests. Both long `review` captures place the sticky header mid-document due
to the captured scroll position; this is an artifact limitation, not evidence of
a runtime layout defect. Quote/saved captures show the header normally. No print
acceptance is claimed or required for this particular screen.

The domain independent report now gives scoped R16 APPROVE; its LF SHA256 is
`50ee6452ed7f904a77eb620c37664636b4fe02d71d48431a09690dcc94116e4c`.
It preserves all original findings and treats the auditor's controls separately.

Final actualPG clock XML SHA256:
`945955cb30ded0a4d4a07823462800b8a411e151f6111f4bae1304493e8f4adf`.
Builder confirmed all cited final processes exited0; the auditor's own processes
also finished. No active auditor test or PG process remains. Final R17/index
identity was then independently verified for all 36 files. No test was run from
the root environment and no full repository suite is claimed.

The evidence index is only a navigation aid; actual artifacts, source mappings,
separate review verdicts and own adversarial tests establish this GO. Earlier
failures remain preserved rather than being overwritten by the corrected runs.

## Completion limits

No J01/J02 points, full fourteen-SOP coverage, the other two golden examples,
all-product quotation, real clause/commercial/source approval, activation,
deployment or production readiness follows from this bounded local feature.
Original NO_VISA, installed dialogue admission and existing money semantics are
not redefined. The user prohibited deployment; no production release is requested
or granted by this audit.
