# E6-30A independent implementation review

Final verdict: **APPROVE** for the exact sixteen staged E630A files matching
`runs/e6-30-r12`, base `7b45f6c56c22adef80a3f4e79aa1aae8d7a3fe0d`.
All four independently reproduced findings are corrected; thirteen final checks
pass in the reviewer's separate environment-free archive. CRITICAL / solo;
target is the reviewed local preliminary-case and same-case recorded-signature
flow. No production, real policy approval, full J01/J02 acceptance or E630B/C
approval is implied. Separate final audit remains its own gate.

## Method and identity

Read task requirements, the actual new domain/native/model/migration code and
adjacent existing permissions, ownership, legacy contract, workflow-task and
finance-reader code. The first task read inadvertently included its short builder
checkpoint; those counts were not used to establish correctness or acceptance.
The independent design pre-audit was then read as a requirement/constraint source.
No earlier implementation-review verdict was used. No root runtime edit, root
environment file, real data/provider or own PostgreSQL execution was used.

The reviewed frozen snapshots share base `7b45f6c56c22adef80a3f4e79aa1aae8d7a3fe0d`.
All normalized-LF overlay hashes were verified before constructing separate
environment-free Git archives; earlier C and unrelated UI overlays are not new
E630 approval scope.

| Snapshot | Own archive | Verified overlays | LF manifest SHA256 |
|---|---|---:|---|
| R4 | `runs/e6-30-review-r4` |41|`d3d1bfd484b6e228102d310638e21a9a9c462458401290615670a8c658875755`|
| R6 | `runs/e6-30-review-r6` |43|`bb32e20ea946d64a49605d8d125ee250a6ba258c6bab9b50bd944105fb5ffca2`|
| R8 | `runs/e6-30-review-r8` |45|`e8f35170524aa2088d6f2e3c4b7217524e3c40783558c386a6764199dfb55476`|
| R11 | `runs/e6-30-review-r11` |45|`73b4d754c81c9478dde3369fdc07eac45a32259bf00f80a3aa95ab70206a13fd`|

At R11 verification, all sixteen root files matched the R11 frozen files and
the then-current `runs/e630-commit-scope.json` (LF SHA256
`c293dd155c2259d75295bcdc867549c251e2cc593a54ce99f37ecfb442814b88`).
This map covers the new domain/native/template/migration, model and router,
workday/case/conversation links, six E630 test files and the existing migration
inventory test. The broader forty-five-overlay archive includes previously
reviewed C and unrelated UI artifacts; they are not newly approved here.
R10 was also inspected and archived, but no own R10 test execution is claimed.

Final staging update: R12 removes only one trailing blank line in
`tests/test_precontract_evidence.py`; all other fifteen scope files are identical
to R11. Verified the difference is whitespace-only and all sixteen root, frozen
and Git-index blobs match the refreshed scope map (LF SHA256
`7bbfaa6a46d70f2d0437f9b522e8b4faac4538ab1c3d8cbbe356578080d76b6d`).
All forty-seven R12 overlay hashes verify; manifest LF SHA256
`1fb1a69c4b587de76953f1cfb14a4cf14e7cd70c4d50d9ce97ff2bd5f9495b57`.
The extra broad overlays are documentation, outside this sixteen-file approval.
No new test execution is necessary or claimed for this non-executable delta;
all runtime and test behavior below maps from final R11 to exact R12/index.

## Confirmed findings

1. **A committed opening cannot be recovered after later owner disagreement.**
   An actual admin native opening and its immediate exact retry both return303.
   A subsequent real domain contact assignment changes to another manager while
   the panel still contains the previous owner. Fresh opening correctly returns422,
   but the original committed form also returns422 because fresh `_owner` checks
   precede receipt lookup. The admin still has current case access. Historical
   operation recovery must compare its original immutable command under current
   access checks, without requiring a new owner decision. R6 moves only the known
   receipt path ahead of fresh owner resolution; subject/case/current access and
   original command remain enforced. **Original R4 FAIL; unchanged R6 PASS.**

2. **Malformed signed-event JSON escapes native failure handling.**
   Following a real native signature, controlled SQL changes its `payload` to an
   empty JSON list. Exact POST retry raises uncaught `AttributeError` at
   `_plain(event.payload).get('operation')`; no controlled error/form is returned.
   R6 verifies the payload and retained-operation shapes first.
   **Original R4 FAIL; unchanged R6 PASS.**

3. **Signed-event stage is not bound to the saved operation.**
   Following a real native signature, changing only its `to_stage` to a fabricated
   stage requires no hash rewrite and is accepted by the original form as303.
   First signature was explicitly permitted only at the pinned original first
   stage. R6 binds the signed event's from/to stage and reason to the validated
   opening and original signature command, without comparing them to a later
   legitimate current case stage or corrected money.
   **Original R4 FAIL; unchanged R6 PASS.**

