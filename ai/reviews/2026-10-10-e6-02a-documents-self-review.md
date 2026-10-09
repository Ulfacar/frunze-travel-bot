# SELF_REVIEW — E6-02A document matrix

- STANDARD / solo, local-change target. Codex, same author/context, separate
  review pass. No independent CRITICAL approval.
- Task `ai/tasks/2026-10-10-e6-02a-document-checklists.md`; base `1747d0c`.
- Reviewed source §§5.1–5.5/11.4, catalog builder, evaluator, route/template,
  native tests, navigation, Dockerfile, report builder and delivery scope.

## Findings and decisions

1. Matrix source has23 rows, not24: combined numbers1–3 and5–6; no12. Initial
   builder count assertion caught this before creating a catalog; corrected to
   the actual23. All207 cells preserved and matched to the source rows.
2. Mixed address/hotel cells cannot make a recommended booking mandatory.
   Split positive symbols into separate items. A dash with a nested dash/Face ID
   explanation is kept intact, not split or treated as legal exemption.
3. The matrix alone omits details (including mandatory TS application alternatives
   in §5.3 and medical additions on p38). Keep all supplementary source text and
   explicitly refuse package acceptance/submission even when required matrix
   rows pass. Nine matrix types are not all possible visa types.
4. Unknown applicability must not disappear; receipt must not imply content
   verification. Literal typed states/conditions only; changed/unknown version
   makes checked items require review again. This does not assert real file
   hashes, consent, passport continuity or actual acceptance.
5. Unverified EP-photo source marker remains unresolved despite a checked answer.
   Draft source metadata stays pinned; source publication is always false.
6. Existing admin/OFF/workday checks precede source access; no new permissions or
   domain access. Dedicated CSRF and bounded whitelist forms; stale409, invalid422,
   unavailable503; no malformed echo or old result after errors. No free-text
   personal fields/files; no answers stored in DB/session or sent outside.
7. Product change deliberately resets the scenario. Clarified successful summary
   as REQUIRED matrix rows checked; recommended rows may still be absent. No
   complete-package implication in screen or print.
8. Initial print was3 pages with two cards on the last page. Reduced print-only
   spacing/source font, kept cards intact; final browser check must verify it.
   Screenshot now scrolls result to its heading instead of centering a long block.
9. Added explicit Docker catalog COPY; no image-build claim. Full PDF estimate
   about30%/70% is a rounded engineering judgment, not page/test coverage or launch
   readiness. Remaining execution, documents/privacy, dialog, publication and
   acceptance are explicit in coverage/report.

## Evidence and limits

Initial pure checks23 PASS/0.43s. Isolated domain/HTTP/browser44 PASS/3 deprecation
warnings/46.55s, before the final summary/print/screenshot refinements. Original
PDF SHA256 and physical matrix pages36–37 verified. Catalog repeatability,
mixed cells, stale files, source markers, type/field attacks, gates/zero SQL and
mobile390/desktop1365 no-JS covered. Final exact-copy regression/print and report
evidence follow in the handoff from STATE.

No unresolved functional defect identified in this local matrix slice. Final
completion awaits those final checks. Prior CRITICAL independent review/audit/PG,
business/privacy decisions and actual per-applicant document workflows remain
UNKNOWN or incomplete. No full-suite/build/traps or production acceptance claimed.

## Final local verdict

**SELF_REVIEW PASS for STANDARD local slice** at code
`1d3372ed7116d99a13b1ef989c9d0c31c5d248a5`: final exact-copy regression121 PASS /
3 deprecation warnings /182.03s, no failures/skips. Cold imports all exit0.
Revised print2 pages and mobile result inspected;5-page progress report inspected
with26/26 headings verified. Code snapshot20/20 matches Git/workspace/archive.
Prior CRITICAL gates and whole-PDF remaining work are unchanged.
