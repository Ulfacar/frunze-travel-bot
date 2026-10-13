# TASK — individual applicant qualification

- CRITICAL / solo. Base `6c4b587`; local implementation and review packet, no production release. Parent70-point goal; targetB02.
- Observable acceptance: each numbered applicant has independent immutable qualification revisions pinned to source version, facts, result, actor and time. Same payer can have multiple applicants/cases without copying or sharing answers, counters or stay history. An application remains linked to its applicant. Native register→profile→save/resume/history flow supports partial/unknown RU/EN facts and safe exact retry.
- Reuse existing schema/evaluator/form controls. Preserve the payer-level legacy interview. No automatic conversion of family summary rows to identified applicants; no real names/passport numbers/files. Imported sources stay draft and cannot grant eligibility or quotes.

## Risk pre-audit

- Cross-person contamination: explicit case/applicant composite constraints, source applicant hash, no inherited contact qualification/history. Payer is labeled separately.
- Stale/concurrent changes: locked applicant parent, CAS, content/actor-bound idempotency; complete replacement removes stale answers.
- Integrity: bounded immutable hash-linked revisions; pinned source projection and runtime; tampering fails closed. No result silently recomputed after code upgrade.
- Access: existing full-admin/OFF/workday/write gates before storage; signed actor/session/case/applicant/source/revision envelope; bounded strict forms and escaped output; uncertain commits retain exact request.
- Migration: additive table; scope and predecessor FKs; populated/offline downgrade refusal, synthetic SQLite and PG DDL checks only. Production/PII/source policy approvals remain separate.
- Required independent critical review/audit and PostgreSQL runtime remain UNKNOWN if unavailable; local target PARTIALLY_READY. Do not inflate B03/full questionnaire completion.
