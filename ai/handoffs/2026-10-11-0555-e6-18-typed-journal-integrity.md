# E6-18 — typed journal consistency

DONE for the independently reviewed local correction, CRITICAL / solo. Code
`d1c9a38737e600d6508a6e2e1f38c0ca3a9932be`, saved to the authorized working branch.
No migration, historical repair, publication or deployment.

Canonical JSON comparisons close sixteen demonstrated bool/int/float aliases
across qualification, documents, issued facts, procedures, interviews, portal and
deadline journals. Three writer-accepted integral-float deadline foreign keys
are converted only at the relational INTEGER boundary before hashing; original
JSON commands, selections and request hashes preserve their exact number type.
This also fixes the reproduced accepted-write/unreadable-reload defect. Invalid
old rows are not automatically repaired. Historical reads do not recompute every
old result and checksums do not authenticate fully forged database content.

Frozen `runs/e6-18-review-r2`, base fca93ad, eleven-file manifest LF SHA256
`044ee55993e48763563e37ac3808fc2b6cf58ebfbac8cc6531c8488bacb328d0`.
All eleven root/archive/commit identities PASS. The merged d1c9a38 execution
snapshot additionally matches all689 runtime/test/asset files after LF normalization.

Builder command (guarded private loopback PostgreSQL fixture):

```text
python -m pytest tests/test_entry_typed_integrity.py tests/test_entry_typed_integrity_postgres.py -q --tb=short --basetemp=runs/typed-final-r2-tmp --junitxml=runs/typed-final-r2.xml
84 PASS /1 existing deprecation warning /309.01s; zero skips/failures/errors.
```

This is42 SQLite/schema and42 actual PostgreSQL checks. Before correction,
original20 alias cases failed with DID NOT RAISE; independent extra12 alias
failures and all three accepted-float persistence failures were reproduced on
base. Final controls include schema refusal of bool/fraction identifiers,
preservation of valid integral-float receipts, current overlays and exact retry.
JUnit hashes/counters: `ai/reviews/2026-10-11-e6-18-runtime-evidence.json`.

Independent review `ai/reviews/2026-10-11-e6-18-independent-review.md`:
APPROVE,82 PASS (58 SQLite/compatibility,20 actualPG,4 native HTTP).
Separate audit `ai/reviews/2026-10-11-e6-18-final-audit.md`:
GO,60 PASS (14 original negatives,13 compatibility,33 actualPG). Counts overlap.
Both used actual separate old-code writers and new readers for qualification,
profile and deadline receipts. Old exact retries remain valid; explicit old
runtime replay refuses. New quarantine and deadline-current-state overlays pass.

Broader E6-18 regression was deliberately interrupted, without observed failures,
to reserve resources for the final merged whole suite; no PASS claim. Initial merged full
run `runs/overnight-final-r1` was deliberately interrupted after E6-19 uncovered
independent deadline-task defects; that partial run is not PASS. A new merged
full run must include the separately reviewed E6-19 correction. E6-14's prior
4549 PASS/119 SKIP full result remains historical, not later-code certification.

No new technical points or whole-project J03 approval. Fixed score90/100 remains.
Outstanding business/source approvals, all remaining critical reviews, connected
end-to-end acceptance and production recovery remain separate gates.
