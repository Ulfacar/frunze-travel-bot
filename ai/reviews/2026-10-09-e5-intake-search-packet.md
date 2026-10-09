# REVIEW PACKET — E5-04C + E5-01C

- Base `13835bb275bd20881dab8a83c6eec45c94ce114a`, branch `fix/tours-search-quality`.
- Builder/reviewer of this pass: Codex, **SELF_REVIEW**, same author/context.
- Target: current uncommitted snapshot; exact code commit/final evidence follows in handoff.
- E5-04C CRITICAL / solo: PARTIALLY_READY, independent reviewer/final auditor UNKNOWN.
- E5-01C STANDARD / solo: local search target; separate self-review permitted.
- First assessment without builder conclusions: NO; this is a review packet, not independent approval.

Read both tasks, original PDF §3.3/3.4/Б.4/Б.6 and IT instruction before the builder
findings. Inspect actual schema/runtime/adapter/template/route changes and added tests.
Do not start production, send source/customer data to another provider, or contact clients.

## Challenge criteria

1. Existing named full-admin/workday/OFF gates precede source/DB access. Assigned visa
   managers remain denied. Search does not broaden customer access; no DB is required.
2. v1 snapshots remain schema-valid and unchanged; v2 saves are full replacement with
   CAS/retry/CSRF/HMAC. Runtime fingerprint includes intake rules; changed runtime cannot
   pretend to replay old code. Check history, idempotent retry and source corruption.
3. `false`, zero, empty list, absent and unknown remain distinct. Family count includes
   client; relation mandatory; together/later conflict; event order; inviter/location
   pruning affects only the new revision. Browser can clear family after required age.
4. Unicode text is bounded, escaped and never interpreted as instructions. Test URLencoded
   20-row maximum, duplicates, stale/foreign metadata, partial failure and user recovery.
5. No eligibility, price, exact deadline, AI confidence or completed handoff fabricated.
   G-fields partially covered, not full family workflow. Card shows missing operator facts.
6. Retrieval validates pinned lock/source and regenerated corpus, preserves full text,
   labels, tables and provenance; no query-controlled paths. Results always review-only.
   Score is lexical rank, not confidence. Mutating returned objects cannot change index.
7. Existing templates extend the shared shell; native mobile/desktop flows with/without
   JS work; print contains caveats and family facts. Source text remains escaped Markdown.
8. Docker includes only the three selected source files. Actual container build requires
   running Docker engine; local machine currently reports missing Linux-engine pipe.

## Findings and corrections — SELF_REVIEW

| Finding | Correction / evidence |
|---|---|
| Old runtime hashes omitted the new intake module | Added `knowledge/intake.py`; storage regression remains required |
| Windows checkout can use CRLF in corpus | Normalize CRLF for comparison, preserving all source text; explicit loader test |
| Direct index constructor could be mistaken for verified API | Made internal `_ReviewIndex`; public loader verifies full source before construction |
| Search route imported `_gate` from a partially initialized module | Module import + runtime lookup; isolated HTTP tests from `test_admin_kg_entry.py` first pass |
| 32768-byte POST bound was smaller than a maximum valid Unicode/family form | Raised bounded limit to 65536; >32768-byte native payload test passes |
| Search back link pointed to nonexistent `/admin/workday` | Corrected `/admin/work`, actual browser navigation passes |
| Legacy universal-200 page gates did not know new default-OFF route | Added route to their documented flagged set; new positive/negative gate tests separately verify ON, OFF and roles. No old-page assertion removed |
| Search labels showed internal English codes | Human-readable Russian source labels, text still escaped |
| Partial intake could be mistaken for completed PDF | Detailed source map and explicit missing fields; no automatic handoff/decision claims |

Initial focused qualification/HTTP/card suite **183 passed / 129.25s**. New search
**43 passed / 19.12s**. Final extended HTTP **21 passed / 37.26s**, including maximum
Unicode form. After import fix existing form/search HTTP **54 passed / 72.09s**.
After navigation/gate fixes shared-panel + browser **43 passed / 46.74s**.
Full initial run **3448 passed / 4 failed / 8 skipped / 699.70s**: three search integration
failures described above, plus pre-existing tour-date test. Final isolated-copy full
regression must be recorded separately, not inferred from focused fixes.

## Release limits

Independent CRITICAL review/final audit and PG16 runtime UNKNOWN. Owner's permission
decision for assigned managers still unanswered. Publication/legal/calendar/retention
decisions unchanged. Local default-OFF code and working-branch commits are authorized;
production release, schema deployment, real-data tests and messages are not performed.
`prod_traps_check --diff-base HEAD --limit 1`: 1 ERROR / 57 WARN, pre-existing
ANTHROPIC_API_KEY forwarding issue. No secret values printed. Not a green release gate.
