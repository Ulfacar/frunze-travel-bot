# E6-16 independent CRITICAL implementation review

Reviewer: independent `portal_pre_audit` context. Completion target: reviewed local synthetic notification drafts. No production, deployment, activation, real policy, client data or outbound provider was used. This is an implementation review, not the separate final audit.

**Latest decision: APPROVE for exact r3 and the bounded local synthetic scope; see the appended re-review.** The r1 findings and failures below are preserved as historical evidence.

## R1 verdict: FIX_REQUIRED

Three reproducible defects remain in the reviewed r1 snapshot: F1 valid Unicode preview cannot be saved; F2 intermediate printed pages lose the draft/no-send boundary; F3 successful writes can make their entire journal unreadable because append and SQL replay use different size measures. I02 is **not yet earned** on r1.

### Provenance and method

- Base `8f415662f374f29d6cd374ddf5f781bf43c6891a`; immutable source archive `runs/e6-16-review-r1`.
- Manifest `ai/reviews/2026-10-11-e6-16-snapshot-r1.json`, SHA-256 `15578f2fa4c15746bf8f7dadf0bb67abfabfc4306a9a3839e8612ad05da5e720`. All 23 LF-normalized source/test hashes independently verified.
- Own execution copy `runs/e6-16-reviewer-r1`; frozen and root implementation files were not modified. New probes and execution artifacts are confined to its ignored `runs/` directory.
- Read task, contract and pre-audit before builder conclusions; inspected actual policy, retained catalog/renderer, domain, models/migration, native routes/template, package asset paths and tests. Checked original requirements through the source-derived Appendix A and section 14 text. Sent initial source assessment before considering builder results.
- All numbers below are this reviewer's observed executions. Builder results are not substituted for independent evidence. The original core invocation misspelled `test_kg_template_preview.py` as `test_template_preview.py`: collection failed with no tests; the corrected command below is the actual evidence.

### Findings

**F1 — P2, valid native Unicode confirmation is unsavable.** `app/admin/kg_notifications.py:54` encodes `_n_values` with `ensure_ascii=True`; `_form` caps that value at 24,576 characters. A legitimate A07 preview containing six free-text fields of 400 non-BMP characters fits domain UTF-8 and raw HTTP limits, returns 200 and generates a signed save form. Posting that unchanged form with its confirmation checkbox returns 422: `_n_values` is 28,855 characters, while the complete raw URL-encoded body is only 38,981 bytes, below 65,536. No signature manipulation or oversized original input is involved. The accepted preview and server-generated confirmation disagree. Use a bounded encoding that preserves the admitted Unicode input and exercise the full native round trip, retry and read.

Probe: `runs/e6-16-reviewer-r1/runs/e616_reviewer_probes.py::test_legitimate_non_bmp_preview_confirmation_roundtrip`; FAIL in the two-probe run, 16.15s. The other probe in that file, a functioning new renderer version with changed text, passed.

**F2 — P2, intermediate print pages lack the draft/source boundary.** `app/admin/templates/kg_notifications.html:5` has no repeated print annotation. The top warning and final source/footer appear only once. A legally admitted A07 with six 500-character non-BMP text fields, saved through the normal domain service, prints as three pages. Page 2 contains the source's legal/status claims but no draft/no-send warning or renderer/source context. The actual PDF page was visually inspected. Existing browser assertions combine all PDF text and only use A06, so they miss this. Reserve print margin for a repeated warning plus exact template/renderer/source context; inspect every page of long saved and preview documents and avoid mixing two template contexts in the same print output.

Probe: `runs/e6-16-reviewer-r1/runs/e616_reviewer_print.py`; FAIL, 12.90s. PDF `runs/reviewer-print/long.pdf`, page facts `runs/reviewer-print/pages.json`, rendered pages `runs/reviewer-print/page-1.png` through `page-3.png` in that copy. Page facts: warning present/absent/present; renderer context absent/absent/present.

**F3 — P1, successful append can render the whole valid journal unreadable.** `app/domain/entry_notifications.py:90` measures SQL `length(CAST(json AS text))` and applies the canonical UTF-8 limits at line 93; append instead checks canonical UTF-8 payload bytes. SQLAlchemy's escaped JSON text is much larger for Unicode. A single A07 with six 500-character non-BMP fields is 30,548 canonical bytes but 81,397 SQL characters. With a scaled 111,945-byte journal threshold, two normal saves commit successfully, then read and exact retry fail in the SQL preflight although canonical history is about 61 KiB. This is independently reproduced on SQLite and actual PostgreSQL 16.

