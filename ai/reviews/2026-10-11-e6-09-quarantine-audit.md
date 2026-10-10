# AUDIT: E6-09 bounded document quarantine

- Task: `ai/tasks/2026-10-10-e6-09-document-quarantine.md`.
- Risk/mode/target: CRITICAL / solo / local synthetic implementation; independent review and final audit required.
- Auditor: separate Codex agent `/root/quarantine_audit`; builder: parent `/root`.
- Independence: INDEPENDENT. Requirements and existing source inspected before any implementation verdict or builder test conclusions.
- Pre-audit base: `fix/tours-search-quality`, HEAD `26655d40464ecef0ff0647e309e3a725fcc01aae`, with existing staged/unstaged E6-08 changes and untracked task. These changes were preserved.
- Proposed design under audit: bounded in-memory multipart parser; JPEG/PDF bytes in the existing domain database; one transaction writes package receipt plus immutable quarantine row; policy is absent by default; no read/download/release/scanner routes. This supersedes the task card's earlier filesystem draft.

## Pre-audit assessment

Database bytes avoid filesystem orphan/commit coordination, but they also become part of database backups and recovery. The configured policy must explicitly authorize `domain_database` and refer to approved privacy/retention evidence. Merely supplying a syntactically valid reference/proof is not evidence that real operation is authorized. No policy is configured by this task.

Existing code has useful foundations: named full-admin authorization, native OFF/workday/write gates, scoped case/application lookup, case then application locking, SQLite physical transactions, bounded package history, exact request receipts, and clean transaction retries. These are source observations, not runtime acceptance of the new adapter.

| Risk | Existing location / trigger | Required correction or evidence |
|---|---|---|
| CRITICAL: upload bypass becomes approval | `entry_package_rules.apply_operation` accepts manual `receive` and `review`; current metadata alone has no quarantine knowledge | Refuse review and effective acceptance when a current item fingerprint matches retained quarantine bytes anywhere in the same application, including another item, manual metadata receipt, definition upgrade, and a checked item predating upload. Preserve historical journal readability without declaring quarantine released. |
| CRITICAL: bytes attached to wrong receipt | Package event scoped key is `(id, application_id, case_id)`; FK alone does not prove receive action/item/version/hash/actor | Constrain scoped parent; verify receipt semantics and immutable checksum binding. Negative tests for cross-case/application/event/item/version and forged metadata. |
| HIGH: partial write or duplicate | `entry_storage._transaction` retries from a new session; lost commit acknowledgement is deliberately uncertain | Receipt and bytes must share that transaction; failure before commit leaves neither, after commit leaves exactly one of each. Exact retry returns the original receipt even after later package operations; changed actor/app/item/revision/hash/type/size conflicts. |
| HIGH: parser resource or framing abuse | Multipart parser is new attack surface; generic form parsing can spool bytes to disk | Enforce auth/OFF/workday/write/policy before streaming; independently cap total raw input, file bytes, field/header/boundary/name sizes, field and file counts. Reject duplicate fields/headers, missing final boundary, truncation/disconnect, no file/two files, oversized Content-Length and unknown/chunked size. No parser/rendering/extraction of uploaded document content. |
| HIGH: quota race/unbounded persistence | Existing locks order case then application; SQLite ignores row-level FOR UPDATE | Count all retained quarantine rows/bytes, not current item versions. Read quotas and insert under the same application lock. Concurrent last-slot uploads, same-key duplicates, conflicting keys, limit rollover and SQLite retry evidence required; actual PostgreSQL locking remains UNKNOWN until run. |
| HIGH: BLOB memory amplification | SQLAlchemy selecting entire model ordinarily loads binary columns | Read/HTML/history/quota paths must select bounded metadata only. No bytes in templates, return values, errors, snapshots, raw filenames or logs. Ensure checksum/size verification does not load all application files for every page. |
| HIGH: policy/retry confusion | Native forms sign actor/case/application/revision/key and policy can change between GET and POST | Bind upload to current explicit policy digest and server-owned types/storage/limits; recheck policy and authority before new persistence. Policy expiry/change must not permit a second upload or grant broader rights. Fail closed on absent/invalid policy. |
| HIGH: destructive schema rollback | Existing migration0025 rejects populated/offline downgrade | Additive migration/model parity, FK enforcement, empty upgrade/downgrade/upgrade, populated downgrade refusal retaining version/table/rows, offline refusal, PG DDL; ORM update/delete/bulk guards. Existing history must remain intact. |
| MEDIUM: spoofed content/path | Client MIME/extension/name are untrusted | Validate declared type, allowlisted extension, minimal signature and supplied SHA256 independently; reject mismatches and traversal/malformed names. Never use filename as storage key. UI must describe only signature/type checks, never safety/malware clearance. |

