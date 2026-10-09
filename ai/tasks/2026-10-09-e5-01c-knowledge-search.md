# TASK — E5-01C: поиск исходных фрагментов PDF для проверки

- Base `13835bb`, same working branch as E5-04C; STANDARD / solo, local target.
- User requests all engineering work against original PDF and continuous cross-check.
- Builder Codex, separate SELF_REVIEW permitted for STANDARD. No external provider.

## Acceptance / scope

1. Deterministic bounded local search over the existing 74-fragment corpus, blocks
   1–2, 5–13, 15–17, exactly as the PDF IT instruction prescribes.
2. Verify corpus against source lock and regenerated source artifact; reject altered
   text, metadata, publication flags, duplicate identifiers or missing source.
3. Results retain complete fragment, parent context, tables, source pages/lines,
   verify/practice/decision flags and source hash. All output remains review-only.
4. Pure API + CLI + full-admin CRM screen with existing OFF gate. No model/provider,
   embeddings, client messages, automatic legal answer, DB writes or source publication.
5. Empty/no-result/invalid query/source unavailable, direct role denial, escaped text,
   deterministic ties, caps and immutable returned data covered by appropriate tests.

This fulfils local retrieval for human review, not the publication gate or approved
bot answering. Existing CRITICAL intake/storage/permission gates are unchanged.
Record exact revision/checks in handoff and project PDF coverage map.

## Result

Local target DONE, code `e23e39eb78a3586557c712219118344e2cfb9b46`. Separate SELF_REVIEW
for STANDARD scope complete; no independent approval claimed. Search43, final HTTP54,
shared-panel/browser43 PASS. Final full Git copy: 3447 pass / 1 old tour-date fail /
13 skip / 659.79s. Handoff `ai/handoffs/2026-10-09-2201-e5-intake-search.md` records
source integrity, limits, Docker UNKNOWN and critical gates of the surrounding pilot.