The defect also occurs with **all original limits unchanged**: 52 successive normal A07 saves succeed at 128 rows / 128 KiB row / 4 MiB journal limits; the next read fails `notification_history_limit`. Thus this is not merely an artificial monkeypatch failure. The API can report a committed success whose receipt can no longer be recovered through the normal journal API. Separate the conservative pre-materialization storage bound from the canonical semantic limit, using a safe serialization expansion bound or an equivalent consistent measure; preserve exact read/retry at capacity, and reject any new over-capacity append before commit.

Probes: `runs/e616_reviewer_capacity.py` (SQLite FAIL, 10.77s), `runs/e616_reviewer_capacity_pg.py` (actual PostgreSQL FAIL, 21.58s), `runs/e616_reviewer_capacity_default.py` (unmodified production constants, SQLite FAIL, 23.10s), all under the execution copy. Corresponding `reviewer-capacity*.xml` and JSON artifacts are retained.

**V1 — browser fixture defect, not product finding.** Both frozen r1 browser cases call Playwright `.fill()` on the A06 `p03` `<select>`. They fail before native preview/save coverage. Use `select_option` for this control and rerun the exact final snapshot. A builder's corrected mutable fixture does not turn the r1 run into a pass.

### Independent executions on r1

Commands below ran with cwd `runs/e6-16-reviewer-r1` unless the root guarded PostgreSQL helper is shown. Every run used distinct `--basetemp` and `--junitxml` paths.

| Scenario / command | Observed result |
|---|---|
| `python -m pytest -q tests/test_entry_notifications.py tests/test_admin_kg_notifications.py tests/test_entry_notification_migration.py tests/test_alembic_domain_migration.py tests/test_service_cases.py tests/test_kg_template_preview.py tests/test_admin_kg_templates.py --basetemp=runs/reviewer-core-corrected-tmp --junitxml=runs/reviewer-core-corrected.xml --tb=short` | **163 PASS, 2 SKIP**, 385.92s. Skips are existing opt-in generic PostgreSQL migration checks without `TEST_POSTGRES_DSN`; not counted as validation. |
| Root: `python runs/e610_legacy_pg_probe.py runs/e6-16-reviewer-r1 tests/test_entry_notification_postgres.py --basetemp=runs/reviewer-pg-tmp --junitxml=runs/reviewer-pg.xml --tb=short` | **28 PASS**, 179.24s, actual isolated PostgreSQL 16 on loopback. Includes demonstrated transaction lock wait, JSON/model/FK parity, concurrency, ambiguous commit, empty migration cycle/populated refusal, COPY restoration, old retry and new write. |
| `python -m pytest -q tests/browser_kg_notifications.py --basetemp=runs/reviewer-browser-tmp --junitxml=runs/reviewer-browser.xml --tb=short` | **2 FAIL**, 27.01s, V1 fixture issue above. |
| `python -m pytest -q runs/e616_reviewer_probes.py --basetemp=runs/reviewer-probes-tmp --junitxml=runs/reviewer-probes.xml --tb=short` | **1 PASS, 1 FAIL**, 16.15s: working current renderer v2/old immutable receipt/new save PASS; F1 FAIL. |
| `python -m pytest -q runs/e616_reviewer_print.py --basetemp=runs/reviewer-print-tmp --junitxml=runs/reviewer-print.xml --tb=short` | **1 FAIL**, 12.90s, F2. Loopback browser only; external requests aborted. |
| `python -m pytest -q runs/e616_reviewer_capacity.py --basetemp=runs/reviewer-capacity-tmp --junitxml=runs/reviewer-capacity.xml --tb=short` | **1 FAIL**, 10.77s, F3. |
| Root: `python runs/e610_legacy_pg_probe.py runs/e6-16-reviewer-r1 runs/e616_reviewer_capacity_pg.py --basetemp=runs/reviewer-capacity-pg-tmp --junitxml=runs/reviewer-capacity-pg.xml --tb=short` | **1 FAIL**, 21.58s, F3 on actual PostgreSQL. |
| `python -m pytest -q runs/e616_reviewer_capacity_default.py --basetemp=runs/reviewer-capacity-default-tmp --junitxml=runs/reviewer-capacity-default.xml --tb=short` | **1 FAIL**, 23.10s, F3 after 52 committed writes at original limits. |