4. **R6 accepts a malformed retained signature result owner.**
   Controlled SQL changes `operation.result.owner_login` to null and recomputes
   the operation checksum. Exact native signature retry still returns303 because
   the result validator checks keys and IDs but not this owner identity. This is
   malformed historical-result acceptance, not demonstrated permission expansion.
   Validate the retained identity's normalized bounded nonempty string shape;
   comparing it to the current owner would incorrectly break legitimate delayed
   retries after reassignment. R8 validates the original retained owner shape.
   **R6 FAIL; unchanged R8 and final R11 PASS.**

The separate missing-current-`signed_at` corruption control refuses safely and
retains the submitted form; it is **PASS**, not another defect. The first three
unchanged reproductions also pass on final R11.

The separate auditor found rehashed impossible signature revisions and a
noncanonical domain actor that could create an unreplayable opening. These are
credited to that auditor. R8 requires signature result revision to equal original
expected revision plus one. R11 rejects noncanonical actor identity before writes,
while native `actor_for` already supplies canonical identity. The legacy signing
API is unchanged. Root additionally bound the original opening revision to one,
the pinned published workflow's first stage and null original from-stage/reason.
Its R9 empty-string-versus-null mistake caused a genuine regression retained in
the evidence; R10 corrected it to the original null model convention. The final
two opening and three canonical-actor controls were independently executed here.

## Independent executions

Own tests use actual native HTTP forms and synthetic SQLite domain operations in
the own archive. No application import ran from root. No actual provider is invoked.

```text
# Exact R4 archive
python -X utf8 -m pytest tests/test_review_precontract.py -q --basetemp .pytest-review-precontract --junitxml=review-precontract.xml -p no:cacheprovider
# Exact R6 archive
python -X utf8 -m pytest tests/test_review_precontract.py tests/test_review_precontract_partial.py -q --basetemp .pytest-review-corrections --junitxml=review-corrections.xml -p no:cacheprovider
# Exact R11 archive: eight own controls plus five final-delta controls
python -X utf8 -m pytest tests/test_review_precontract.py tests/test_review_precontract_partial.py tests/test_review_precontract_lifecycle.py tests/test_precontract_integrity.py::test_opening_must_describe_actual_first_workflow_stage_and_initial_revision tests/test_precontract_integrity.py::test_noncanonical_actor_refuses_before_committing_unusable_operation -q --basetemp .pytest-review-final-r11 --junitxml=review-final-r11.xml -p no:cacheprovider
```

R4: **3 FAIL /12.086s**, all genuine implementation findings, no fixture failure.
Artifact `runs/e6-30-review-r4/review-precontract.xml`, raw SHA256
`3de6a1d2b0ec1c7e583fe56bf67ea99bde2bda86a72dee83ad67f145a9c75c19`.
R6: **4 PASS /1 FAIL /12.08s**; original three controls pass unchanged, plus the
missing-time negative passes; malformed owner remains. Artifact
`runs/e6-30-review-r6/review-corrections.xml`, SHA256
`7d0dda7ed08447b72cf8706f794efae8a26a33c3e5d6d305ba33da3a74f116db`.
Both original artifacts are retained.

R8: **8 PASS /14.265s**, artifact
`runs/e6-30-review-r8/review-final.xml`, SHA256
`c0ba7b3c42a6aeaa98963d3f088d6016bbed7c592a413c70d2436efdab314d3e`.
The three additional own controls exercise real later lifecycle changes:

- Archived unsigned product denies a fresh signature but preserves the original
  opening retry. After valid signature, stage movement, owner reassignment, amount
  correction and product archival preserve original open/sign receipts without
  creating another contract/task or altering the later current state.
- A peer's reused global opening key cannot disclose the foreign case; a distinct
  legitimate peer opening and original owner's exact retry remain possible.
- Injected failure while inserting the opening receipt rolls back only its new
  case/event/receipt/task while preserving the caller's prior unrelated contact;
  removing the fault allows a successful exact-key retry.

R11: **13 PASS /13.659s**, process exit0, artifact
`runs/e6-30-review-r11/review-final-r11.xml`, SHA256
`004904136b49e79a401d0690b79919b983c75ae44ab0f28f0a51f2deca8d2208`.
This reruns the original eight own controls unchanged and independently executes
two builder opening-integrity negatives plus three canonical-actor boundaries.
Warnings: existing Starlette test-client deprecation and a SQLAlchemy identity-map
warning during the deliberate rollback/retry fault injection. The latter run
still verifies preserved caller data and exact resulting row counts. No own test
or PostgreSQL process remains active.

## Scope assessment and connected evidence

