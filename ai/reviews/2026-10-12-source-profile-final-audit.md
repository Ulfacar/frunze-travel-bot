# E6-24 source/profile — independent final audit

- Auditor: `/root/e622_audit`, independent of builder `/root` and reviewer `/root/publication_review`.
- Date: 2026-10-12. CRITICAL / solo; completion target: reviewed local A01/A02/A03/A04/B01 behavior, unchanged acceptance definitions.
- Requirements and actual source were read before reviewer conclusions: task `ai/tasks/2026-10-12-e6-24-source-profile-review.md`, fixed criteria and actual archive/intake/qualification persistence/native source.
- Initial frozen snapshot: `runs/e6-24-r1`, base `87ad9e759aae223258742d286310aba2155f112d`, **23/23** overlay hashes independently verified. Manifest raw SHA-256 `b2d31a2b326ba408b9154d0cb36eb19433140b3d0242d85bbebd959a0a7f6226`.
- Auditor env-free copy: `runs/e6-24-audit-r1`. Only audit probes/artifacts were added there; shared application source/config and real PDF were not modified. No root `.env`, production, personal records, external services or messages used.
- Final verdict: **GO for exact R2 scoped local A01/A02/A03/A04/B01 behavior**. The original R1 verdict was **FIX_REQUIRED** for the native roundtrip finding below. The correction passes both the auditor's unchanged connected probes and the separate reviewer's final follow-up; no confirmed defect remains in the bounded scope. This is not full PDF/C05, legal approval or release acceptance.

## Confirmed native compatibility defect — corrected in R2

**P2 — a valid saved integral JSON number cannot be resubmitted through the native form unchanged.**

Location: `app/admin/kg_entry_form.py`, `values_from_request` integer-field rendering. It uses `str(value)`, rendering valid saved `applicants_count=6.0` as `6.0` and child `age=8.0` as `8.0`. The existing strict native parser accepts only decimal integer-digit strings, so its own loaded values yield HTTP 422 on ordinary resubmission. This crosses the specific schema/domain/native boundary covered by B01; it does not bypass authorization or mutate the old receipt.

Probe: `runs/e6-24-audit-r1/tests/test_auditor_integral_native.py`. Each case saves through the real domain service, reads the real authenticated native form and its signed envelope, then POSTs its values without editing the integer field. No fabricated signature, SQL corruption or test-only business evaluator was used.

Actual command from the audit copy:

```text
python -m pytest tests/test_auditor_integral_native.py -q --tb=short --basetemp=C:/Users/alanb/AppData/Local/Temp/e624-audit-native-r1 --junitxml=runs/e624-audit-native-r1.xml
```

Result: **2 FAILED**, one dependency deprecation warning, **12.72 s**. Count and age cases both receive HTTP 422 instead of 303. Required correction: render schema-valid integral numeric fields canonically as integer strings, preserving stored inputs/old receipts and the existing strict submitted-string parser. Retest both fields and old receipt preservation on the corrected frozen snapshot.

## Source-first assessment

- The `intake.py` change is exactly two post-schema numeric type guards. Shared request schema, validation, qualification algorithm identifier, storage code and original selected source capture are unchanged. JSON Schema permits integral numeric floats; accepting their numeric comparison prevents `6.0` from bypassing the large-group stop and `1.0` from bypassing the applicant/family consistency rule. Booleans, fractions, nonfinite values, strings and out-of-range values remain rejected before this layer.
- Contact and individual persistence preserve old input/result receipts on ordinary read and duplicate retry. Explicit replay compares the runtime fingerprint, which includes `intake.py`; old results are not silently recomputed after the code change. Existing CAS/ownership/source-integrity checks remain in place.
- New archive script pins exact PDF SHA-256, PyMuPDF binding and MuPDF engine versions. All pages, original extraction order, text-block geometry, rotations, per-text/content hashes and document hash are retained; output is explicitly unapproved and non-executable. Existing different output is refused, `--check` compares complete bytes, and new output uses exclusive creation.
- The archive preserves extracted text and positions, not graphics or an independent visual interpretation of tables. Its own limitations keep the original PDF authoritative; extraction does not grant legal currency, source approval or complete executable rule coverage.
- Actual retrieval rechecks pinned Markdown/source-lock and reconstructs the stored corpus; draft fragments carry source spans/citations, uncertainty labels and false quote/publication permissions. Native search is full-admin gated, read-only and forbids arbitrary input paths.

## Auditor checks actually completed on R1

Environment: Windows/Python 3.12, env-free copy, synthetic SQLite for storage/native tests. No auditor PostgreSQL run is claimed for this task; the separate reviewer owns the coordinated PG upgrade evidence.