Independent recovery artifact: `runs/e6-16-reviewer-r1/runs/notification-postgres-recovery.json`, SHA-256 `ddced5f99c55281b57514f98a0e0d65c84718ec49f26c22b1a23c2cada1ef179`. Binary COPY archive: 16,385 bytes, SHA-256 `cedf6585a6ecc45135baed433b3a7e3b844406d3195c007915d9511318d23867`; created in the private temporary runtime by this execution. It establishes matching table counts/history, exact old receipt retry under removed current authority, native read 200, and a new revision after restoring into a fresh Alembic schema. This is **not** native `pg_dump`, PITR, a production backup or a real-data recovery claim. Native pg_dump remains UNKNOWN under existing Windows App Control 4551.

### Pre-audit condition coverage and scope

| Condition group | r1 assessment |
|---|---|
| All 13 literal source templates, combined RU/EN, blocked A08/A11, unresolved calculations, no approval/send flags | PASS source inspection plus all-template and legacy renderer tests. Values are labeled manual/unverified; outcome claims are not promoted to application facts. |
| Current identity, explicit storage/privacy/source policy, empty default, scoped applicant/application/attempt, terminal approved/refused | PASS inspected server/domain gates and executed negative/terminal/scope tests. No real policy or privacy/source decision supplied. |
| Preview/save signature, exact source pins, CAS, dedup namespace, changed application while waiting, post-lock clock/day | PASS inspected and executed tests, including actual PostgreSQL blocked transaction. Namespace is per application, not global content or delivery dedup. |
| Immutable canonical semantic replay, rehashed wrong text/source/unresolved/send/bool/version, retained renderer dispatch and current overlay | PASS inspected and executed tests plus independent functioning renderer v2 probe. Old read/retry use recorded v1; new write uses v2; different later templates do not silently supersede old ones. |
| Typed/escaped fields, strict HTTP parsing, bounded payload, no arbitrary body/recipient/fetch | Mostly PASS; **F1 FAIL** for valid native Unicode round trip. No body/network/outbox integration exists in the draft service. |
| Count/byte limits and read/retry at capacity | **F3 FAIL**, including normal default-limit operation and actual PostgreSQL. Existing low-limit tests do not cover the serialization mismatch. |
| Unknown commit, failed reread, unchanged signed retry after policy removal, failure rollback | PASS executed domain/native/PG tests. Original request key/envelope survives ambiguity; no false definite-rollback claim. |
| Isolation from payments/contracts/application events/interviews/quotes/tasks/messages/outbox | PASS actual before/after domain table counts and source inspection: one new draft row only. Test network guard and browser external-request block prevent actual providers. No real external service acceptance claimed. |
| Scoped schema, ORM/bulk immutability, fresh migration and populated downgrade refusal, PostgreSQL recovery | PASS on SQLite and actual PG module; COPY limitation stated above. |
| Mobile/no-JS, print all pages, default OFF, old read-only preview, runtime source assets | Old preview/gates and Docker COPY source paths PASS; **V1** prevents r1 native browser acceptance; **F2** fails multi-page print. Docker image execution/build remains UNKNOWN; file/package asset wiring inspected and rendered through actual checkout paths. |

I02 wording stays unchanged: **“Notification drafts/outbox with explicit policy gate and dedup”**, weight 1. A complete reviewed internal draft journal can satisfy it without recipients, a sender or outbox integration. On r1, F1–F3 and browser acceptance must be closed before PASS. No notification scheduling, delivery, consent/retention business decision, live source approval or release readiness follows from this local scope.

### Selected artifact hashes

All paths in this list are relative to `runs/e6-16-reviewer-r1/runs/`.

