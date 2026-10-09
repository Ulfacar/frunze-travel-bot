# E6-04 — SELF_REVIEW and independent-review packet

- CRITICAL / solo; task `ai/tasks/2026-10-10-e6-04-applicant-profiles.md`.
- Same builder context performed SELF_REVIEW. Independent review/final audit UNKNOWN; local slice PARTIALLY_READY. No production release or real personal-data processing.

## Requirement and implementation

B02: individual applicant qualification linked to the case/application register, separate from the payer and other family members. Immutable `EntryApplicantProfile` records pin request, source version/projection, result, runtime, actor, previous hash and applicant identity hash. The existing typed RU/EN partial interview is reused. Numbered applicant IDs identify records; no names or passport numbers are introduced. This is not B03/full conditional questionnaire completion.

Each applicant has its own revision counter and idempotency namespace. No payer qualification or stay history is inherited, including for the primary applicant. Applications retain their existing applicant link; register and selected attempt link to that person's native profile. Legacy contact-level interviews retain their behavior.

## Risk review

- Named full-admin authorization precedes storage. Existing KG-OFF, workday and write gates apply. Domain/API do not introduce manager access.
- Composite applicant/case and predecessor FKs; locked applicant on writes, shared lock on reads; SQLite coherent transaction and CAS. Concurrent saves produce one successor, exact retry retains the original revision. Actor changes cannot reuse a request.
- Hash-linked bounded history (250 revisions /4MiB), pinned source integrity and prior hash. Corrupt or deleted history refuses reads/writes/retries. ORM/bulk mutation protected. Privileged database replacement of a complete forged history is outside hash guarantees.
- Full replacement removes stale answers. Results retain their original meaning across runtime upgrades; explicit replay rejects changed runtime. Draft source conclusions remain non-publishable and cannot authorize quotes or legal eligibility.
- Session/actor/case/applicant/version/revision-bound signature separates legacy and individual forms; cross-person/case/session posts refused. Strict form/body/query limits and output escaping. Verified errors retain input; uncertain commit preserves the exact envelope even when reread fails. Repeated save cannot silently create a duplicate.
- Additive `e6_profiles_0020`, no backfill or conversion; empty-only locked downgrade; populated/offline downgrade refused. SQLite FK/model parity and actual migration-path writes tested. PG DDL only; runtime UNKNOWN.

## Evidence before final committed snapshot

- Initial domain13 PASS/1 fixture failure/23.12s: test incorrectly expected nested application response; corrected to the established flat response.
- Domain/migration/HTTP26 PASS/1 deprecation warning/35.47s.
- Initial browser2 failures: test expected ordinary follow-up questions after a work-purpose stop. Corrected to require specialist reasons with no questions at that step; questions return after changing purpose to tourism. Runtime behavior was correct.
- Corrected mobile390/desktop1365 without JS browser2 PASS/3 warnings/25.99s. Screens inspected; added explicit applicant/case label within result card and final browser rerun will verify committed copy.
- Cold imports profile UI, legacy intake, application register and main all exit0 in isolated no-env snapshot.
- Final committed-copy suite and manifest are recorded separately in the handoff; do not infer them from this packet.

Remaining: independent critical review/audit, PG runtime/recovery, individual stay-history binding, complete A–H questionnaires, source/privacy/owner decisions and production acceptance. Existing synthetic fixture uses legacy VisaUSA product as a scaffold; it is not an approved inbound product.
