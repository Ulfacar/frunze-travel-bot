# E630C — independent current aftercare reader review

Reviewer: `calculation_review`. CRITICAL / solo, independent implementation review, reviewed-local target. **APPROVE exact R28 two-file current dependency reader and native read-only panel. All four confirmed findings are closed; no open scoped runtime defect remains.** The separate final audit remains a separate gate. This report does not approve whole E630C, J01/J02, the work deadline/task adapter, real source/policy approval, production or unrelated CRM base-shell changes.

## Requirement, source and identity

Read original PDF §19.5–19.8 and the U06 registration continuation in §19.13 before builder conclusions. The source distinguishes visa, separate resident-card approval/collection and registration aftercare. A parent visa approval must not become a resident-card decision. A separately initialized REG journal must supply its own current certificate receipt; its withdrawal/stop cannot resurrect a duplicated parent attestation. Parent stage and historical receipts remain independent of this current display.

Original supplied PDF SHA256: `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`. The fixtures exercise recorded facts and explicit synthetic policies; they do not establish legal eligibility or automatically assess periods or business policy.

All application imports and checks run in independent env-free Git archives of base `7b0475b536592f6d254d607fb4baf3619a6e7fff`, with hash-verified frozen overlays and PDF. Root runtime, `.env`, real data/providers, PostgreSQL, and release operations were not used or modified.

Final candidate: frozen **R28**, own archive `runs/e6-30c-aftercare-review-r28`, 22 verified overlays, manifest LF SHA256 `963218af4092993995ac24084055dbe568f573f9aa4cee46d554bb1de3e33956`. Only these two runtime files are in this verdict:

| File | LF SHA256 |
| --- | --- |
| `app/domain/entry_processes.py` | `700af9a4d7d5a4a51c4281cd3fda6e27c1d5d66c313a955aa355cc8aaa8e54d3` |
| `app/admin/templates/kg_process_journal.html` | `d88a511f57338133d35e580edfccaf1872b1fabd650e8fde09a00ad4ed564f96` |

R25's own 16-overlay manifest LF SHA256 was `aea8100f1529972097daedeeb2cddadecc591efe619f470baaac4f8f06c66a40`; its reader is byte-identical to R28. R28 changes only the scoped template's existing display macro to localize six decision values; R25 template SHA256 was `cc403c4daa64610cd2b0bdf66408788bf79ff6b7b1ae83b5b35257a87737ed08`. The exact diff was independently inspected, then actual native/browser rendering repeated on R28. No source-resolution, authority, currentness or history semantics changed in this mapping.

The other overlays, new default-empty work-deadline authority/config, model/migration/task implementation, old work catalog and unrelated UI are excluded. Later identity mapping must be explicit if these two files change.

## Confirmed findings and correction

| Finding | Original actual evidence | Correction |
| --- | --- | --- |
| AC1: parent reader ignored a current certificate receipt in the child's separately initialized REG journal. | R20 ordinary application/process writes: child receipt true, parent displayed unknown; genuine FAIL. | R21 validates the child journal and resolves its own current receipt. |
| AC2: a duplicated parent certificate receipt remained true after actual withdrawal in the initialized child's journal. | R20 actual withdrawal, no corruption; genuine FAIL. | R21 child state takes precedence; stopped/catalog-mismatched child returns unknown with no parent fallback. |
| AC3: collection actually dated September 1 became current after separate official RES approval on September 4. | R21 ordinary immutable records, genuine FAIL. | R24 current-only overlay requires the receipt's actual date to be on/after its own latest approved application event. Old manual reducer/replay is unchanged. |
| AC4: after a real child receipt was saved with a future service timestamp and the clock returned, it displayed true in the current panel. | R21 clock injection only, no row tampering; genuine FAIL. | R25 suppresses current parent dependencies for a future parent head and makes a future child process receipt unknown. Equality remains a valid boundary. |

Original artifacts remain intact:

- `runs/e6-30c-aftercare-review-r20/review-aftercare-r20-original.xml`: two genuine AC1/AC2 failures plus a separate RES fixture setup error (package initialized after official approval). SHA256 `9e5cad8c86521d868cb6c6cab3a34b4706189f0336e4c60988e5a61efd723984`.
- `runs/e6-30c-aftercare-review-r21/review-aftercare-r21.xml`: **3 PASS / 83.957 s**, original AC1/AC2 probes unchanged; RES fixture ordering corrected. SHA256 `ef38174fa8e7f1e3d44099649b70353486e1950b9fa49ab8b0b1aea899b62d2e`.
- `runs/e6-30c-aftercare-review-r21/review-aftercare-boundaries-r21.xml`: **3 PASS / 1 genuine FAIL / 24.685 s**; stopped/catalog/corruption controls passed, AC3 failed. SHA256 `89d360791e86b1b33521ce1ecb1814ca1878f3d6c965d474be69e777add7ba5c`.
- `runs/e6-30c-aftercare-review-r21/review-aftercare-clock-r21.xml`: **1 genuine FAIL / 11.778 s**, AC4. SHA256 `54e502346f8c9aca883614e47b75e5ba849744253701a2041a8ed6ac40ccb1bf`.