- `reviewer-core-corrected.xml`: `4406e21217d18329ff86ec70f8f97030433f3cc97729f0c8c7e1a4db8d82874f`
- `reviewer-pg.xml`: `ff475027aa55e94b6a711c28ab7df99f5e4c4eb59419cdb5234d052e645c5772`
- `reviewer-browser.xml`: `b158bd4b1f9f026b257f5c06a654e13c84eae5e6ea6893d3895962762b39a971`
- `reviewer-probes.xml`: `28ee4c15bf73b27825c5fb6c91e04db183a6903f9d46266ae64b67278bf22618`
- `reviewer-print.xml`: `6cd13bd6def8e03af0dfb55ce283f8858682cc635e6e3187d52f24aa1d37cafc`
- `reviewer-print/long.pdf`: `20109214cd855848488cb03a87ad3b0caaa7fed5012cfd2cbba8486c45a62a53`
- `reviewer-capacity.xml`: `9f25e784a5d2c9ee4d2504ec2ed4e5531fdd36149bb231c404962e710a9859d4`
- `reviewer-capacity-pg.xml`: `50f10d43ff34f2318448858596a598fe0a104fb1a713c6192f38617f97b63a42`
- `reviewer-capacity-default.xml`: `9bd89be2ea6fc3716c61ccb84e15096ff72e70ae39f7efca8f0a5166f609f1b2`

R1 findings and failing artifacts must remain preserved when a corrected snapshot is re-reviewed.

## Final r3 re-review: APPROVE for reviewed local synthetic scope

Exact target: `runs/e6-16-review-r3`, manifest `ai/reviews/2026-10-11-e6-16-snapshot-r3.json`, SHA-256 `627f6bf0079f85b381ca5eb1b7ef3c6ee5aa8b0713af71d2e810db04470d5253`, 23 LF-normalized files. Manifest base is `fca93ad8ed7d6a5fcdf53b741b254ba1241ad03e`; compared with r1 base, the base advance contains only E6-15 tests/evidence/docs. No E6-17 runtime change is included in this decision.

All 23 hashes were verified before copying, then reverified in the independent execution copy after all tests. Own copy: `runs/e6-16-reviewer-r3`. Original F1/F2/F3/default-limit/working-version probes were copied byte-for-byte from the r1 reviewer directory; the failing r1 artifacts remain intact. Actual source/test differences were inspected before relying on the new results. The extra policy/rules file changes are only trailing blank-line removal.

### Findings closed by actual behavior

- **F1 CLOSED.** The signed `_n_values` string uses UTF-8-preserving JSON; signature generation and validation are unchanged. The unchanged original native probe now saves, reads and exactly retries admitted non-BMP input. Frozen regressions also cover six 500-character non-BMP and mixed Cyrillic/HTML/quote values, with unchanged HTTP/domain limits.
- **F2 CLOSED for the tested Chromium print path.** The template reserves 23 mm at the bottom and repeats draft/no-send plus exact template, renderer and PDF source-page context in the page margin. Preview printing hides the previously selected saved draft, so it cannot carry a different template under the preview footer. The unchanged original long-print probe now produces four pages, each with warning and source/version context. All four rendered pages were visually inspected; every footer occupies y=798.1–819.4 pt within the A4 page, without clipping or overlap. Frozen desktop/mobile browser flows also save the maximum A07 Unicode fields and assert markers on every printed page.
- **F3 CLOSED.** The SQL pre-materialization check uses its own conservative 6× text-character bound; the row count, canonical UTF-8 row size and canonical UTF-8 journal limit remain unchanged and identical on append/replay. ASCII escaping and serializer spacing therefore cannot apply a stricter hidden semantic limit. Both original scaled-limit SQLite/actual-PG probes now pass, as does the original 52-save scenario with unmodified 4 MiB/128-row/128-KiB constants. New frozen SQLite/PG regressions additionally reject the next over-capacity write cleanly and preserve the old read and exact retry after current policy removal.
- **V1 CLOSED.** Frozen browser fixture uses the native select control correctly, and both resolutions execute the complete flow successfully.

No new blocking finding was found in this delta. The template selector displays the retained source `label` value `none`; this is nonblocking presentation polish, not source approval or a storage/authorization defect.

### Independent exact-r3 executions

Cwd is `runs/e6-16-reviewer-r3`, except the root guarded PG command. Separate basetemp/XML/recovery paths were used; no builder/auditor artifact was reused.