## Required acceptance scenarios

1. Synthetic minimal JPEG and PDF accepted only by an explicitly named full administrator and valid policy; metadata receipt stays `received`, UI says quarantined, package not approved, no bytes can be downloaded.
2. Policy absent, invalid, expired/future, unauthorized actor, wrong storage/type, invalid/maximal limits and browser-supplied policy/storage fields fail closed. Scoped manager/unauthenticated/OFF/workday/write-gate requests do not consume body or touch storage.
3. Malformed multipart at adversarial chunk boundaries, duplicate security fields and headers, too many fields/files, oversized name/header/boundary/field, empty or truncated file, missing terminator, disconnect, false/missing Content-Length, oversize body/file, MIME-extension-signature mismatch, checksum mismatch and traversal all leave zero new rows/events.
4. Wrong case/application/item/revision and closed/replaced application leave zero new rows/events. Same content cannot escape quarantine through another item/manual receive/review/approval. Old package histories still replay.
5. Before-commit and after-commit faults; exact retry after lost acknowledgement, reread failure and later successful operation; changed file/policy/scope/actor cannot reuse original key. All successful rows remain a single immutable receipt/bytes pair.
6. Racing identical requests return one receipt; conflicting same key yields conflict; final quota slot race permits only one new row; retained old file versions still consume quota. No new filesystem files.
7. SQLite migrated schema matches model, raw invalid FKs/constraints rejected, ORM mutation blocked, downgrade populated/offline refused. Actual disposable PG runtime and recovery are separately reported PASS or UNKNOWN.

## Checks actually performed

Only read-only source/context inspection (`Get-Content -Encoding UTF8`, targeted `rg`, `git status --short`, `git log -5`, `git branch --show-current`, `git rev-parse HEAD`, `Get-FileHash`). No tests, external services, production access, source edits or Git mutation by auditor. No nested AGENTS.md was returned under the inspected app/tests/alembic/ai-playbooks scope. Some initial wide command output was truncated; relevant source was subsequently reread in bounded sections.

Relevant inspected pre-implementation fingerprints (SHA256):

| Path | SHA256 |
|---|---|
| `app/domain/entry_document_packages.py` | `9d491ae8b52ab6fa2770eaa7a86f8a5d7375c789e816aea0905dbe0aefe8fbe5` |
| `app/domain/entry_package_rules.py` | `4460467d35f8c64fd753dee09b6a1a11070094a346abae92051e5b9ddeb3ae17` |
| `app/domain/models.py` | `8e6460e922f35780c99db548867ae4962586ad1f95a60502c54c4138cc9ca9b1` |
| `app/domain/entry_storage.py` | `9b3c04a54dc425635f598e1de603b1145a44185ee09db30e48261bd5a7cfd23e` |
| `app/domain/entry_applications.py` | `1afb49ff71a19b2b1dbfb84f793b44dd93d316bbb6e73574c45bf3d212998f2b` |

## Pre-audit verdict

GO for bounded local implementation and synthetic verification of the proposed design. Final audit: UNKNOWN pending exact implementation snapshot and independent verification. This is not release approval; real-file operation, configured privacy/retention policy, production migration/deployment and malware release policy remain outside authorization.

## Final-audit first assessment (implementation pass 1)

Base `419fe40cca04f8ed9c65e0386c48c18764c32424`; target uncommitted implementation including new quarantine domain/policy/admin/parser/template/migration/tests, not only tracked `git diff`. Initial source fingerprints matched the env-free `runs/e6-09-local` archive before independent probes. In particular `app/domain/entry_quarantine.py` SHA256 was `0c7d3c19c6d8e6bbd9d87d28ca5085e2fc094161abc5b78b1258ee82ebdc9eed`.

Source assessment: authorization and empty default policy precede multipart parsing; binary storage is `deferred=True`; receipt and file insert share an owned SQL transaction; retained quotas are evaluated under case/application locks; signatures only classify the file; no content/download/release route exists. Existing package review and effective acceptance are checked against quarantine fingerprints across items in the same application. These aspects address the principal pre-audit risks.