The initial R20 `review-aftercare-r20.xml` was three fixture failures from an invalid ten-character portal reference, before the target behavior; preserved separately and not runtime evidence. Its source copy is `tests/reviewer_aftercare_first.txt`.

Final exact-R25 independent runs:

| Artifact under `runs/e6-30c-aftercare-review-r25` | Result | SHA256 |
| --- | --- | --- |
| `review-aftercare-final-r25.xml` | **10 PASS / 1 harness-only FAIL / 148.008 s**. All original AC1–AC4 probes passed unchanged. The failure compared a selected read view against a write receipt containing two extra metadata fields; parent future suppression already passed before that assertion. | `2fa8604596e8cb8116d08c9a957664d336d354e43b6bfc3bf3863a25eccbe320` |
| `review-aftercare-native-r25.xml` | **2 PASS / 19.191 s**. Corrected parent equality control plus actual Chromium mobile/no-JS dependency panel. | `d166d90136bb893c5f467171d2c10deb39ef183fa0e22d72daa8c78faf815778` |

Commands: `python -X utf8 -m pytest tests/test_reviewer_aftercare.py tests/test_reviewer_aftercare_boundaries.py tests/test_reviewer_aftercare_time.py -q --basetemp .pytest-review-r25 --junitxml=review-aftercare-final-r25.xml -p no:cacheprovider`; then narrow `tests/test_reviewer_aftercare_time.py::test_parent_future_head_hides_current_panel_and_equality_recovers tests/browser_reviewer_aftercare.py` with separate temp/XML paths. No broad repeat was needed. The first clock-test source is preserved as `tests/reviewer_aftercare_time_first.txt`; only removal of write-only `current_revision`/`readiness` from the comparison was corrected.

These cover **12 distinct final passing controls**, across the mapped runs; not a fabricated all-green initial suite. Both actual future application-approval and package-approval writes refuse current domain reading with `process_source_from_future`, native no-store 503 and no positive panel; setting the current reader clock to the exact source timestamp restores the appropriate positive. Parent future-head hiding and exact equality recovery also pass. No runtime or fixture limits were weakened.

Independently viewed R25 `runs/review-aftercare-browser/dependency-390.png` and `dependency-1365.png`: the panel is readable, no horizontal overflow, correct child link, no forms; mobile shows current certificate `Да`, the desktop/no-JS historical view shows `Неизвестно` after actual child withdrawal. The current-versus-parent-stage explanation remains visible. This certifies this panel in the frozen fixture only, not the separately edited base shell or full CRM redesign. The observed raw enum `approved` copy issue is closed by R28 localization.

Final R28 native delta: `python -X utf8 -m pytest tests/browser_reviewer_aftercare.py -q --basetemp .pytest-review-r28-native --junitxml=review-aftercare-localized-r28.xml -p no:cacheprovider`, **1 PASS / 22.402 s**, no failures/errors/skips; known upstream deprecation warnings only. XML `runs/e6-30c-aftercare-review-r28/review-aftercare-localized-r28.xml`, SHA256 `b5b43343f2a0108a37cea59eafc3c57d6e16b37076fd51deb26143a04edeef0a`. This repeats the browser control with an additional `Одобрено`/no-raw-`approved` assertion, not an extra unique domain scenario. Independently viewed both fresh R28 panel screenshots under that archive's `runs/review-aftercare-browser`: localized decision is readable on 390px and 1365px/no-JS, positive and withdrawn child receipts remain correctly distinct. All earlier genuine and harness failures remain preserved.

## Independent coverage and limits

Own tests use actual FK-enforced SQLite journals and native routes. They cover wrong-person linking with unchanged parent receipt; parent visa approval versus separate RES decision; approved own package versus consent withdrawal; absent/expired/mismatched process policy; revoked manual source authority; current and historical selection; own REG positive/withdrawal precedence; stopped/catalog-mismatched child; actual hash corruption causing domain refusal/native no-store 503 and restoration; actual receipt/approval chronology and clock rollback.

Application identities/events and package source rows also run through the existing `Evidence.prefix`, which rejects future source timestamps before a current positive can return. The new reader retains the existing fail-closed whole-read error policy for corrupt/future source streams. A full dependency panel is not promised when source integrity is unavailable.

The code reuses the existing case lock and one post-lock current timestamp. Child `_history` is bounded and nonrecursive; it validates retained receipts without invoking dependency reading. The new path has no append, reducer mutation, external operation or parent stage promotion. Historical selected receipts remain exact while the separately labeled current panel can change.

No new migration, SQL locking mechanism or writer was introduced by these two files; actual PostgreSQL concurrency/recovery is N/A for this read-consumer delta, not a claim that SQLite proves PostgreSQL behavior. Existing work-process/PG recovery evidence belongs to its separate reports. Whole-project suite and production verification are not claimed.
