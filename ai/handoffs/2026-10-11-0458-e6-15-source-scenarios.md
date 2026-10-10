# E6-15 connected source scenarios

**DONE for the bounded local test change; PARTIALLY_READY for whole source-SOP
acceptance.** STANDARD / solo, separate SELF_REVIEW PASS. Code `944bb41` saved
and pushed only to `origin fix/tours-search-quality`; no deployment.

The added real-service tests preserve one applicant through visa V25 after an
existing contract and registration R08 after a separate confirmed decision.
They exercise interview/handoff/owner ACK, scoped WhatsApp suppression, profile,
partial quote, complete package, payment shortfall, portal correction/resubmission,
issued-document review and post-issue entry/exit/followup. Operator attestations
are explicitly synthetic and do not imply external transmission or legal approval.

The exact Appendix B.8 USA45day tourism, India10day business and Uzbekistan
garment-work situations retain their facts, handoff and uncertainty. Draft
qualification leaves unapproved regime/visa/deadline decisions unknown. Source
PDF SHA141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2.

Two actual missing product links remain: intake requires an existing service
case while contract signing creates one; typed interview does not automatically
save an approved qualification. Work/regularization and all14 source procedures
are not newly covered in full here. **J01/J02 stay UNKNOWN; score89/100 unchanged.**

## Evidence

Windows Python3.12, env-free archive of8f41566 plus three manifested files,
FK SQLite and actual isolated PostgreSQL16.15 loopback55971. Private connection
was provided through `FRUNZE_LOCAL_PG_CONNECTION`, never included in the tree.

```text
python -m pytest tests/test_entry_source_scenarios.py tests/test_entry_source_postgres.py -q --tb=short --basetemp=runs/source-final-tmp --junitxml=runs/source-final.xml
10 PASS /0 FAIL /0 SKIP /1 dependency warning /305.77s
```

Execution used the equivalent `pytest.main` wrapper to set the guarded local
connection path and tests import path. Five scenarios ran on each database.
JUnit `runs/e6-15-final/runs/source-final.xml`, SHA256
`1f07e027d75bdf50ef9d0bd4a90ea5da5d8b64fedfe5db6d3690dbc32cdd1f1a`.
The committed final tree `runs/e6-15-final-r2` differs only by removal of a
trailing blank line from one test; both test ASTs are independently identical to
the executed tree. Exact three-file root/archive/commit identity is recorded in
`ai/reviews/2026-10-11-e6-15-snapshot.json`. Staged whitespace check PASS.

Separate assessment: `ai/reviews/2026-10-11-e6-15-self-review.md`. Earlier local
fixture failures are preserved in development artifacts; no failure was skipped
to create the final result. This test-only change requires no new migration or
critical release approval. Previous broader critical review gaps remain open.

Next: finish independently reviewed E6-16 internal draft journal; preserve the
known source acceptance gaps, no-deploy constraint and final Telegram obligation.