| Severity | Location | Trigger / consequence | Independent evidence | Correction requested |
|---|---|---|---|---|
| P2 / integrity | `app/domain/entry_quarantine.py:metadata` | Claimed file document version is compared only with its own request, not the actual referenced receipt state. Rehashed corrupt metadata can be displayed as a different document version. | Synthetic upload version1; raw SQL changes file version to399, request expected version to398 and recomputes its two hashes. `read_document_package` returned `FORGED_VERSION_ACCEPTED 399 ACTUAL_RECEIPT_VERSION 1`. | Compare file metadata with the already verified package state at its receipt revision, including exact item/version/fingerprint and receipt timestamp. |
| P2 / integrity | `app/domain/entry_quarantine.py:metadata` | A missing file row is treated as no quarantine even when a package upload receipt remains. A later ordinary review becomes possible after out-of-band deletion/corruption. | Synthetic upload; raw SQL deletes only its file row. Read returned no quarantine and new review returned `MISSING_BYTES_PAIR_ACCEPTED 0 REVIEW_STATUS checked`. | Verify one-to-one completeness between upload receipts and retained file rows, including a missing quarantine table after upload history exists; fail closed for orphaned receipts. |
| P2 / native flow, initially missing | `app/admin/templates/kg_document_package.html` | No navigation path from native package to upload page in initial workspace source. | Targeted `rg` found no quarantine link; existing native test asserts that link. | Add the link; builder reported a correction, independently pending confirmation. |

The two integrity reproductions are corruption/recovery checks using authorized synthetic raw SQL; they are not claims that an ordinary browser user can modify database rows. No production or real files were used.

Auditor commands: PowerShell here-string piped to `python -`, working directory `runs/e6-09-local`; `tests.conftest` network guard imported before fixture initialization; `tests.test_admin_kg_entry.env.__wrapped__` instantiated with `pytest.MonkeyPatch` and a new `tempfile.mkdtemp(prefix='auditor-quarantine-tmp-…', dir='.')`; SQLite `PRAGMA foreign_keys=ON`; normal `setup`/`upload` helpers create only synthetic data. The two raw SQL scenarios above are executed only against those disposable fixture databases. Both probes exited0 and confirmed the findings; fixture engines/session clients were disposed normally. No source was edited by the auditor.

Pass1 verdict: **FIX_REQUIRED / NO-GO for final local acceptance until integrity findings are fixed and independently rechecked**. The implementation may continue locally. Release authorization remains outside scope.

## Fix verification (candidate, before final manifest)

Builder corrections inspected in actual code: `metadata(..., history=(events, states))` checks file version/fingerprint/item/case/application and timestamp against the already verified receipt snapshot; receipt IDs with reserved `quarantine.` keys must match binary rows exactly. A missing table with surviving upload receipts fails closed. Public metadata mutation rejects reserved request keys. Native package navigation now links to the file form.

Additional inspected changes deny quarantined fingerprints through another application's package or legacy inventory and adjust effective status/pending counts. This denial selects only the current bounded fingerprint set and returns no other application's owners, rows or bytes. Historical metadata itself is retained. Review forms are hidden for effective quarantined rows and backend review denial remains authoritative.

Independent command, env-free `runs/e6-09-local`, local FK-enabled SQLite and network guard:

```text
python -m pytest tests/test_entry_quarantine_migration.py tests/test_entry_quarantine.py -k "rehashed_metadata or missing_binary or rollback_lost_ack or concurrent_requests or race_for_last_slot or does_not_load_blobs or cross_application or reserved or downgrade or parity or postgresql" -q --basetemp auditor-quarantine-tmp-final
```

Result: **13 PASS / 25 deselected / 1 Starlette deprecation warning / 17.22s**. Exercised version/timestamp forgery rejection, missing row/table rejection, before-insert/before-commit/after-commit fault recovery, duplicate writers and last-slot competition, metadata reads without BLOB loading, additive schema/model parity, populated/offline downgrade refusal, and PostgreSQL DDL generation. The `cross_application` selector did not select the new `another_application` test; no pass is claimed for that scenario from this command. PostgreSQL runtime was not exercised.

Final source manifest and final independent probe rerun remain pending in this audit record. Candidate checks do not themselves approve later edits.

## Final audit against the reviewed snapshot

Final target: the **22 files** in `ai/reviews/2026-10-11-e6-09-reviewed-snapshot.json`, base `419fe40cca04f8ed9c65e0386c48c18764c32424`, uncommitted snapshot with CRLF-to-LF normalized file SHA256 values. Manifest file SHA256 at the last independent check: `83a2ce79243c1d50364f01077832d6603a541306f1e1f159f21bd07988c4f6c8`. Auditor independently recomputed every listed hash in both the workspace and env-free archive: **22/22 matched**, including after the final checks.

