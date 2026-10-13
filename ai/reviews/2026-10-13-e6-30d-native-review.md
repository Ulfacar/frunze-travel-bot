# E630D — independent native review

**Final disposition: APPROVE for the scoped native interface at frozen R16.** Original recovery and print defects are corrected; the builder's later token/scope correction was independently reproduced and verified. This is not whole-D/domain/schema/PG approval or a release gate.

Reviewer `/root/publication_review`; CRITICAL / solo protocol, independent of the implementation. Scope: signed RU/EN actual-anchor and conditional-review page, its existing task adapter calls, authentication, recovery and rendered presentation. Source/domain approval, production, actual personal records and external messages are excluded. No root implementation or test file was edited.

The task `ai/tasks/2026-10-13-e6-30d-actual-anchors.md`, actual native controller/template and called domain boundaries were read before builder conclusions. Original R7 and corrective R8 are independently reconstructed Git archives with their exact overlays and the verified original source PDF; root `.env` is neither read nor copied.

## Exact targets

- Final R16 base `7f7a59a2c17033f3ae45a5434c1087d1fdfe7ea1`, 59/59 overlays independently verified in the own archive. Manifest raw SHA256 `74abf5d9bbe9d8b59de22726e5261b09a584add0d0282eb47d89c9d548bf6910`.
- Final controller LF SHA256 `f54144ca9ef8de9e1a8dccd78cc3511f522f844c22c8f7e96aacfb787a12441c`; final template LF SHA256 `5f4a80ffa76e78135677e7887b50fbe469891206748395b5d72366b8fb536480`.
- R14 manifest raw SHA256 `1622e195a410957bf79fedb4363086cf75b647b5af8368dbb30c193fd8d7c21c`, same base as R16, 59 overlays. The template is byte-identical R14→R16. The only native-controller delta is strict hexadecimal CSRF/signature validation and controlled404 for four concrete absent/foreign scope errors.
- R8 base `5e91ddb2b85563c331f43f24351befd1a255d31a`, 59/59 overlays verified. Manifest raw SHA256 `7c31e46a6b713a658e3479af2da947fe29381c32e7f5e39ab3bc7fa11acc0194`.
- R8 `app/admin/kg_actual_dates.py` LF SHA256 `0fa99db7fb0326d6b205bb9701b1fb49e72f67ec0017d651bbc366405467df5a`.
- R8 template LF SHA256 `46324884011a5fddf2b84b1b5d2fc0290a57fa046d66cf2575f808218c14bc8e`.
- Own archives: `runs/e630d-native-review-r7`, `-r8`, `-r14`, `-r16`; creation command `python -X utf8 runs/e630d-native-freeze.py <version>`.
- Machine-verifiable inventory: `python -X utf8 runs/e630d-native-evidence.py` — PASS; `runs/e630d-native-review-evidence.json` SHA256 `6eee258e0024204889f861ff9a464b4684ed8f8e7090107bdd4fb7aba9068320`. It records exact snapshots, own XML outcomes and hashes of every retained screenshot/PDF. No root environment is imported by the inventory.

## Confirmed original defect

**ADUI-01 — HIGH: acknowledged database commit followed by lost response is reported as invalid input and loses the original request.**

Trigger: the real `conditional_deadlines.record` or `entry_anchors.record` commits successfully, then raises `EntryStorageUnavailable`; the subsequent page reader is healthy. R7 catches it in `(EntryStorageInvalid, ValueError)` because `DomainError` inherits `ValueError`. HTTP returns422 with fresh forms, not503 with the exact original signed retry. The existing builder test also made the reader unavailable, which masked the status error but did not preserve the retry form.

Own unchanged R7 probes: `tests/test_reviewer_actual_dates.py::test_lost_commit_healthy_reader_keeps_exact_original_retry[conditional_review/record]`. Actual result **2 FAIL / 1 PASS, 133.96s**, `runs/e630d-native-review-r7/runs/reviewer-http-r7.xml`. Both failures assert actual422 versus required503. Response HTML retained under that archive's `runs/reviewer-http/`. The positive test records the complete new signed visa renewal context and a conditional review and rejects route/profile/CSRF/query tampering.