The new operation correctly separates opening and signing request identities,
pins the original commercial workflow and preserves legacy signature behavior.
Current case access is checked before duplicate disclosure. The signature uses a
case lock and revision, compatible top-level signed event money fields and a
nested savepoint for contract/event/task atomicity. Opening creates no signature,
payment, quotation authorization, immigration classification or consent. Retained
result identities are validated without requiring equality with later mutable
owner or money. Opening remains explicit and the first signature requires the
original workflow's first stage; there is no automatic workflow advancement.

The initial native positive merely opened the intake page. The R5/R6 added test
was inspected: actual native applicant/application creation, own profile save and
reload, real internal quote, then same-case signature; exact IDs and profile/quote
receipts remain unchanged and legal eligibility/payment remain unasserted. This
actual connected test passes in the builder's R7, R10 and final R11 evidence.

The following builder artifacts were personally parsed, and their relevant test
source inspected. These are not represented as own PostgreSQL executions.

| Evidence | Result | Exactness and purpose |
|---|---|---|
| `runs/e6-30-r7/runs/e630-r7-delta.xml` |16 PASS /41.970s|Native continuity, migration inventory, browser and actual binary-COPY recovery. R7 native/UI/migration files unchanged on R11.|
| `runs/e6-30-r10/runs/e630-r10-final.xml` |45 PASS /48.741s|35 domain/native/integrity plus 10 actual local PG races, migration and recovery. R10→R11 runtime delta is only prewrite canonical-actor rejection in the domain module.|
| `runs/e6-30-r11/runs/e630-r11-delta.xml` |18 PASS /20.268s|Exact final integrity and native checks, including connected applicant/profile/quote/signature flow.|
| `runs/e6-30-r11/runs/e630-r11-legacy-postgres.xml` |4 PASS /6.197s|Actual legacy signing concurrent same-key/other-contact/foreign-direction and migration constraints; prior optional skips are now executed.|

R10 full XML raw SHA256:
`e6de461d05d5ec9299091e4df5131752aa8f7b10cdd0d725d9e6e2e8dbfef786`.
Final R11 delta raw SHA256:
`03d6fa1cef001482e8e3ceffb0bdc7310ab8a2aca66ea96daa0ab8583f1efcb3`.
Final R11 legacy PG raw SHA256:
`9cfda071986fd4c3ced3f4b620144eade1a26fdd8935cc2797dc84f11cd50811`.

The actual PG tests observe lock waits and verify same/different-key opening and
signature races, stale revision after owner/stage/money writers, collision,
rollback and lost-response recovery. The additive 0038 migration has empty
roundtrip/metadata parity and refuses a populated destructive downgrade. Recovery
exports every public table with binary COPY, counts/hash manifest, sequence values
and Alembic revision, restores a fresh migrated isolated database with foreign keys
enabled, then verifies old/new records, exact open/sign retries and a later write.
This is local database recovery evidence, not a production backup/release claim.

R6 recovery originally failed because its output directory did not exist;
`runs/e6-30-r6/runs/e630-r6-core.xml` retains 39 PASS /1 FAIL. Root fixed the harness
directory creation. A separate earlier migration-inventory failure omitted three
existing C tables and the new opening table from the expected set; the explicit
four-name inventory update does not weaken runtime constraints. Both failures
remain distinct from genuine reviewer/auditor defects and later passing runs.

Personally inspected all six R7 Chromium screenshots at
`runs/e6-30-r7/runs/e630-browser/`: open, sign and recorded states for 390px dark
and 1365px light. Forms and button text are legible, no horizontal overflow is
visible, and the final state displays the recorded reference/amount instead of an
empty disabled signing form. The browser test runs without JavaScript at both
sizes, uses actual native form posts and verifies same-case navigation and final
case/task/payment counts. Its source and template are unchanged on R11. No extra
automated contrast or production browser claim is made.

The separate auditor additionally executed independent corruption/cancellation
and actual PG archive/legacy/namespace controls on R8, and five final R11 actor
and opening controls. Those evidence artifacts are attributed in the separate
audit; they do not replace the own adversarial checks above.

## Acceptance boundary

**PASS** for E630A's explicit preliminary case → saved/reloaded own intake and
internal quote → recorded already-signed contract on the same case; exact and
conflicting retries, current authorization, immutable operation evidence, unknown
money semantics, pinned workflow/task, rollback, concurrent operations, migration,
recovery, native no-JS views and legacy compatibility have bounded local evidence.
No confirmed defect remains in the exact sixteen-file scope.

**J01/J02 remain UNKNOWN/open.** They require the later source-product/scenario
work in the fixed criteria and pre-audit; this preparatory continuity slice alone
does not earn those criteria. Selecting a commercial product does not establish
immigration eligibility, approved pricing, consent, payment or real signature.
Real owner/source approvals, pilot activation and any release are outside this
local review. Separate final audit is required before the parent records the
reviewed E630A target complete.