The final import-only correction extracts unchanged response headers/status labels to `app/admin/kg_document_ui.py` and references package UI policy at request time, avoiding direct circular imports. Auditor inspected this change, cold-imported the quarantine module successfully, and ran the two native flow/gate tests again. Domain, parser, migration and behavioral test hashes remain the same as the preceding 21-file frozen target used for the full independent targeted checks below.

### Final independent checks actually performed

| Command / scenario | Result | Environment / limitation |
|---|---|---|
| Original custom probe repeated on frozen target, now expanded to version, timestamp, missing row, missing table; all four assert both package read and direct backend review fail with `quarantine_integrity_failed` | **PASS 4/4 scenarios** | Separate synthetic FK-enabled SQLite fixture databases, no source edits; manifest verified before/after execution. |
| `python -m pytest tests/test_quarantine_multipart.py tests/test_admin_kg_document_quarantine.py tests/test_entry_quarantine.py::test_quarantine_cannot_be_laundered_through_another_application tests/test_entry_quarantine.py::test_legacy_inventory_also_blocks_globally_quarantined_content -q --basetemp auditor-quarantine-tmp-envelope` | **32 PASS**, 1 deprecation warning, 24.24s | Frozen 21-file target; domain/parser logic unchanged in final 22-file target. Real HTTP test client, bounded multipart, access/OFF/workday/write/policy gates, forged/session/scoped forms, invalid bytes, lost acknowledgement/reread failure/exact retry, cross-application and legacy denial. |
| `python -m pytest tests/test_entry_quarantine_migration.py -q --basetemp auditor-quarantine-tmp-final-migration` | **3 PASS**, 1 deprecation warning, 7.60s | Migration rerun after source freeze; FK/type/size constraints, old schema preservation, model parity, empty cycle, retained rows on populated downgrade refusal, PG DDL and offline downgrade refusal. No PG connection. |
| `python -m pytest tests/test_admin_kg_document_quarantine.py::test_native_upload_receipt_history_and_quarantine_blocks_review tests/test_admin_kg_document_quarantine.py::test_policy_and_access_gates_before_file_parser -q --basetemp auditor-quarantine-tmp-final-imports` | **2 PASS**, 1 deprecation warning, 9.05s | Final 22-file target after import extraction; verifies native navigation, no content leak, no duplicate, quarantined review denial and pre-parser gates. |
| Manifest recomputation in root and archive; cold `import app.admin.kg_document_quarantine` followed by package/inventory imports | **PASS**, 22 matching paths | Final manifest above, env-free archive, no external service calls. |
| `git diff --check` | **PASS** | Existing CRLF normalization warnings only; no whitespace defects. |

Earlier **13 PASS** candidate tests remain supporting recovery/concurrency evidence; their exact command/result is recorded above. Repeated tests are listed separately rather than added to a misleading unique-test total. Browser/mobile/no-JavaScript/print test source was inspected; the builder reported two browser passes, but the auditor did not run that browser command and does not claim an independent browser run.

### Acceptance coverage and limitations

| Criterion | Evidence status | Basis |
|---|---|---|
| Explicit absent-by-default server authority, named existing full-admin restriction, storage/types/validity/limits/privacy/retention binding | **PASS for implementation** | Strict policy source and settings inspection; independent HTTP gate tests. No actual owner policy was created or approved. |
| Bounded JPEG/PDF intake, MIME/extension/signature/checksum handling, no caller-selected storage path or retained filename | **PASS for local synthetic scope** | Parser/file validation inspection, independent multipart/HTTP tests; type signature is expressly not a malware verdict. |
| Atomic scoped receipt/file pairing, retry and version/timestamp integrity, retained quotas and failure recovery | **PASS for local synthetic scope** | Both confirmed integrity findings fixed; custom adversarial probes, independent recovery/concurrency tests and migration tests. |
| Quarantine cannot become reviewed/accepted through same item, another item/application, or legacy inventory | **PASS** | Backend/read logic inspection, independent cross-application and legacy tests, native review suppression. No release/download/content endpoint exists. |
| Old histories retained; additive migration, metadata-only reads and ORM immutability | **PASS for inspected/local scenarios** | History replay code, candidate deferred-BLOB/ORM tests and final SQLite migrated schema tests. Direct privileged SQL is outside the ORM immutability boundary; corruption is detected as tested. |
| Native disabled/error/success/exact retry states, no filename/content exposure | **PASS for HTTP scenarios** | Independent native tests. Browser layout/mobile/print is builder-reported evidence, not an auditor-run check. |
| Actual PostgreSQL runtime/concurrency and backup restoration | **UNKNOWN** | Only PostgreSQL SQL generation and SQLite runtime were exercised by auditor; no production/external connection authorized. |
| Real-file operation, real privacy/retention approval, deletion/release/scanner policy, production deployment | **N/A for this local target** | Explicitly outside authorization; implementation does not invent or configure these policies. |