R8 independently inspected correction adds an explicit `EntryStorageUnavailable` branch before `ValueError`. Both original probes and the complete visa-context positive passed on R8, including exact retry and no fresh operation forms on uncertain responses. No original failure was overwritten. The R14 controller is byte-identical to R8; final checks also exercise it against the later domain corrections.

**ADUI-02 — MEDIUM: printing in dark mode inherits the dark background, and operation summaries print as a useless additional page.**

Own real R8 Chromium PDF preserves dark body RGB(13,20,21) / pale text RGB(230,237,237). Both RU-dark and EN-light PDFs have a second page containing only collapsed record/withdraw summaries. Actual page images were independently opened and inspected. The print CSS hid forms but left their enclosing operation details and inherited screen surfaces.

Evidence: `runs/e630d-native-review-r8/runs/reviewer-browser/{ru-dark,en-light}.pdf` and their `*-print-{1,2}.png` renders. Browser result **FAIL** on the dark-background oracle; the second-page defect was also directly observed. Screen contrast, focus, no overflow, real no-JS saves and retained cancellation after authority removal passed before that final assertion.

R14 template correction explicitly makes the printed page/panels white with black text, resets height/min-height, and marks only operation details `no-print`; historical visa hash disclosure remains. This exact source diff was independently inspected. Corrective browser execution **PASS**: both PDFs are exactly one nonblank page, contain the actual date and omit operation summaries. Both final pages were independently opened and visually inspected.

**ADUI-03 — MEDIUM robustness / LOW error classification, builder-identified then independently verified:** malformed non-ASCII CSRF or signature reaches `hmac.compare_digest` and raises an uncaught `TypeError`; absent application is misreported as503. The own R14 originals produce **3 FAIL / 10.34s**, preserved in `reviewer-token-original-r14.xml`. There is no demonstrated authentication bypass or data disclosure. R16 rejects non-ASCII, blank, uppercase and wrong-length tokens with403 before HMAC; absent application, foreign applicant and foreign case return404 with no-store. The unchanged negative tests pass on R16.

## Completed verification

R8 completed: `python -X utf8 -m pytest tests/test_reviewer_actual_dates.py tests/test_reviewer_actual_browser.py -q --junitxml=runs/reviewer-native-r8.xml` in the own archive — **3 PASS / 1 FAIL, 233.65s**, no skips. The only failure is ADUI-02.

R14: same two own test modules, `--junitxml=runs/reviewer-native-r14.xml` in `runs/e630d-native-review-r14` — **4 PASS / 256.76s**, no skips. Additional controls cover strict body size, duplicate query parameters, cross-session rejection, an actual changed renewal-context pin producing409, registry GET503 without operation forms, and exactly one printed page without operation summaries.

R16: `python -X utf8 -m pytest tests/test_reviewer_actual_tokens.py tests/test_reviewer_actual_overdue.py -q --junitxml=runs/reviewer-corrective-r16.xml` — **4 PASS / 51.30s**, no skips. Besides the unchanged three token/scope originals, an actual dated source calculation is read at 20 October: the existing 19 October review remains visible as overdue in both RU/EN, while the actual document expiry remains 1 November. A malformed document date returns 422, without an uncertain retry or anchor write. The viewer does not invent a later document expiry or silently change the saved facts.

These are separate bounded executions, not a final whole-repository suite. R14's normal flow and visuals map to R16 through the exact template identity and inspected narrow handler delta. The later domain history-read cache and other domain corrections require their separate domain review; this report does not recertify them.

Browser probe uses a loopback-only uvicorn app and Chromium, blocks all non-loopback requests, and exercises mobile390/dark/RU, desktop1365/light/EN with JavaScript disabled, actual signed save→task creation→authority loss→retained clear, contrast, keyboard focus and actual PDF rendering. R8 artifacts are retained unchanged; R14 output has its own `runs/reviewer-browser/`.

Final paired screen checks: **230/230 visible element foreground/background samples meet 4.5:1 contrast**, no horizontal page overflow, labeled controls, native disclosure and checkbox forms, three-pixel visible keyboard focus. The real no-JS POSTs produce a saved review and planned task, then authority removal shows “Date not established” alongside clearly labeled recorded evidence. Explicit retained withdrawal cancels the task. Merely viewing the page does not claim cancellation. Registry loss shows a controlled 503 page with no mutation forms. Actual screen/error/authority-loss images and both print pages were independently inspected. These are the stated two theme/viewport combinations, not an exhaustive device matrix.

