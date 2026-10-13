# E6-18 — typed semantic consistency audit of PDF journals

CRITICAL / solo. Target: reviewed local corrections only where an actual
rehashed bool/int/float substitution reproduces a semantic integrity gap.
No new criterion points, rule approval, migration or production action. Parent
overnight scope and03:00 UTC deadline apply; reserve final15 minutes.

The independent E6-04 review proved that Python dictionary equality accepts
False as0 and integer IDs as equal floats. A focused static search found the
same comparison shape in older PDF journal replay functions. This is evidence
to investigate, not a claim that every match is a vulnerability or that any
HTTP permission bypass occurred.

Candidate scope: qualification_storage context; entry_documents and entry_issued
replayed snapshots; entry_deadlines source/manual/replay snapshots; entry_processes,
entry_interviews and entry_portal replayed state. Read their actual contracts and
surrounding type/schema/hash checks first. Do not alter any candidate without a
meaningful synthetic corruption reproduction showing a missing typed check.

Proposed correction is canonical JSON comparison at the semantic equality
boundary. Preserve actor/scope/policy gates, transitions, clocks, deduplication,
limits, source approvals, old receipt/runtime-version behavior and all immutable
payload formats. No reinterpretation of accepted source numbers or business
facts, no reconstruction/migration of existing records, no silent source upgrade.

Required evidence: independent pre-audit before patches; original failing probes
and corrected equivalents against actual SQLite and relevant isolated PostgreSQL;
ordinary old receipt/read/exact retry, unrelated scope and runtime-version
regressions; exact source manifest; independent review and separate final audit.
If original behavior already rejects a candidate, record that result rather than
performing a speculative refactor. Finish a concrete bounded fix; do not imply
that this narrow audit completes J03 or all historical critical review gates.

Pre-audit GO: ai/reviews/2026-10-11-e6-18-pre-audit.md. Original frozen
runs/e6-18-baseline (base fca93ad) reproduced20 failures across10 boundaries;
all were DID NOT RAISE, not fixture or setup failures. The focused corrected
20-test run passes. Seven modules now use canonical comparisons only at these
confirmed boundaries. Added positive writer-accepted integral-float controls,
old read/retry versus explicit runtime replay behavior, and actual PostgreSQL
wrappers including healthy operation/scope/retry scenarios. Independent review
and separate final audit remain pending; no new points or deployment.

R1 review reproduced six additional typed boundaries inside the same seven
modules: qualification predecessor, interview command, process evidence and
deadline anchor/manual inheritance/explicit replay. Original independent12
failures are retained. Selection-only deadline tampering already rejects and
is deliberately unchanged. R2 includes only these demonstrated corrections.

Positive input controls also exposed a pre-existing deadline writer defect:
integral-float JSON identifiers were accepted and hashed as float in INTEGER
FK columns, then loaded as int with a broken checksum. All three columns fail
on untouched base code (runs/e6-18-baseline-columns,3FAIL18.89s). R2 casts only
the three validated SQL INTEGER fields before hashing; original command,
selection, source and request hash retain their exact JSON types. No old rows
are rewritten, including previously already-invalid float receipts. Both
independent reviewer and auditor pre-assessed this narrow correction as sound.
Controls cover read/retry/replay/manual successor, changed-input key conflicts,
and boolean/fraction rejection. Final frozen checks/review/audit remain pending.
