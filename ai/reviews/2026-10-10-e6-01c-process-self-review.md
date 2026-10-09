# SELF_REVIEW — E6-01C draft process preview

- STANDARD / solo; local-change target. Reviewer: Codex, same author/context,
  separate review pass, not independent CRITICAL approval.
- Base `735eaf3`; task `ai/tasks/2026-10-10-e6-01c-process-preview.md`.
- Read PDF §§14.2–14.6/p63–66 and derived rows, builder, catalog, evaluator,
  HTTP forms/template, tests, router registration, Docker packaging and coverage.
- Exact final code revision and verification: handoff linked from `ai/STATE.md`.

## Findings and resolutions

1. Preserve all 87 codes, including exceptions and parallel flags. 71 edge variants
   include two different branches for U05→U06; these are not 71 distinct pairs.
   Source-stated order is labelled separately from proposed links. All required
   facts remain draft formalizations, including edges based on source order.
2. Unknown eligibility must not mean ineligible. Replaced the early draft's
   false boolean guard with explicit `eligibility=ineligible`; tests distinguish
   no value, pending specialist review and confirmed impossibility.
3. A registration cannot issue an L visa. U06→U07 requires exit-visa route,
   approved decision and issued visa; registration branches remain separate
   procedures. Source U codes are retained; L denotes the document type.
4. Refusal must not be reset to pending. X01 has no back edge and explains a new
   linked application. Corrections retain the same attempt. Work process steps
   involving resident cards and registration describe separate applications;
   employer-wide stages are not attached to an individual application.
5. Positive conditions never authorize execution: every result is hypothetical,
   unpublished and leaves the current stage unchanged. Source flags, terminals
   and undescribed exception exits cannot pass through an empty condition set.
6. Protect version integrity and deterministic inputs. Frozen pinned bytes,
   detached decoded objects, known typed facts, no truthy strings/integers,
   strict process membership, stale-form rejection, bounded file/form sizes.
   Added CRLF-only normalization for Windows Git checkout and explicit test.
7. Existing full-admin/default-OFF/workday gates execute before catalog access.
   Dedicated session CSRF, no arbitrary fields or personal-data form, no external
   request, DB/session fact persistence or application mutation. Read-only preview
   works with the existing write flag off; tests capture zero domain SQL.
8. Dockerfile previously copied only specific knowledge assets. Added explicit
   copy of the catalog. This review is not a successful image-build claim.
9. Initial print left the scenario hash alone on page two. Reduced print heading
   and paragraph spacing while preserving full conditions/source/hash. Final
   committed-copy browser run and visual inspection must verify that adjustment.

## Evidence before final checkpoint

- Pure source/evaluator checks: 25 PASS.
- Isolated domain + new HTTP + existing knowledge HTTP: 57 PASS, 1 warning,
  44.88s. Browser mobile 390 / desktop 1365 without JS: 2 PASS, 3 warnings,
  29.95s before the final print-spacing change.
- Compilation and protocol structure PASS; whitespace check PASS.
- Final exact-copy regression, printed layout and snapshot hashes are recorded
  in the handoff; this document does not substitute for those results.

## Boundaries and verdict

No unresolved code defect identified in this local preview during SELF_REVIEW.
Final local completion still requires the final checks above. This is not a
published legal workflow or approval for any previous CRITICAL storage change.
DEC-02/06/07/08/11/12 and independent review/audit/PG16 gates remain outstanding.
No production release, migration, real-data input, changed permission or payment
policy, client messages, full-suite/traps/build rerun claimed. Whole PDF incomplete.
