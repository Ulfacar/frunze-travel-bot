# TASK — bounded document quarantine

CRITICAL / solo. Local synthetic completion target, F06 (PDF §§5.5/18). Parent100-point goal remains ACTIVE. Independent reviewer and final auditor required, currently UNKNOWN. No production deployment, real scans, existing data migration, external scanner/message or owner policy decision is authorized by this task.

## Observable acceptance

- An absent-by-default, explicitly configured server policy authorizes named existing full-admin users and binds validity, permitted types, byte/count limits, storage location and privacy/retention reference/proof. Do not infer business defaults, retention periods or permission expansion. No browser can choose a storage root or policy.
- Stream bounded JPEG/PDF input on an authenticated, case/application/item/version-scoped route. Validate declared type, extension/signature and SHA256; ignore client filenames for storage paths. No URL fetch, extraction, rendering or executable parsing of uploaded content. A signature check does not prove a file harmless.
- Every accepted upload enters quarantine. No automatic release, public URL, document approval or portal submission. Keep receipt metadata linked to an exact file and package version. No quarantined content becomes reviewed merely through upload. Later malware/release policy is separate and remains blocked.
- Storage and metadata must handle retry, racing keys, incomplete streams, count/size limits, commit failure and lost acknowledgement. Avoid overwrites and unbounded orphan creation. Delete only a newly created temporary file owned by the failed operation, after confirming it is within the configured test/storage root; never delete existing history or caller-selected paths.
- Add a schema change only when required by a durable scoped receipt/audit. Preserve old package and matrix history. SQLite FK/model parity, PG DDL and safe populated/offline downgrade checks; real PostgreSQL/recovery remains UNKNOWN until exercised.
- Native CRM displays policy-disabled/quarantined/rejected states, access and write gates, errors and exact retry. Synthetic bytes only in tests; negative cases include traversal, spoofed extension/MIME, oversize/chunk limits, checksum mismatch, untrusted owner/case/item, duplicates/concurrency and failure recovery.

## Risk pre-audit / boundaries

Files may contain personal data or malicious input. Current source-policy approvals are unresolved; real operation stays OFF. Work locally against env-free archives and disposable synthetic storage. Do not add a cloud bucket, external paid scanner or a default retention/deletion policy. Server-owned configuration is an explicit future gate, not approval to populate it. Do not expose hashes/paths/content unnecessarily or log raw filenames/content.

## Current state / next action

### Reviewed local completion2026-10-11

DONE for local synthetic target at `4c570a3408d21d1749543c1144eabf4cdc6a20fa`. Independent reviewer APPROVE and separate final auditor GO for25-file snapshot. Handoff `ai/handoffs/2026-10-11-0030-e6-09-document-quarantine.md` records broad218 PASS/2 PG SKIP plus final UI39 and quarantine/issued68 PASS, exact snapshot identities and limitations. F06 adds2 points (69/100 total); parent scope remains incomplete. No real policy, real file, live migration or deployment. Next prepared E6-10 procedural stages task; user authorized a final Telegram report to themselves after overnight local work.

### 2026-10-11 implementation decision and pre-audit

Use the existing domain database for immutable bounded binary quarantine (SQLite BLOB / PostgreSQL BYTEA), not a new filesystem store. This is a technical implementation choice, not a storage/privacy policy approval: the absent-by-default policy must explicitly choose `domain_database`, authorized existing full-admin users, validity, per-file and per-application quotas, privacy/retention references and proof hashes. No policy is populated by this task. The earlier filesystem draft above is superseded: no caller path, filename-based storage, temporary files, orphan cleanup or filesystem deletion is needed. Filenames are only validated for type/path spoofing and are never retained.

One transaction must bind the quarantine bytes, checksum, immutable metadata and exact package receipt event; partial or failed saves roll back together, lost acknowledgement supports the same request. A bounded streaming multipart reader holds one small file in memory and never parses/renders document contents. No file download/release route is added. Package review and approval must refuse quarantined content even if metadata is re-entered. Required checks include malformed/incomplete multipart, oversize header/field/file/body/chunk streams, traversal/MIME/signature spoofing, checksum change, stale forms, cross-case/application/session requests, duplicate/concurrent writes, quotas, corruption, rollback, and lost acknowledgements.

Independent pre-auditor/final auditor: separate agent `quarantine_audit`; actual findings and verdict will be recorded in `ai/reviews/2026-10-11-e6-09-quarantine-audit.md`. E6-08 review fixes are being verified first. No production/schema/environment configuration has been changed.

E6-08 commit26655d4 implements metadata receipts and policy-gated package acceptance, with files deliberately absent. Exact-commit checks are still running when this follow-up task is created. First finish that evidence/handoff, then inspect its source/receipt bindings and implement the smallest quarantine adapter with explicit policy and durable recovery. Reuse existing full-admin/OFF/workday gates and case→application ordering. No new source-law claims.
