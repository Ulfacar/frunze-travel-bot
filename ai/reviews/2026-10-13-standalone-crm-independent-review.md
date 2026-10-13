# Standalone CRM — independent implementation review

Reviewer: `publication_review`. CRITICAL / solo, independent requirement/code review and own synthetic adversarial execution. **Final R5 disposition: APPROVE within the local implementation / authenticated HTTP / manual-intake / internal-task scope described below; no deployment or release approval.** CRM-R1–R4 were corrected in R2, CRM-R5 in R4, and the residual external-asset/UI issue CRM-R6 in R5, all with own corrective execution. Original failures and fixture limitations are preserved below. Actual PostgreSQL/image/restart/TLS/browser and separate release audit remain separately required; J05 is not approved.

## Requirement and inspection boundary

Read `ai/tasks/2026-10-13-standalone-crm-release.md`, the actual admin authentication/scope/native route code, original three requested UI changes, dedicated factory/intake/bootstrap/packaging and called identity helpers before builder conclusions. The new service must retain working native CRM operations and persistent private records while excluding bot startup, providers, customer sending and the existing production database. It must not manufacture source, privacy or business approvals.

Frozen R1: `runs/crm-standalone-r1`, base `5200ac1bdec2faab82840e01e6372b33851b9a1d`, **19 overlays**, snapshot raw SHA256 `d9eceffc23d5769fd200b6bd0cf1d9e4569048e49a38cd6e98e431631f27e879`. Own archive `runs/crm-independent-r1` was created by `python -X utf8 runs/crm-review-freeze.py r1` from Git archive plus individually LF-verified overlays. No `.env`, root application import, server, PostgreSQL, provider call, real data or runtime edit. Original PDF fixture SHA256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2` is used only for real draft bootstrap in a disposable SQLite database.

| Inspected R1 file | LF SHA256 |
|---|---|
| `app/crm_main.py` | `360ea6601bc65f562a351b8e2b1a4d068945fc2fb5c21fb3c0430af097bf8b9b` |
| `app/crm_intake.py` | `99b295d7e2f7c900b46420430639847f54cf47bb5c746995a7ec770465953b43` |
| `app/admin/contracts.py` | `ea1978f507a3c218a07840a6297ff2b920e82457c7dd69655b9b6461a88115b6` |
| `app/admin/router.py` | `33400d16b2cfc542e5e38a9db9d5b7fbcc0600a6c534b6bd91f369ae6da37cb1` |
| `scripts/crm_initialize.py` | `104639dcbdd99961dfa827fa187f8f12783df24f6d000b2fd879506f771276ab` |

## Confirmed findings

### CRM-R1 — HIGH: manual international identity changes during case opening

`crm_intake.intake_submit` accepts an explicit international number and stores canonical digits under `manual_visa:`. The new `contracts._identity` manual branch validates those digits but then falls into legacy `normalize_phone(raw_key, assume_e164=True)`. That helper handles bare nine-digit Kyrgyz subscriber numbers before its protocol-guaranteed E.164 branch. Actual input **`+372555123`** is retained as `manual_visa:372555123`, then the native preliminary POST creates a real case whose `ContactIdentity.normalized_value` is **`996372555123`**. A different country/person identity has been invented. Accepted eight-digit **`+12345678`** cannot continue: its correctly isolated preliminary GET returns422. The first multi-test run's404 was later traced to fixture database leakage, not this runtime boundary; details below.

Own connected original controls both FAIL in `test_manual_international_identity_survives_actual_case_open`. Preserve explicit international intent in the dedicated manual branch and the subsequent ContactService path; keep old WhatsApp/Telegram guards unchanged. A pure string-helper assertion alone is insufficient: corrective evidence must inspect the actual saved case contact.

### CRM-R2 — MEDIUM: lost commit acknowledgement loses controlled exact retry

`crm_intake.intake_submit` only handles `IntegrityError`. A SQLAlchemy availability failure after the real transaction commits escapes as generic500. Own test uses the actual session/transaction, injects `OperationalError` only after successful transaction exit, and confirms **one persisted receipt** before checking the response. Result: **500 / Internal Server Error**, without the original signed form. This is an uncertain-save recovery defect, not a failed transaction or synthetic fake success.

Corrective contract: controlled503/no-store and the unchanged original fields/key/signature; repeating that form must return the same durable intake with no duplicate. Also cover availability failure before commit without claiming a save.

### CRM-R3 — MEDIUM: retained retry can silently redirect to another person after pointer corruption

The old-receipt path validates `actor` and submitted `payload_hash`, but fetches `receipt.conversation_id` and checks only visibility. An own integrity probe changes that single FK to another valid, administrator-visible manual conversation. Repeating the **original signed first-person request** returns303 to the **second person's preliminary form**. Neither payload hash nor CSRF detects the substituted retained pointer.

This requires stored-row corruption; ordinary peer HTTP access is not the attack. The bounded correction is to verify the retained Conversation identity against the canonical submitted command (`manual` channel, namespace, exact user_id/phone/direction) before redirect, retaining genuine history/retry semantics rather than accepting visibility as subject identity. Reject a mismatch explicitly; do not create a replacement person as a recovery side effect.

### CRM-R4 — MEDIUM: visible calendar task creation is excluded from the standalone routes

The existing `/admin/calendar` returns200 and renders `form[action="/admin/calendar/task/create"]`, but R1's `ROUTER_POSTS` only permits login/logout/direction. A real same-origin authenticated submit of that rendered task action returns404. Empty legal policies mean the E adapters do not replace ordinary operator tasks. The task acceptance explicitly includes working tasks; a visible dead form is not a safe feature boundary.

Select and review the existing internal task operations individually, preserving ownership and bound-task guards, or expose a deliberate own-case task path. Do not admit all old router writes: send/resend/suggest/followup must remain denied. The old generic phone path strips `+` before normalization, so the CRM-R1 international-identity edge must also be considered before enabling that path.

## Own execution evidence

Commands executed only in the env-free own archive:

- `python -m pytest tests/test_reviewer_crm_boundary.py -q --tb=short --junitxml=runs/reviewer-boundary-r1.xml`: **3 genuine FAIL, 1 fixture FAIL, 1 PASS /22.46s**. Nine-digit identity, postcommit acknowledgement and retained pointer controls demonstrate runtime failures. The eight-digit404 was initially misattributed; its independently isolated runtime failure is recorded below. Positive peer ownership/role revocation/origin/outbound-denial control passes, with fresh fixture confirmation in R2.
- `python -m pytest tests/test_reviewer_crm_boundary.py::test_visible_calendar_internal_task_create_is_connected -q --tb=short --junitxml=runs/reviewer-calendar-r1.xml`: **1 genuine FAIL /8.07s**, rendered task form→404. This test was added after the first five-case run; the first XML is not represented as a six-case execution.

The passing control creates a real manual intake for `medina`; a different visa peer cannot read or claim its identity through a new intake; removing that configured peer invalidates its existing session. A sibling origin is denied. Send/resend/followup routes on a real owned conversation remain404/405 without calling the instrumented outbound function or changing conversation/message/intake/case counts. This is a bounded positive control, not a complete authorization audit.

## Reviewed direction and pending gates

The dedicated factory avoids `app.main` and its unconditional scheduler/webhooks. Explicit secure host-only session cookie, current configured principal/credential binding, strict role interpretation, same-origin writes and selected native routes are coherent boundaries. The inert one-stage intake product and draft source import do not themselves approve a legal route. Fresh initialization accounts for both legacy CRM Base and Alembic DomainBase; image includes current knowledge assets and local HTMX. These are source observations, not proven image/deployment acceptance.

The requested three-file visual baseline is preserved: system font, readable buttons and quieter layout; its previous behavior tests are retained. Final actual standalone mobile/no-JS/print/error presentation, image/startup validation, real isolated migrated persistence/restart/recovery, release routing/TLS, and separate final audit still require the final candidate and their own evidence. No J05 owner/source/privacy/business/pilot approval is inferred or supplied. All own R1 test processes have finished; only own archive/probe/report files were written.

## Corrective R2 and the fixture isolation correction

R2 own archive `runs/crm-independent-r2` verifies all20 overlays on the same base; manifest raw SHA256 `2ad2550457c95f3cfd8bcc1d9b5fb6479fc0a5987d0a140856d3292ec0abe6e4`. Actual source diff was read before corrective execution. Manual identity returns the explicit canonical number, intake catches SQLAlchemy availability failure with its original form, retained retry verifies the exact manual subject, and selected task routes are now available with scoped owner/direction checks and preserved international phone intent.

The initial unchanged six-case execution was **5 PASS /1 fixture FAIL /33.60s**, `runs/crm-independent-r2/runs/reviewer-boundary-r2.xml`. Investigation found the shared builder `crm` fixture replaced the DB sessionmaker but did not reset `panel.store._pg_store`, which retained the previous test database. The second phone case looked up the wrong database and reported404. No production code was changed for this correction. Own R2 tests now explicitly bind their panel store to the current fixture's sessionmaker; their original six test bodies/assertions are unchanged. Root R3 independently adopted a fixture reset.

The original R1 eight-digit case was also rerun alone in a fresh process: **1 genuine FAIL /9.92s**, `runs/crm-independent-r1/runs/reviewer-international8-r1-isolated.xml`. Its actual unsupported bare international normalization returns422. This separates the genuine eight-digit defect from the earlier fixture404 and preserves both original artifacts.

Corrective command in own R2: `python -m pytest tests/test_reviewer_crm_boundary.py tests/test_reviewer_crm_calendar.py -q --tb=short --junitxml=runs/reviewer-boundary-calendar-r2-bound-store.xml` — **7 PASS /1 genuine FAIL /36.98s**. All original six behaviors now pass. The seventh passing test executes actual quick/calendar and conversation-card task creation for eight-/nine-digit international numbers, reads the exact saved ContactIdentity, rejects a forged other direction and a peer's subject, demonstrates no mutation from peer complete/cancel/reschedule, preserves00:30 Bishkek as18:30UTC on the previous date, then executes the owner's real reschedule/complete/cancel. These are state assertions, not status-code-only acceptance.

**CRM-R1–R4 CLOSED on R2 within these tested boundaries.** Their original failures remain above. R3's router is unchanged from R2, so the new finding below still applies there.

### CRM-R5 — MEDIUM: newly exposed task lifecycle swallows storage failure

The standalone task-create paths now return503 on storage failure, but `_apply_calendar_action` and `_apply_task_action` retain the legacy catch/log/return behavior. An actual saved own task is still `planned` after an injected `OperationalError` before completion writes, yet the native completion POST returns a normal303 redirect with no error. The own eighth test `test_task_action_storage_failure_is_not_reported_as_normal_redirect` fails specifically **303 !=503** after independently verifying unchanged task state.

Standalone complete/cancel/reschedule/snooze and card task actions should return a controlled failure instead of normal confirmation/navigation when the transaction outcome cannot be confirmed. The legacy service can retain its old behavior outside standalone mode. This is a newly admitted path; it is not a reason to broaden the denied external-route set.

## Final R4/R5 corrective assessment

R4 catches task lifecycle storage failures in both `_apply_calendar_action` and `_apply_task_action` and returns503 only in standalone mode. Existing non-standalone catch behavior is preserved. Own unchanged failure control now proves503 and unchanged planned task state. **CRM-R5 CLOSED.**

The R3 manual conversation template was inspected and exercised with an actual created intake and task. It shows the exact international identity, local scheduled time and internal task, escapes an injected script-shaped display name, and removes provider send/resend/suggest/takeover/release/followup controls. However, the containing `/admin` shell still unconditionally referenced the external Sortable CDN, which the standalone self-only CSP blocks. Own R3 card test failed only that final asset assertion; its earlier identity/task/output-escaping/no-provider-action assertions passed. R4 retained the same defect. **CRM-R6 — LOW, presentation/asset mismatch:** standalone had an unnecessary blocked external script for drag behavior whose mutation route is not admitted. This was not an observed outbound customer call or CSP bypass.

R5 removes that script only for standalone; the existing initializer checks whether Sortable exists and returns safely. The same scoped template changes hide unsupported board/inbox archive and bulk-selection actions and misleading manual-source advertising/intercept badges. The local HTMX asset and self-only CSP remain intact. Own original R3 card probe was copied byte-for-byte to R5 and now passes, including actual local asset delivery. **CRM-R6 CLOSED.** Real browser rendering is not inferred from this HTTP/DOM test.

Own final commands, each run inside its own env-free archive:

| Candidate and command | Actual result | Artifact |
|---|---|---|
| R4: `python -m pytest tests/test_reviewer_crm_boundary.py tests/test_reviewer_crm_calendar.py tests/test_reviewer_crm_card.py -q --tb=short --junitxml=runs/reviewer-final-r4.xml` | 8 PASS, 1 FAIL /47.518s; only residual external Sortable reference fails | `runs/crm-independent-r4/runs/reviewer-final-r4.xml` |
| R5: `python -m pytest tests/test_reviewer_crm_card.py -q --tb=short --junitxml=runs/reviewer-card-r5.xml` | 1 PASS /9.840s | `runs/crm-independent-r5/runs/reviewer-card-r5.xml` |

The eight R4 passes comprise both actual international identity cases, real postcommit lost-ack recovery, retained pointer rejection, owner/peer/session-revocation/origin/provider-route denial, rendered calendar task creation, actual foreign-number task ownership/date/lifecycle checks, and the task-storage503 correction. Their original test bodies were compared by AST with R1; the only necessary harness change was binding each fixture to its own panel database. Do not represent this mapped evidence as a single nine-pass R5 execution or as a full suite.

The concern about legacy `_find_conv_by_phone` matching the final nine digits was checked against actual standalone control flow: standalone quick creation selects the exact `manual_visa:<canonical international digits>` identity and verifies its channel/phone/direction/visibility; the suffix helper remains only in the non-standalone branch. Eight-/nine-digit international positive and other-person/other-direction negative controls run through these real standalone paths. This review does not certify legacy suffix behavior outside the new service.

## Final immutable mapping and packet

R5 base: `5200ac1bdec2faab82840e01e6372b33851b9a1d`, **25 overlays**. Frozen manifest raw SHA256: `d3f0ac33d5256896d59c9ce77037388354c40bea025d7780861fc2ea00a124b8`. All overlay identities were independently checked in both `runs/crm-standalone-r5` and own `runs/crm-independent-r5`, with no `.env`. R4 raw manifest SHA256: `e2dc47fbc2a2e868e31588a38c63156931289fce7ab013ab0f32be86ad0e9340`.

Independent `python -X utf8 runs/crm-independent-evidence.py` verifies every R1–R5 overlay, parses all eight own original/corrective XML artifacts, compares original boundary test ASTs and the unchanged card probe, and proves the **only R4→R5 source differences are `_attention.html`, `_board.html`, `boards.html`**. All R4 runtime and tests map unchanged to R5. Output `runs/crm-independent-final-evidence.json`, SHA256 `315be53eacd791d0f5b2e6a5a91e2eba50664011dec336518e0ad2f362592520`, contains the full source/manifest/XML hashes, failed test names and exact timings.

| Final reviewed file | R5 LF SHA256 |
|---|---|
| `app/crm_main.py` | `c20d3bd5aa5ae66521ab506b4e2923e3f4fb345c71d0d0aefb78af515e57f542` |
| `app/crm_intake.py` | `b26a471361641d64e893bd16b9a508f04eb9474c0aa8961726a42d44fbdd28b6` |
| `app/admin/contracts.py` | `5db89a8af3e4e8ecad975ad4454c9968a51973566625c58134575d51ca2bd16f` |
| `app/admin/router.py` | `fdada2803ad82785dfcc126b6b6779667fa4e56fa96ab7b8ea6a81795614a021` |
| `app/admin/templates/_conversation.html` | `74bd395fcf44c3a22a80834cc8838df18bbed8737dd18d088db9356deb393384` |
| `app/admin/templates/base.html` | `b2a7789c2dbef0fa19e3466ec9c68e0531b4dcdfe1bd397bcfb0155b50fed867` |
| `app/admin/templates/boards.html` | `2226dff0bf0586e09b5b9919cb0b52d2e0bd5619856dcf656e65b7bcbafbf11a` |
| `app/admin/templates/_attention.html` | `f47385b2435cb265cc5d38a43bc550bc60cc8513912cb878fa6708b8f1a1b78b` |
| `app/admin/templates/_board.html` | `b932292d26439491d8591bcb5c6175ac9a8d37dfbc0978f6fb5291b8077626a1` |

Promotable own probes: `runs/crm-independent-r4/tests/test_reviewer_crm_boundary.py`, `runs/crm-independent-r4/tests/test_reviewer_crm_calendar.py`, and `runs/crm-independent-r5/tests/test_reviewer_crm_card.py`. The calendar probe imports the boundary fixture; preserve that dependency and the fixture's explicit current-database binding when promoting. No root runtime or tests were modified by this reviewer.

## Scoped verdict and outstanding release evidence

**APPROVE — the reviewed R5 local implementation scope.** No known unresolved finding remains in the examined dedicated entry point, selected-route/auth/current-account enforcement, manual intake/identity/receipt recovery, internal task scope/lifecycle and HTTP presentation boundaries. The correction retains original legacy behavior outside standalone rather than permitting bot/provider writes.

**Not a release GO.** Own execution used synthetic disposable SQLite fixtures, DomainBase metadata creation and fixture schema-version setup; it does not prove production-dialect migrations, PostgreSQL locking, bootstrap resume, volume/restart durability, backups/restore, deployed cookies/proxy/TLS/hostname isolation or Docker runtime behavior. The separate auditor owns the bootstrap/body-bound/release-bundle findings and their corrective evidence; this report does not self-certify them. Actual dark/light/mobile/no-JS/print browser acceptance on the standalone service remains separate from this HTTP/DOM proof. No live data, customer sending, source/legal/consent policy activation, J05 owner acceptance or deployment permission is inferred. All own test processes are finished; no own server or PostgreSQL process was started.

## R6 deployment-guard delta — independent source addendum

**Scoped APPROVE, with the same separate release gates.** Source-first inspection of frozen `runs/crm-standalone-r6` found only three changed files: `Dockerfile.crm`, `compose.crm.yaml`, and `app/crm_main.py`. Base remains `5200ac1bdec2faab82840e01e6372b33851b9a1d`; all25 overlays were verified against own env-free `runs/crm-independent-r6`. R6 manifest raw SHA256 is `f87bb0b219cdcd57322f961123864734e0d0ff8712ab1c11643742cfff3d14ea`.

The Docker image now executes `/usr/bin/setpriv --no-new-privs --` as its entry point, and its healthcheck explicitly uses the same wrapper. Compose removes the earlier engine-level `no-new-privileges` option to permit the host's Snap AppArmor transition; non-root image user10001, all-capabilities drop, read-only filesystem, isolated network/loopback port and resource limits remain. Uvicorn additionally limits concurrency to16; exhaustion may therefore produce an intentional capacity503. No HTTP route, principal/identity/session, form, native task or provider boundary is changed.

Before importing native handlers or creating the service, the production configuration validator now requires POSIX UID10001 and reads `/proc/self/status`, refusing startup unless `NoNewPrivs=1`, `Seccomp=2`, and both effective/bounding capability masks are zero. Missing values default to refusal; a missing/unreadable status file or non-hex capability value raises before app creation rather than enabling service. The existing test bypass remains limited to the explicit function argument **and** `sqlite+aiosqlite`; it is not an environment switch that bypasses the production PostgreSQL guard. The guard does not itself assert the active AppArmor profile or all five capability sets; those remain deployment checks. The trusted entrypoint necessarily starts before setting its own no-new-privileges bit, so this change is not described as engine-enforced restriction on every possible overridden `docker exec` command.

`python -X utf8 runs/crm-independent-r6/verify_delta.py` verifies all25 overlays and proves the other22 files unchanged, plus AST identity of `crm_main.py` after excluding only its `os` import and configuration validator. Therefore own R4/R5 functional evidence maps to R6 without claiming another execution. Mapping artifact: `runs/crm-independent-r6/runs/reviewer-r6-source-mapping.json`, SHA256 `a992a2131396eb9119b6c2b60a5f19fe6f27fb5ea2255d8fb5a7cf6d055d252b`.

| R6 changed file | LF SHA256 |
|---|---|
| `Dockerfile.crm` | `577f88dbc0108a05820b0ef22ee6a8102e5ec3de66cc757fe7d14f282d5cc559` |
| `app/crm_main.py` | `68c6903d487bca64b29c8f7e0021548a3f08a87bbb6768d1af71e9a5b50b224a` |
| `compose.crm.yaml` | `f99c1d3be95889c20f3c0f4083b42ec1a3791b195edae6bd7615ef4a96d6b821` |

The separate auditor is executing narrow synthetic kernel-configuration negatives and bundle verification; they are not duplicated or attributed to this reviewer. Builder-reported actual Linux/AppArmor/process checks, fresh PostgreSQL initialization and healthy image startup have not been independently executed here and remain release evidence for the final auditor to reconcile. No additional source defect was found in this bounded delta. No own application import, container, server, PostgreSQL connection or runtime edit was used for this addendum.

## R9 final source mapping — private network and readable native controls

**Scoped APPROVE for frozen R9; deployment/public-hostname approval remains separate.** All30 R9 overlays were independently verified in the frozen candidate and own env-free `runs/crm-independent-r9`. At the time of verification all30 root overlay files also matched, including all28 runtime/packaging/test files; no documentation mismatch had occurred yet. Base remains `5200ac1bdec2faab82840e01e6372b33851b9a1d`; R9 manifest raw SHA256 is `6f484aefcd1fc7679a0d4de0304a4372d1969879275e610ffc4f7eba187b952c`.

Actual R6→R9 changes are confined to six files: Compose, two presentation templates and three promoted reviewer tests. Every application Python overlay, the Dockerfile and other previously reviewed assets remain identical to R6. The three promoted tests preserve original own probe ASTs exactly after the single fixture import rename from `test_reviewer_crm_boundary` to `test_standalone_crm_recovery`; no assertion was removed. Earlier own R4/R5 behavior evidence therefore remains applicable, with no claim that a new full suite was executed here.

Compose removes the app's published loopback port and assigns `172.30.78.10` on the existing internal `172.30.78.0/24` network. The gateway remains `172.30.78.1`, matching the unchanged Uvicorn trusted-proxy address. There is no published app or database port in this candidate. `EXPOSE8000` remains image metadata, not a new Compose port mapping. This source change is compatible with a host proxy reaching the private address; actual host routing, incoming proxy-header handling, TLS and network isolation require the separate deployment evidence. No broader proxy trust, customer channel or provider route is added.

Standalone login styles now pair accent backgrounds with the existing theme-specific `--on-accent` text token and surface/input text tokens, use16px labels/inputs/buttons and bound the card width to the viewport. Calendar styles use the existing theme palette for statuses and primary/hover controls, remove completed-task opacity loss and keep form fields readable. Its manual-client link now says `Карточка`, and phone entry shows an explicit international example plus an accessible label. The changes preserve form actions, field names, task semantics, HTML escaping and authentication. Apart from the additive phone accessible label, the changed appearance/copy is guarded by `standalone_crm`. This is a source assessment; it does not replace the actual dark/light/mobile browser evidence owned by the deployment review.

Own verification command: `python -X utf8 runs/crm-independent-r9/verify_delta.py`. Artifact `runs/crm-independent-r9/runs/reviewer-r9-source-mapping.json`, SHA256 `87581e91dda6fa6174c5e4fb6464838771117566d59fce5e4a18d979214ac196`, records all30 identities, root correspondence, the exact six-file delta and promoted-test AST checks. Critical changed production files:

| R9 changed production file | LF SHA256 |
|---|---|
| `compose.crm.yaml` | `1f2912038aa2a8636223d843d3c07356cfc7f478d828f3b922906144554f6213` |
| `app/admin/templates/login.html` | `2e422098edb9c50b44e7b4b22dde541f33ff2043d71cc75236c509e8ad652258` |
| `app/admin/templates/calendar.html` | `6591189a03b44a944be47fcbf3a33183457d87880107e206cea7fc1d8da96d39` |

No new defect was found in this bounded delta. No full suite, app import, server access/mutation, PostgreSQL connection, provider call or public deployment was performed by this reviewer for R9. Actual Linux/runtime/restore/browser evidence and the user's public-domain decision remain separately attributable to their owners; no source-policy/J05 approval is inferred.
