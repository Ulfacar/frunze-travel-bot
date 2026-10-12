# E6-30B — independent native UI review

**Scoped APPROVE — reviewed local UI on frozen R15, exact UI identities mapped to R16.** Reviewer: `publication_review`, independent of the builder. This covers the specialist page, its native confirmation/retry forms, router registration and application link. It does not certify the specialist domain, source/legal authority, PostgreSQL concurrency, migration/recovery, all fourteen SOPs, J01/J02 completion or production release.

The task, actual route/template, underlying form and quote contracts were read before builder test conclusions. Original findings were reported immediately and reproduced in an environment-free archive. No root implementation/tests/configuration, `.env`, production data or provider was used or changed. All policies, people, evidence and approvals in tests are synthetic; the supplied original PDF is only source-shape input.

## Exact target

Base commit: `ad9e0bd4d7403f05cb8e7178a0d5f738a0cd4356`. R15 is an uncommitted snapshot with **32/32 verified LF-normalized overlays**, copied independently through `git archive` plus the declared overlays. Raw R15 manifest SHA-256: `79d47e12bb5ad8a2fbd19e603602df40e2b4d4a42d962de591f3eb36e849ebca`.

| Scoped file | R15 LF SHA-256 |
|---|---|
| `app/admin/kg_specialist.py` | `6ff11f6d0d74e4cff0dbcbd965a865d145aac905dd73bca3be7cd015e3c68cf6` |
| `app/admin/templates/kg_specialist.html` | `fe56c5b2672445444162e25cd4470ee26fea8a7464bd6a851be5cc0744f8d2ba` |
| `app/admin/router.py` | `b1451cf1f6f3a1b43266dc98025ce484d0573120935a957dc240f8cdd407a1ac` |
| `app/admin/templates/kg_applications.html` | `aeee85d144977f13c09c0e807ec40dc3ef66eb3a2903d2960cbf3368f42ce280` |