### Final verdict

**GO for the reviewed local synthetic E6-09 target identified by the final 22-file manifest.** No blocking finding remains in that snapshot; the version-binding, missing-pair and native navigation findings are closed with source and independent runtime evidence. This final audit is independent of the builder and does not substitute for the separate required reviewer.

**No production/real-file GO is issued.** Actual PostgreSQL/recovery remains UNKNOWN; approved real privacy/retention/storage authority and any production release require their applicable separate gates. The code remains disabled by default, with no uploaded real files, live policy configuration, production migration or deployment performed by this audit.

## Reopened audit: issued-document boundary (supersedes the 22-file verdict)

The parent subsequently confirmed an adjacent bypass in the issued-document journal: a quarantined SHA could still be used for issued-document review/delivery/receipt, or an earlier completed review could remain effectively current. This boundary was not covered by the previous 22-file verdict. The audit was reopened rather than treating that verdict as approval of the expanded implementation.

The latest target is the **25 files** in the same manifest, now SHA256 `252cf12ca1124535fd711bc081d810bc4b029242e7f96c832a169922a4c47137`. Base remains `419fe40cca04f8ed9c65e0386c48c18764c32424`; target remains uncommitted. Added source scope is `app/domain/entry_issued.py`, `app/admin/kg_issued.py`, `app/admin/templates/kg_issued.html`, plus strengthened cases in the already listed `tests/test_entry_quarantine.py`. Auditor independently verified **25/25 normalized hashes in root and archive before and after the new probes**. Previously tested quarantine/domain/parser/migration code is unchanged; earlier evidence remains valid for those paths.

Actual delta assessment:

- New review, delivery and receipt operations query quarantine before appending. The guard checks the supplied issued-file hash together with actual current and issued-passport hashes. A falsified replacement file hash cannot bypass this guard because the existing reducer then rejects its mismatch with the stored file version/fingerprint.
- `_effective_view` is used for current/historical reads, exact-retry returns and newly appended operations. It sets effective verification, completed delivery and current checked receipt to false if any relevant file/passport is quarantined. Immutable stored snapshots and the fact that a receipt was recorded are preserved.
- Native issued UI shows the quarantine reason and removes review/delivery/receipt forms; backend checks still reject forms obtained before quarantine.
- Correction, replacement metadata and factual travel remain recordable. Deadline consumers inspect actual travel facts from verified history, not issued-verification flags, so this does not grant travel permission or release content.

Independent verification used the same env-free fixture/network-guard pattern as the earlier custom probes, with separate `auditor-quarantine-issued-file-*` and `auditor-quarantine-issued-passport-*` synthetic SQLite databases. Source was not edited. For **each of the two targets** (issued file and passport), the probe:

1. Records a file, a valid review, all three delivery channels, and a checked receipt; verifies that all three effective status fields were true before quarantine.
2. Obtains signed native review/delivery/receipt forms, then uploads the matching synthetic bytes into another application's quarantine.
3. Verifies current and historical summaries now have all three effective flags false while the immutable snapshot is unchanged and `receipt_recorded` remains true.
4. Replays the exact review request, every original delivery request, and original receipt request; each return is quarantined and cannot restore effective verification.
5. Submits all three previously obtained signed forms; each returns422 with the quarantine notice and no matching action form. No new issued revision is added.
6. Records an actual travel fact; verifies its count becomes1 while all three effective verification flags remain false and earlier review/receipt facts are retained.

Both probes exited successfully in the same Python invocation (9.80s process duration; one existing Starlette deprecation warning):

```text
MANIFEST_MATCH 25 252cf12ca1124535fd711bc081d810bc4b029242e7f96c832a169922a4c47137
ISSUED_ADVERSARIAL_PASS file complete_before_false_after_stale_POSTs_denied_retries_and_history_overlay_travel_retained
ISSUED_ADVERSARIAL_PASS passport complete_before_false_after_stale_POSTs_denied_retries_and_history_overlay_travel_retained
MANIFEST_STILL_MATCHES
```

**Revised final verdict: GO for the reviewed local synthetic E6-09 target identified by this 25-file manifest.** No blocking finding remains in the inspected issued-document delta. This verdict supersedes the earlier 22-file target; it preserves the earlier verified evidence and adds the independent checks above. Separate reviewer requirements still apply. PostgreSQL runtime/recovery, real policy authority, real files and production remain UNKNOWN or outside this local target exactly as recorded above; no production/real-file GO is issued.
