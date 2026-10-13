# E630E — independent native review

Reviewer: `publication_review`. Scope: signed RU/EN native operator SOP review, existing CRM presentation and recovery. Requirement/source/controller/template were inspected before builder conclusions. This is a CRITICAL independent native review; source catalogue, domain integrity, migration, PostgreSQL concurrency and final audit have separate owners. No release, legal/source/business approval, live data, external messages or J01/J03 acceptance follows from this report.

## Current verdict

**APPROVE — native scope on R14, with mapped R9/R10 evidence and own R14 expiry control.** All four original findings below are corrected and independently verified. Own R9 HTTP suite: **3 PASS /270.07s**. Own R10 real browser: **1 PASS /85.04s**, including mobile RU/dark, desktop EN/light/no-JS, actual save/task/withdrawal, controlled errors and two readable one-page PDFs. Final screens and both PDF pages were personally inspected. R14 has the same template and only one new localized reason mapping; its actual nested-policy-expiry HTTP control is **1 PASS /86.93s**. This is not whole-E/domain/J01/J03 or release approval.

## Frozen identities and environment

- Base: `d1d5138c15e9101b3ef73d1f38126c98e2f716a0`.
- Original `runs/e6-30e-r2`, own env-free archive `runs/e630e-native-review-r2`; all 20 manifest overlays checked by LF SHA-256 against the archive. Controller LF `82f3661961ad6b0de8a5c3d7a1ad19270ff1e5074ae3be20fb0490de5252b903`; template LF `a8823313a74ad030b33749938c54107e66fe739301bbf886592622791610064e`.
- Current preparation `runs/e6-30e-r6`, own env-free archive `runs/e630e-native-review-r6`; all 28 manifest overlays checked. R5/R6 deliberately include the preserved `base.html`/`boards.html` UI baseline that R2 omitted. R2 visual failures remain original evidence; final visuals must use the later shell.
- Archive creation: `python -X utf8 runs/e630e-native-freeze.py r2` / `r6`. The script uses Git archive plus checked overlays, refuses `.env`, and copies only the verified source PDF (SHA-256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`). Root `.env` was not read. Synthetic SQLite with foreign keys, real local HTTP and loopback Chromium; no PostgreSQL/provider calls.

## Findings

### E-N01 — current authority registry blocks retained recovery (HIGH)

Trigger: save a legitimate signed review, retain its exact command and signed clear, then make the current registry loader unavailable. `kg_sop_reviews.sop_reviews_submit` invokes `policies.configured` before `service.record`, although the domain writer verifies/returns a retained duplicate before requiring fresh authority and permits retained-authority cancellation. Both signed HTTP commands return 503 instead of completing. GET also loads the current registry before historical preview, hiding recovery controls. Empty `[]` authority removal works and is a different case.

Own persistent reproduction: `tests/test_reviewer_sop_authority_recovery.py` in the R2 review archive; `python -X utf8 -m pytest tests/test_reviewer_sop_authority_recovery.py -q --junitxml=runs/reviewer-authority-r2.xml`: **1 FAIL /39.54s**, actual `(503,503)` versus required `(303,303)`. Saved response HTML is under `runs/reviewer-http/authority-registry-{retry,clear}.html`.

Correction must preserve fail-closed fresh writes while allowing exact retained retry/clear without fabricating a current authority. Also account for `operator_sop_reviews.current` reloading configuration when passed no authority; changing only the POST loader does not restore retained GET presentation.

### E-N02 — blank second printed page (MEDIUM)

Actual saved task, mobile RU/dark and desktop EN/light/no-JS: each PDF has two pages, with no text or content on page two. Print colours are white/black, but the inherited page-height constraints are not reset. This is the same type of print-height failure previously corrected in the actual-dates page. Reset print height/min-height on the inherited wrappers and verify the final shell.

Own artifacts: `runs/e630e-native-review-r2/runs/reviewer-browser/{ru-dark,en-light}.pdf`, corresponding `*-print-1.png`/`*-print-2.png`, and `checks.json`. Both first/blank pages and saved screens were personally inspected. `reviewer-native-r2.xml`: **1 PASS /1 FAIL /182.51s**; only browser final failure entries are the two unexpected PDF page counts. Screen flow, contrast, overflow, focus, correct time, no-JS withdrawal and controlled reader error assertions completed before that final assertion.

### E-N03 — no visible own subject identity (MEDIUM)

The controller signs and enforces case/person/application IDs, but neither screen nor printed review displays that identity in the main content. A printed selected schedule/task cannot be associated with its own case and applicant from the page itself. Add a compact localized case/person/application identity row; this is a presentation defect, not evidence of a cross-subject authorization bypass.

### E-N04 — authority/privacy uncertainty is labelled a stage mismatch (LOW)

Removing the authority while retaining the same V01 process displays “This review is currently unavailable for this stage.” The same generic stage wording covers other unavailable causes. `authority-withdrawn.png` demonstrates the unchanged-stage case. Use a neutral unavailable/current-evidence explanation or accurately map the reason; keep historical selected time visibly distinct from current applicability. Clear/reconcile confirmation should describe the selected action rather than confirming a time that the form does not select.

## Completed independent evidence

`tests/test_reviewer_sop_http.py` and `tests/test_reviewer_sop_browser.py` are reviewer-authored in the env-free archive, using actual application routes/domain writes and the repository's synthetic source fixtures.

- **PASS:** signed CSRF/context, non-ASCII/malformed tokens, changed request/evidence/revision, duplicate form/query fields, body >8192, invalid date/time/confirmation, foreign subject/application/case, other admin session and unauthorized manager. Mutations rejected without extra review/task records.
- **PASS:** real changed evidence produces 409; fresh date-only review can save/reconcile; real own consent withdrawal hides fresh review and retains cancellation, which cancels the actual task.
- **PASS:** case-reader outage GET/POST is controlled no-store 503; POST preserves the exact signed original. Actual committed write followed by lost acknowledgement with a healthy reader returns 503 plus the original retry, suppressing new action forms. Repeated original command after authority removal returns the original record exactly once.
- **PASS:** actual RU mobile dark and EN desktop light/no-JS, local server/authentication, readable Arial 16px body/buttons, text/control contrast >=4.5, no horizontal overflow, keyboard focus, same Bishkek date/time on save/read/task, true no-JS retained withdrawal, no fake delivery claim.
- First HTTP artifact `reviewer-http-r2.xml`: 1 PASS/1 FAIL58.32s; the failed case was a reviewer fixture duplicate application request key before the tested edge, corrected by giving the other application a distinct key. This is not an application defect. The corrected full security case passes in `reviewer-native-r2.xml`.

## Scope limitations

No known native blocker remains in the reviewed scope. No browser approval is inferred from a builder test or from earlier D page evidence. Domain/source evidence and PostgreSQL/migration/capacity recovery are outside this scoped native verdict. RU used JavaScript enabled; EN executed the actual flow with JavaScript disabled. Source clause excerpts remain in their original PDF language; this review does not claim to translate the source document or the shared CRM shell.

## Corrective evidence, R6 / R9 / R10

- R6 own `tests/test_reviewer_sop_http.py`: **2 PASS /140.24s**, `runs/e630e-native-review-r6/runs/reviewer-http-r6.xml`. No technical proof/reference field is accepted from the operator; extra posted fields return 422. Original security/scope/overflow/privacy/date-only and actual lost-acknowledgement checks pass. The stale-evidence control now writes a new revision of the identical own profile: the earlier `conversation_started` trigger deliberately terminates LEAD_RESPONSE under the independently corrected domain wait guard, so it no longer supplies the next eligible review form. The rejection remains a genuine old-evidence 409, followed by a fresh eligible save.
- R9 own `python -X utf8 -m pytest tests/test_reviewer_sop_authority_recovery.py tests/test_reviewer_sop_http.py -q --junitxml=runs/reviewer-corrective-r9.xml`: **3 PASS /270.07s**. Both actual malformed registry `[{}]` and an unavailable loader preserve readable private historical GET/clear while suppressing fresh review; a previously signed fresh command returns 503 with its exact retry and no write. Original saved duplicate returns 303 unchanged. Retained clear cancels the actual task and is repeatable; even the original earlier save remains retryable after clear. All preceding HTTP/security/privacy/lost-acknowledgement controls also pass on R9.
- R9 source correction passes `None` to the domain writer on unavailable current authority; the domain distinguishes retained retries/clear from fresh commands. `current` catches current registry errors and reports unknown without changing immutable history. It does not grant a substitute authority. R9 also supplies human-readable unavailable reasons and action-specific confirmations.
- R10 contains exactly the same application `.py`/`.html` files as R9 except `app/admin/templates/kg_sop_reviews.html`: its literal `?` separators were corrected to `&middot;`. All 30 R10 manifest overlays were verified against the own archive; all 28 R9 overlays likewise verified. Browser testing uses R10.
- Final native controller LF SHA-256: `f5ebcb8cb6ac4460f922641b82f345e1d66ad37024819da3247642bfcd18e275`; R10 template LF: `5809f9c6a5b7f6e427afbb13a232d84cc9cbd4b7b84269481d36d221d557018f`. Actual preserved shell base LF: `65b70c196c2736f2f89b5a8994dc02da71f07373b06ba3c3e36407e207a1b727`, boards LF: `9ce80ed0684efa123641dbb71ea171439b48da259572b30b0b24a0652a26b377`.

Machine-readable identities, individual test outcomes and artifact hashes are generated by `runs/e630e-native-evidence.py` into `runs/e630e-native-evidence.json`. These overlapping runs are kept separate, not represented as one new full suite.

## Final browser correction and closure

Command in `runs/e630e-native-review-r10`: `python -X utf8 -m pytest tests/test_reviewer_sop_browser.py -q --junitxml=runs/reviewer-browser-r10.xml` — **1 PASS /85.04s**. It runs a real authenticated local application, blocks non-loopback requests and submits native forms; it does not substitute HTTP mocks for the business writes.

- **E-N01 CLOSED:** R9 original/corrective retained recovery, malformed/unavailable registry, fresh-denial and actual same-task cancellation controls pass as documented above.
- **E-N02 CLOSED:** both R10 `ru-dark.pdf` and `en-light.pdf` have exactly one nonblank white page with readable black text, selected date/time, own IDs and actual task status. No hidden action controls or shared navigation are printed.
- **E-N03 CLOSED:** case/applicant/root application IDs are readable in both screen languages and both print pages; active stage application is shown when current evidence exists. The real route/session/source enforcement remains independently tested.
- **E-N04 CLOSED:** removed authority is described as an access/configuration/currentness issue, historical selected time remains separate from current applicability, and clear/reconcile have their own confirmation labels. The subsequent real no-JS clear cancels the same task. Reader outage displays a private no-store 503 without new POST controls.
- **PASS:** final actual shell dark390px/light1365px, no horizontal overflow, visible focus, 16px Arial body/buttons and all sampled visible text/control contrasts >=4.5. No proof/reference input is rendered; the server-derived value is explicitly evidence of operator selection rather than a legal/document approval.

Personally viewed final artifacts under `runs/e630e-native-review-r10/runs/reviewer-browser/`: `ru-dark-saved.png`, `en-light-saved.png`, `ru-dark-print-1.png`, `en-light-print-1.png`, `authority-withdrawn.png`, `reader-unavailable.png`. `checks.json` contains no errors. Original R2 PDF/HTTP failures are retained unchanged.

R10 evidence manifest preserved as `runs/e630e-native-evidence-r10.json`, raw SHA-256 **`36ff0ebde3b43be4530026eb8cd798222a899dd2bf9a86b87c31a6f79b06a201`**. At that checkpoint no reviewer processes or servers remained active. Only own archives/probes and this report were written; implementation was not edited.

## R14 native expiry follow-up

Parent/auditor found a separate domain currentness edge: expiry of the nested process policy previously propagated as an availability failure. R13/R14 narrowly translate `process_policy_outdated` to an unknown current review, retaining integrity errors. The native R14 delta maps that exact reason to the existing localized authority-expired text.

Own freeze `runs/e630e-native-review-r14` verifies all41 manifest overlays. Controller LF SHA-256 **`dc29695a809a810445c9ead7ebd78a4f2f8e069759bf092bb50fc693edb75b6d`**. Template remains **`5809f9c6a5b7f6e427afbb13a232d84cc9cbd4b7b84269481d36d221d557018f`**, identical to the personally inspected R10. Independent AST comparison removes only `operator_sop_process_authority_expired → authority_changed` from the new reason map and matches the entire R10 controller exactly. No repeated full browser suite is needed for that text-selection change.

Own `tests/test_reviewer_sop_native_expiry.py` sets an initially valid process policy with today's review boundary, performs the real native save/task creation, and advances the two current-observation clocks by two days while the outer E authority remains valid. Both RU/EN GETs are private200, show localized expired authority/unknown currentness and historical time, suppress new review and retain clear. A previously signed fresh command refuses422; original command retries303; signed clear cancels the same task and repeated save/clear remain idempotent.

Command: `python -X utf8 -m pytest tests/test_reviewer_sop_native_expiry.py -q --junitxml=runs/reviewer-expiry-r14-correct-harness.xml` — **1 PASS /86.93s**. The first execution passed every behavioral assertion but had a reviewer count-oracle mistake: it expected one total CRM task while the shared fixture already contained an unrelated ordinary task. Original `reviewer-expiry-r14.xml` (**1 FAIL /106.52s**) and `runs/reviewer-expiry-original-harness.py` remain preserved. Corrected test measures the baseline and asserts exactly two new receipts/one new task. No runtime change was made for that fixture correction.

Updated full native evidence manifest `runs/e630e-native-evidence.json`, SHA-256 **`20fec42deb063e24ce7ef612ef72be84abc03e741ab45c9ae1a08b258a6f78d6`**. Promotable narrow follow-up is the own R14 test above. No own test/server/PG process remains active. Separate source/J01 matrix and final E domain/audit acceptance remain outside this native approval.
