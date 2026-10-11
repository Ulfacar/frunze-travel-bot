# E6-17 — typed profile integrity and scoped E6-04 review closure

DONE for reviewed local synthetic correction, CRITICAL / solo. Code
`214d88f2a157139be121d070ddd8217358d58d79` pushed only to the authorized working
branch. No migration, publication, deployment or real personal-data processing.

Four semantic comparisons now use canonical JSON: previous revision pin, source
context, runtime fingerprint and explicit result replay. Python equality could
otherwise equate bool/int/integral-float values after a synthetic SQL change and
full checksum recomputation. The native browser fixture was updated to the
existing applicant-specific qualification link; substantive assertions remain.

Frozen `runs/e6-17-review-r1`, basefca93ad, five-file manifest LF SHA256
`dcf20adaf989dadf3143a4720e9e31198c7328247198d4968490475da5a9b5c2`.
All five root/frozen/committed identities PASS. Runtime module SHA256
`760d5c9885ba6f4edb2ca90790bfc19e95125945417701b3f631bcb9121c630f`.

Builder actual command (guarded private loopback PG fixture):

```text
python -m pytest tests/test_applicant_profiles.py tests/test_admin_kg_applicant_profiles.py tests/browser_kg_applicant_profiles.py tests/test_applicant_profile_integrity_postgres.py -q --tb=short --basetemp=runs/profile-integrity-r1-tmp --junitxml=runs/profile-integrity-r1.xml
52 PASS /3 deprecation warnings /242.41s; no failures or skips.
```

Hash/counters: `ai/reviews/2026-10-11-e6-17-runtime-evidence.json`.
Independent review `ai/reviews/2026-10-11-e6-04-independent-review.md` APPROVE:
48 SQLite/domain/migration/native/browser/own checks +21 actualPG checks PASS.
Separate final audit `ai/reviews/2026-10-11-e6-17-final-audit.md` GO:
17 own SQLite/browser +24 actualPG PASS. Counts overlap. Original negative probes
were retained unchanged. Both390/mobile and1365/no-JS screenshots inspected by
the auditor. SQL constraints, actual0019↔0020 migration and populated downgrade
refusal were exercised on PostgreSQL.

The auditor used the actual previous module to create receipts, then read and
exactly retried them with the new module on both databases. Explicit old-runtime
replay refuses; a new receipt replays; JSON key order remains irrelevant.
Ordinary historical reads intentionally do not recalculate result semantics after
a runtime upgrade. This proves bounded typed consistency, not authenticity
against complete database forgery or a claim of an HTTP authorization bypass.

The E6-04 individual numbered-profile review/audit gap is closed and B02 review
may be marked PASS; no new technical points, whole-project J03 approval or legal
qualification claim follows. E6-18 changes the qualification runtime dependency
separately and requires its own combined compatibility check. Final production,
owner/source/privacy decisions and all remaining older critical reviews stay open.