| Command/scenario | Result |
|---|---|
| Independent direct PyMuPDF comparison of the real `../Kyrgyzstan-visa-knowledge-base-v1.1.pdf` against archive JSON, all page text, block text/order/number/geometry, rotation, text/page/document hashes | **PASS: 94 pages, 8,820 raw extracted lines, 3,006 text blocks**, no mismatch. PDF SHA-256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`. Independent comparison did not call the builder's extraction function. |
| `python scripts/build_kg_full_source_archive.py --source '../../../Kyrgyzstan-visa-knowledge-base-v1.1.pdf' --check` from audit copy | **PASS**, 1,812,564 bytes; archive SHA-256 `a0ef99ebaf87bb980b59a1481ede20a6f1b5c75ff79826f2186b8d387afac58c`. One earlier invocation used an incorrect extra `../` and failed with missing file; corrected invocation above is the actual acceptance evidence. |
| `python -m pytest tests/test_intake_numeric_semantics.py tests/test_kg_full_source_archive.py -q --tb=short --basetemp=C:/Users/alanb/AppData/Local/Temp/e624-audit-core --junitxml=runs/e624-audit-core.xml` | **13 PASS**, 12.54 s, one dependency deprecation warning. Numeric group/family/invalid representations, contact/person persistence, all synthetic pages/geometry, PDF/extractor drift and nondestructive output checks. |
| `python -m pytest tests/test_kg_entry_source_bundle.py::test_real_bundle_is_reproducible_and_passes_actual_file_parser tests/test_kg_entry_source_bundle.py::test_no_approval_or_governance_policy_invented tests/test_kg_entry_source_bundle.py::test_unrepresentable_conditions_are_not_fabricated tests/test_kg_retrieval.py::test_corpus_corruption_is_rejected -q --tb=short --basetemp=C:/Users/alanb/AppData/Local/Temp/e624-audit-source --junitxml=runs/e624-audit-source.xml` | **10 PASS**, 2.13 s. Rebuild/check of 208 source units, unchanged unapproved and unresolved statuses, seven corruption mutations refused by actual retrieval loader. |
| Native loaded count/age regression above | **2 FAIL**, confirmed finding requiring correction. |

The R1 native failure above remains a failed historical run; corrected acceptance is recorded separately below. Full C05, interview/channel integration, actual legal/source approval, pilot and production remain outside this audit.

## Final corrected R2 identity and independent retest

The builder confirmed `runs/e6-24-r2` frozen. Base: `d847a254acfd54ec8aeecef529c2885f6ba39bbe`; **21/21** overlays verified in both the frozen folder and `runs/e6-24-audit-r2`. Manifest raw SHA-256: `0a3e730efe85c2a5328b8c8c6a47f97f5e1e0178c2252b48b2c847bf1fcee5a2`.

Corrected `app/admin/kg_entry_form.py` LF SHA-256: `a4021f5d3042021646e389dc52de6dd50a1fff3253f1b4f4b176a6e35592c0b0`. The only runtime delta from R1 is a display guard: an integer-kind field containing an integral Python float is rendered through `int(value)`. Stored input/result snapshots are not rewritten; strict submitted-string parsing is unchanged. Invalid input echo remains raw, so validation feedback is not hidden by coercion.

I directly compared R1/R2 intake, contact/individual storage, archive script/data, native template/controller and search template/controller: all are byte-identical after LF normalization. Existing source, semantic and PostgreSQL evidence therefore maps to unchanged paths; it is not mislabeled as a new R2 execution. The base advance contains the separately audited E6-22 route adapter, which is outside this E6-24 acceptance.

Actual command from `runs/e6-24-audit-r2`:

```text
python -m pytest tests/test_auditor_integral_native.py tests/test_intake_numeric_semantics.py tests/test_admin_kg_intake.py::test_bad_counts_family_and_dates_keep_values_without_writes -q --tb=short --basetemp=C:/Users/alanb/AppData/Local/Temp/e624-audit-native-r2 --junitxml=runs/e624-audit-native-r2.xml
```

Result: **24 PASS**, zero failures/errors/skips, one dependency deprecation warning, **32.18 s**. The original unchanged count/age repros now save successfully. Adopted connected tests also cover the individual applicant form; old receipt equality is checked after the new revision. Group/family semantics and strict invalid count/family/date refusal remain intact. No audit process remains.

Own JUnit SHA-256:

- R1 numeric/archive 13 PASS: `3ef14cfa6ec356811457b7183ed71fbf16a5e2d2549bcd8774bc19c09b57ce51`.
- R1 source/retrieval 10 PASS: `b4c687450a608e06b7b78a85edcc0d1b2a30e4e351edb5b79ba6fe94053bd2f4`.
- R1 native 2 FAIL: `4c52273062d45ec68ce8dbe0f37f8a11a890977c1866ed5c1c9f442f634a1392`.
- R2 corrected native 24 PASS: `0db939a03313f733b34cb07778c421bae65253dce7432a9c47e4e18e351282e3`.

## Separately attributed review, builder and rendered evidence

After source-first assessment I examined `ai/reviews/2026-10-12-source-profile-independent-review.md` and the reviewer's actual historical-runtime/PG probes. Historical compatibility probes seed through the real archived 87ad handler and captured old runtime fingerprint, then restore current code without modifying the stored row. They assert original read/retry receipt preservation, explicit runtime-drift replay refusal, a corrected new revision and unchanged old output. The actual PG wrapper exercises this same contact-storage scenario; the separate baseline lock probe holds the contact row lock and observes that the service write waits until it releases.

These are **reviewer executions**, not auditor tests: baseline source/parser/search 213 PASS/1 optional-PDF SKIP (actual PDF tested separately), selected native/storage 39 PASS, baseline PG 4 PASS, two viewport browser scenarios in 1 PASS test, fixed R1 own probes/numeric/archive 23 PASS, and actual fixed PG 3 PASS. The separate report contains exact commands/artifacts and retains its original semantic failures. Following this audit's native defect report, the reviewer withdrew its R1 approval, independently reproduced three native rendering failures and rechecked corrected R2 before issuing final **APPROVE**.

The reviewer's final R2 run is **21 PASS / 40.16 s**, recorded in `runs/source-profile-independent-20261012/fixed-r2-tests.txt` and its final report. Six independent native cases cover contact/individual forms with count 6.0, child age 0.0 and upper-bound age 2147483647.0; they verify successful unchanged POST, exact retry without an extra revision, unchanged old result/hash, and decimal-string tampering rejected with HTTP 422/no write. Two historical-runtime probes and thirteen numeric/native regressions also pass. I inspected the final report and actual run log. Its LF-normalized manifest identity and this audit's raw-byte manifest identify the same verified R2 file map; line-ending treatment is explicitly different.

I independently viewed reviewer-produced `search-390.png` and `review-1365.png` under `runs/source-profile-independent-20261012/source/runs/e5-04c-intake-browser/`. Search shows readable controls, draft/no-quote notice, page/section citations and raw source fragment. The saved review card shows English questions with the stored language, applicant/family facts, provenance and visible unresolved/no-final-eligibility limitations. I also inspected its three-page `review-demo.pdf` structure. This is inspection of real reviewer-generated artifacts, not an auditor browser execution; no claim of translated admin chrome or interpreted table rendering is made. The R2 correction changes numeric value spelling only, not layout/copy.

Builder R2 artifact `runs/e6-24-r2/runs/e624-r2-native.xml` independently parsed: **75 tests, zero failures/errors/skips**, 207.359 s; builder reported 207.37 s. Raw SHA-256 `6a6c4bea1ecf2716a0bb4f49757cc81c85ce917d2eb7380890d39859130bc653`. It is separate builder evidence, not part of the auditor's counts.

## Acceptance coverage

| Fixed criterion | Auditor assessment and boundary |
|---|---|
| A01 — lossless versioned corpus/pinned integrity | PASS within source-text preservation contract. Exact original PDF identity, complete positioned archive, unchanged pinned Markdown/corpus and actual reproducible source/parser checks. Original PDF remains authoritative for graphics/visual interpretation. |
| A02 — strict schema and semantic validation | PASS. Actual source review, unchanged schema, corrected int/integral-float semantics, native/parser negatives and source-corruption checks. |
| A03 — source-grounded local search, native citations/uncertainty | PASS. Verified loader reconstruction and corruption rejection, reviewer native/search checks, independent mobile/source-card artifact inspection. No legal truth or automated answer permission inferred. |
| A04 — complete source coverage/provenance/unresolved/reproduction | PASS for source preservation. All 94 source pages and 3,006 positioned text blocks independently matched; existing 208 draft units and unresolved values unchanged. This is not a claim that every PDF instruction has a typed/executable implementation; the original editorial Markdown converter remains absent, while complete extraction now has a reproducible pinned path. |
| B01 — versioned save/reload/CAS/retry/native RU-EN | PASS on exact R2. Own original native failures now pass, old receipts remain intact, strict validation remains; reviewed independent actual-PG and historical-runtime evidence covers unchanged storage. Separate final review independently verifies corrected native boundary cases and approves R2. |

**GO for the exact scoped R2 local change.** Required independent review and separate final audit now have evidence; both confirmed defects and their failing historical runs remain preserved. No approval of real law/currentness, actual source/policy publication, customer channel, pilot, C05 closure or production is provided. Later work outside this frozen change requires its own applicable checks.