An initial attempt failed during collection on a syntax error in the new reviewer browser harness, before runtime execution. It is retained as `reviewer-native-r8-collection.xml`; the harness was corrected. This is not an application defect or a passing test.

## Authority and scope assessment

The handler reuses the existing full-admin gate, KG-entry feature gate and server-side write gate. URL IDs, actor, session CSRF, operation, conditional evidence hash, revisions and retained profile/application-event pins are signed. Posted facts remain operator-entered evidence and are validated again by the real domain service. An old preview after a real renewal-context correction refuses with 409. A signature cannot be reassigned to another applicant, profile, query language or session. The body/field bounds include the full new visa-renewal context; its actual signed save/reload/duplicate and review path passed.

Router registration and the application-card link were inspected: the link uses the selected application's own applicant/case IDs and only the four supported procedures. Authority defaults remain `None` / empty; viewing a form grants no source, price, work, filing or stay permission. A historical date and an active stale task are not represented as a fresh source-approved calculation. Creating/reconciling and clearing are explicit confirmed operations; domain predicates, source locks and task ownership remain enforced by their existing services.

No PostgreSQL, provider call, deployment, live policy change or score change was performed. Actual source/legal approvals and all real-person records are outside this synthetic verification. The report author wrote only own archive/probe/evidence files and this review. A separate final auditor and the remaining domain/migration/concurrency evidence are still required for the complete D change.

**Scoped native verdict: APPROVE. No remaining native blocker was found in the reviewed R16 scope.**

## R20 native delta addendum — five source-specific visa review choices

Independently inspected frozen `runs/e6-30d-r20`; manifest raw SHA256 `6a9044896481b021894f3dec49b036ffac61bb74c8c411e5ab8f809789e81506`, LF SHA256 `012156250f6afe5a3cac0655e2b12849fb9fbd93f7218ae3ca2f4781edfc84c3`. Own env-free archive `runs/e630d-native-review-r20` was created with the existing freeze script; all72 overlay hashes were checked and no root `.env` was read or copied.

Controller LF SHA256 `54be5d2066d359c0903e966d4fee78d888e7b880f19d2d60e84de7a5d569d3ed`. Its only change from reviewed R16 is five RU/EN `RULES` labels: TS exit5calendar days, declared B renewal preparation15working days, RL RES preparation15/ review10working days, S RES review10working days. AST outside that dictionary is identical; all pre-existing entries are unchanged. The template is exactly the reviewed R14/R16 file, LF SHA256 `5f4a80ffa76e78135677e7887b50fbe469891206748395b5d72366b8fb536480`. Prior source-gate, error/retry, security, no-JS, contrast and print evidence therefore maps through the unchanged native implementation. This does not re-audit the new domain rules.

Source comparison confirms the displayed units/intents against §19.2/19.3/19.5 printed80 and §19.7 printed81. The B wording explicitly limits its meaning to **declared renewal preparation**. The labels promise internal review/preparation, not legal permission or client delivery. Query validation still uses the closed `RULES` map; the existing signed envelope binds the selected rule/language and exact subject.

Own command, in the isolated R20 archive: `python -X utf8 -m pytest tests/test_reviewer_new_visa_rule_labels.py -q --junitxml=runs/reviewer-new-visa-labels-r20.xml` — **1 PASS, 13.33s**, no skips. The connected HTTP probe opens a real own visa application and tests all five choices in both RU/EN:200/no-store, exact selected option, readable localized label, explicit unknown date with empty real authority, no record/review/reconcile form, and unchanged anchor/deadline/task row counts. Unknown rule suffix and duplicated rule query both return422. No source approval, write, task or provider call is manufactured by selecting a new label.

Actual XML: `runs/e630d-native-review-r20/runs/reviewer-new-visa-labels-r20.xml`, raw SHA256 `cfae1063a80391e649832724d211f1ff983118cc7d50bb166b1cd35f2bf16431` (JUnit duration13.323s).

No additional whole browser or PG suite was necessary for five labels with unchanged template/control flow; the existing visual evidence remains bounded to its stated theme/viewport pairs. New domain applicability/arithmetic and final D audit remain separately required.

**Scoped native verdict extended to R20: APPROVE.** No new native blocker was found. E630E draft work and whole J01 acceptance are outside this addendum.
