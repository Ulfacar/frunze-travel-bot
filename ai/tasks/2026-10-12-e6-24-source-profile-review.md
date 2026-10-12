# TASK: E6-24 — source coverage and qualification persistence review

STATUS: DONE for reviewed local A01/A02/A03/A04/B01, code
693d683b9a0adcb8f76d5551bf0f121ca6824fec. Independent APPROVE/separate GO on R2;
handoff `ai/handoffs/2026-10-12-2038-e6-24-source-profile-review.md`.
Separate old-profile route compatibility defect is E6-26, not complete C05.

- CLASS: CRITICAL (source integrity and saved personal qualification); mode solo.
- Completion target: reviewed local behavior for fixed A01/A02/A03/A04/B01, without changing acceptance definitions or scores.
- Parent: authorized continuation of PDF/CRM work. Base87ad9e759aae223258742d286310aba2155f112d on fix/tours-search-quality.
- Existing UI and new E6-22 route edits are separate. This review covers established corpus/extraction/search/schema and existing saved draft qualification, not new approved-route behavior.
- Read-only independent review first; a separate final audit is required before marking CRITICAL review PASS.

Inspect source requirements and actual code before earlier builder conclusions. Verify versioned lossless source text/provenance, strict structural and semantic validation, complete coverage and reproducible extraction, source-bound local search/native citations/uncertainty, and saved draft qualification CAS/idempotency/history/RU-EN native form. Test credible malformed input, source corruption, wrong scope and stale retries using isolated synthetic databases; exercise actual local PostgreSQL where lock/storage behavior matters.

Source correctness/actual legal approval are not proved by extraction, tests or document hashes. Preserve all208 real draft statuses. No source policy, production changes, real personal data, outside messages or deployment are authorized. Env-free snapshots only; never read root .env. Existing local PostgreSQL55971 may be used only with the established private opt-in fixture and unique temporary databases.

Report exact evidence identities, commands/results and confirmed defects. Fix only confirmed scoped defects, then review/audit again. Missing evidence stays UNKNOWN. Do not close C05, interview/channel integration, pilot or owner acceptance from these checks. Update STATE and write a scoped handoff at completion.