Machine-readable source/artifact mapping: `runs/e630b-native-review-r15/runs/review-identities.json`, raw SHA-256 `28b0fcb2669c5961341b2c4b593ff38c22a479369f96529dfdb82af253d6ad85`. Original PDF SHA-256: `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.

Subsequent R16 uses the same base,36 overlays and raw manifest SHA-256 `7d7d0af3a339328f03c7a98f0fd1ead0a3e2cc75204596c5591628d4fc700508`. All four scoped files above were independently compared against both R15 bytes and the R16 manifest: **4/4 identical**. This maps the UI approval only; it does not certify R16's separate domain clock-guard correction.

## Findings and correction evidence

All five findings below are **MEDIUM, corrected**. They blocked the requested native acceptance; no financial mutation or unauthorized external action was observed.

1. **Unreadable Russian material confirmation.** R9 template had literal `????` for the review date, business/work/host facts and yes/no answers. The connected Russian prepare page reproduced this. R15 uses readable labels; the confirmation also identifies each evidence fact and selected reason, with the document fingerprint in native details. Corrective HTTP evidence verifies readable facts and exact retained findings; preparing a confirmation leaves the journal at revision zero.
2. **Valid incomplete quote failed to render.** R9 called `preview.totals_by_currency.items()` although the calculator deliberately returns `None` when a component price is unknown. A synthetically approved recipe with unknown bank fee passed the domain preview but native POST returned503 and an incorrect uncertain-save message. R15 template line43 renders complete totals only when complete; otherwise it explicitly says the complete price is unknown and lists known/unknown components. The same connected scenario now prepares and saves the incomplete internal estimate, without changing it into a complete price.
3. **Case-registry outage escaped native recovery.** R9 GET and POST awaited `_case` outside their error boundary. Both produced raw HTTP500; POST lost its signed retry form. R15 route lines128/177/188 render a controlled no-store503 without trying a further unverified history read. POST parses the bounded signed form before case lookup. Corrective controls verify exact original POST values, no fresh action form, no journal write, forged-envelope403 before any case lookup, and preserved case403/404 responses.
4. **Healthy reread masked commit uncertainty as invalid input.** `EntryStorageUnavailable` inherits `DomainError(ValueError)`. R9 and R13 therefore caught it in the validation422 branch. Earlier builder testing also made the reread unavailable, which hid the wrong branch by changing the final response to503. The independent control exposed422 with a healthy reader. R15 line219 catches storage unavailability before `ValueError`. A strengthened connected probe actually commits, then loses the acknowledgement while reads stay healthy: the response is503 with exact original confirmation, and its retry returns the existing receipt with one journal revision.
5. **The UI rejected a valid signed preview on unchanged save.** The former24000-character payload and65536-byte body limits were below accepted recipe/result bounds. An accepted37833-byte recipe produced a28779-character signed payload; the actual signer/parser returned422 even though the60364-byte body was below the old body limit. R15 lines32/60/86 tie the UTF-8 payload bound to the bounded journal event, check it before offering confirmation and retain a bounded percent-encoded body/stream limit. A real32-line recipe now produces a29852-character /39932-byte payload and86947-byte encoded form, then saves and retries successfully with exact operation equality and no duplicate quote. Oversized UTF-8 pre-offer payload and streamed body overflow still fail safely.

## Independent verification

Environment: local Windows, Python3.12.10, pytest9.0.3, FastAPI0.135.1, Starlette1.3.1, SQLAlchemy2.0.25, aiosqlite0.20.0. No PostgreSQL run was needed or performed for this scoped UI review. The only warning was the installed Starlette/httpx deprecation.

Commands were run from each named environment-free archive:

| Revision / command | Evidence |
|---|---|
| R9: `python -m pytest tests/test_reviewer_specialist_native.py -q --tb=short --junitxml=runs/reviewer-native-r9.xml` | **5 FAIL /231.16s**, retained original RU, incomplete-preview, GET/POST outage and error-class failures. |
| R14: same command with `reviewer-native-r14.xml` | **5 PASS /278.10s**. The corrective controls additionally cover removed current admin, cross-case/applicant/application/language403, 409/422/503 exact retry, and actual committed lost acknowledgement with healthy reads. |
| R14: `python -m runs.form_bound_probe` | Original bound failure retained: **422**, accepted recipe37833 bytes, signed payload28779 characters, body60364 bytes. The script tests actual envelope signing/parsing; it does not claim a connected saved quote. |
| R15: `python -m pytest tests/test_reviewer_specialist_bounds.py -q --tb=short --junitxml=runs/reviewer-native-r15-bounds.xml` | **2 PASS /89.32s**: connected32-line preview/save/exact duplicate plus stream/pre-offer bounds. Sizes recorded in `runs/reviewer-native-bounds.json`. |

Own artifacts reside under `runs/e630b-native-review-r9`, `runs/e630b-native-review-r14` and `runs/e630b-native-review-r15`. R14→R15 runtime UI diff is only the bounded payload/body compatibility correction; the template is identical. This maps the five R14 corrective results to R15 without claiming they were rerun there.

Additional builder evidence inspected after the source assessment: R11 browser XML `runs/e6-30b-r11/runs/specialist-browser.xml` records **1 PASS /170.03s**, driving actual no-JavaScript review→confirmation→quote→save→reload in RU mobile390 dark and EN desktop1365 light. I independently viewed all six `review/quote/saved` screenshots. Text and button labels are readable, forms fit the viewports, fields are labelled and actions remain explicit. The specialist CSS and base template are byte-equivalent after LF normalization between that snapshot and R15. This browser evidence covers the unchanged layout and positive path, not the subsequently corrected error branches or original broken Russian record-confirmation labels; those corrections have the independent HTTP evidence above. No claim is made here about an unfinished later builder browser run.

## Acceptance and limits

PASS for this UI: GET is read-only with respect to business journals; preparation and explicit save are separate; HMAC/CSRF bind actor, all three target identifiers, language, revision, operation and request key; current configured identity and the service authority path enforce access. Bounded strict form parsing rejects duplicate/extra fields and altered signatures. Correctable conflict, invalid operation and uncertain result remain distinct; original signed values survive retries; no fresh operation form appears during an uncertain retry. The same case/person/application is visible, original receipts remain readable and the linked estimate stays an internal estimate.

No native action sends an offer, records client acceptance/signature/payment, or grants entry/stay/work permission. Source and specialist delegation remain independently required and empty by default. Domain, interruption, financial compatibility, actual PostgreSQL and migration conclusions belong to their separate reviewers/auditor. **No open material finding remains in this exact native UI scope.**