| Command | Observed evidence |
|---|---|
| `python -m pytest -q runs/e616_reviewer_probes.py runs/e616_reviewer_capacity.py runs/e616_reviewer_capacity_default.py --basetemp=runs/reviewer-original-probes-tmp --junitxml=runs/reviewer-original-probes.xml --tb=short` | **4 PASS**, 59.17s: original F1, original F3, original default 52 writes, and a functioning new renderer v2 with immutable old read/retry plus new v2 save. |
| `python -m pytest -q tests/browser_kg_notifications.py runs/e616_reviewer_print.py --basetemp=runs/reviewer-browser-tmp --junitxml=runs/reviewer-browser.xml --tb=short` | **3 PASS**, 66.33s: 390/mobile and 1365/no-JS, keyboard/native controls, empty/default policy, explicit confirmation, lost ACK plus failed reread, unchanged retry after policy removal, history, long Unicode save, all print pages, and unchanged independent F2 probe. |
| Root: `python runs/e610_legacy_pg_probe.py runs/e6-16-reviewer-r3 tests/test_entry_notification_postgres.py runs/e616_reviewer_capacity_pg.py --basetemp=runs/reviewer-pg-tmp --junitxml=runs/reviewer-pg.xml --tb=short` | **30 PASS**, 224.22s on actual isolated PostgreSQL 16. Includes original F3, new over-capacity refusal/retry, demonstrated application transaction wait, schema/FK/JSON parity, concurrency, tamper, rollback/unknown commit, migration cycle/populated refusal and fresh-schema COPY recovery. |
| `python -m pytest -q tests/test_entry_notifications.py tests/test_admin_kg_notifications.py tests/test_entry_notification_migration.py tests/test_kg_template_preview.py tests/test_admin_kg_templates.py --basetemp=runs/reviewer-core-tmp --junitxml=runs/reviewer-core.xml --tb=short` | **106 PASS, zero failures/errors/skips**, 342.23s. Windows emitted a WMI `0x8007000e` diagnostic during collection under the reported host memory pressure; the same process continued and exited 0 with the complete suite. No source/environment workaround was applied. |
| `python runs/e616_reviewer_package.py` | **PASS**: only notification knowledge code and the two Docker COPY asset directories were staged in a separate directory; isolated `python -I` loaded the retained and legacy catalogs and produced equal literal A07 text with no-send flags. This is a package-path smoke check, not an actual Docker image build. |

The r3 recovery artifact `runs/e6-16-reviewer-r3/runs/notification-postgres-recovery.json` independently records matching history/table counts, exact original receipt retry with current authority removed, native read 200 and a new revision 3 after fresh-schema restore. Its COPY archive is 16,359 bytes, SHA-256 `0e9eea5c00e170d511bf17751c1d88f43d2accaa342ef5b97c04c56ea456c28d`. Native pg_dump/PITR and real-data recovery remain UNKNOWN.

### Final criterion and limitations

**I02: PASS for the unchanged fixed criterion's internal persistent-draft scope**, conditional on the protocol's separate final-audit reconciliation. The reviewed implementation supplies policy-gated, application-scoped durable drafts, exact confirmation dedup, immutable retained-version replay, explicit manual provenance, honest source/unresolved labels, capacity-safe retries and recovery. It does not implement or claim scheduled notification delivery, recipients, transmission or an outbox sender.

All pre-audit runtime conditions applicable to this bounded draft slice now have the above source/negative/schema/native/recovery evidence. Original read-only preview behavior remains tested. Real privacy/retention/source approval, actual mailbox/provider behavior, production activation/release and compatibility with untested browser print engines remain UNKNOWN or outside scope. Real policy remains absent; this approval is not a production release gate.

Selected r3 evidence hashes, relative to `runs/e6-16-reviewer-r3/runs/`:

- `reviewer-core.xml`: `5fbab4b1931815778ed49b57d16d2a375672bc0bbd990568f5dbe3b397f25912`
- `reviewer-original-probes.xml`: `95655db361389ef04b88676b02f70d6b1dc9eb829c67dbb44fc2f058e83973ca`
- `reviewer-pg.xml`: `7ba6cc21fcc5528959057bb8a5f511f41da9fae6c455bb5b34c435762d48b9b5`
- `reviewer-browser.xml`: `83910c758d2427f1d566ff5b08be122cdf1173b500fae25a9ac9624c6d937f03`
- `notification-postgres-recovery.json`: `54ef853500cc94c83d72d25d68829d1ffb502aa63cffbd879d3a01c7d47279c4`
- `reviewer-print/long.pdf`: `2e52de3e2256811d1ddd154dac544ef46cf82b6c06f9be5fbb62fa7c825fd7e0`
- `e6-16-notification-browser/draft-long.pdf`: `a962419cca19e1434becb508f7b9f2b2a6e66e86c2c6493c6bf8ced243a6da11`
- `reviewer-package.json`: `cdacf45fc407cff3390290f224a6471da1c80d384b1f2dd071e1e23dd8869407`
