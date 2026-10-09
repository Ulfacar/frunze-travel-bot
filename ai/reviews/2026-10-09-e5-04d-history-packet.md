# REVIEW PACKET — E5-04D actual history in CRM

- CRITICAL / solo, local change + review packet; **PARTIALLY_READY**.
- Base `54a6e9d94c8fde5a8b602b49646702dc91633f83`, branch `fix/tours-search-quality`.
- Builder/reviewer: Codex, same author/context, **SELF_REVIEW** only.
- Independent review and separate final audit: **UNKNOWN**, not performed.
- First assessment before builder conclusions: NO. No independent approval claimed.
- Exact code revision and final evidence: follow-up handoff linked from `ai/STATE.md`.

Read task `ai/tasks/2026-10-09-e5-04d-history-crm.md`, original PDF §3.3 D1/D2/D5,
§18.4/18.5 and contract `docs/e5-04d-history-crm.md` before the findings below.
Inspect new adapter/routes/templates and integration diff against base. No real data,
production, credentials, new service or messages are needed for this review.

## Challenge criteria

1. Named full-admin and default-OFF/workday/write gates run before domain access.
   A guessed history ID from another contact cannot be read, edited or attached.
2. CSRF/HMAC bind actor/session/case/contact/base/as-of/key. Cross-form/session/case,
   metadata forgery, duplicate/unknown fields and oversized request are denied.
3. GET and add-row do not write history. Save calls existing owned transaction service;
   CAS/idempotent retry/lost commit acknowledgement retain recovery semantics.
4. Old versions and old qualification reports/cards are immutable and contact-scoped.
   Explicitly attaching another version creates a new qualification only after save.
5. Blank, no trips, incomplete, unasked exit and actual ongoing stay are distinct.
   Future/reversed dates, two open stays and client-statement confirmation fail.
   Overlaps are retained with a warning, including same-day boundary records.
6. Omitted saved fields/rows cannot silently erase trips. Explicit row removal affects
   only a new full snapshot. Opaque passport refs never enter the browser/form contract;
   preserve them server-side, clear on explicit change or changed country.
7. Error echo retains signed nonce and facts; no result is invented after unavailable
   storage. Corrupt persisted source fails closed. Native no-JS/mobile flow works.
8. Print/card discloses facts, completeness and provenance from the pinned version,
   not latest history. No legal allowance or full D1/D2/D5 coverage is claimed.
9. Docker COPY includes the existing ISO3 catalog. It validates country codes only,
   not visa eligibility. No migrations or permission/publication settings changed.

## Findings and corrections — SELF_REVIEW

| Finding | Resolution / evidence |
|---|---|
| Browser helper used asyncio.run inside Playwright's active loop | Removed in-loop DB helper; final DB assertions run after browser closes. HTTP test independently checks add-row causes no writes. Initial browser run 2 failures; corrected combined browser run 3 passes |
| Invalid qualification hid explicitly selected history while retaining it in signed metadata | Error context now shows signed history ID; HTTP scenario verifies error banner, same nonce, unchanged old result and eventual attached history |
| Empty unknown exit could be confused with stored null (known ongoing) | Adapter rejects unknown/unasked exit. Explicit ongoing choice required; documented draft-history limitation |
| History revisions could have replaced older qualification sources | Default keeps pinned source; only explicit history_id selection changes next save. Old-card and older-history browser checks pass |
| Full snapshot UI might truncate large imported history | Adapter renders up to existing 1000-row bound and rejects count below base; roundtrip boundary test |
| Country change could retain a previous passport binding | Clear opaque ref on changed country or explicit checkbox, tested both paths |
| New ISO3 file needed in deployed filesystem | Added fixed public catalog COPY; local source exists and parser tests pass. No Docker build claim |

## Verification / release gates

Initial new HTTP/adapter tests: 46 passed / 54.38s on synthetic SQLite. Corrected
combined browser tests: 3 passed / 45.33s on isolated loopback Chromium (390 JS,
1365 no JS), including existing intake/search flow. Four-page synthetic history
card PDF visually inspected page by page, plus mobile history screenshot.
Final related regression and committed-copy results are recorded separately in
handoff; do not promote these initial worktree numbers to final-commit evidence.

Independent reviewer/final audit and PG16 runtime UNKNOWN. Docker engine absent in
preceding checkpoint; no image build attempted here. Previous full-suite tour-date
failure and production-traps baseline remain unrelated; no green release assertion.
Manager scope question remains unanswered. No production release, schema operation,
real-data imports, access expansion or outgoing messages performed.
