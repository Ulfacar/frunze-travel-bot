# E6-07B — publication and runtime review packet

CRITICAL / solo; local synthetic target, independent reviewer and final auditor UNKNOWN. Review the requirement and actual diff before these builder notes. No release approval. User extended the parent target from70 to100 and asked to preserve resumable work; the original criterion definitions and weights remain unchanged.

## Requirement and boundaries

D04/D05, PDF IT/0/Б and CRM KB-03/04/05, AC-22. Review→approval→activation with atomic version switching, rollback, source provenance and per-rule expiry/revocation. A stale rule must not disable other eligible rules. All208 actual source units remain unapproved; actual policy DEC-07 is unresolved. No real publication, env change, production migration or client message.

## Implementation / risk audit

- Default-deny server-owned publisher identities, policy reference and proof hash, in addition to existing named full-admin authentication. No form can assign authority or a review period. Config names only: kg_knowledge_publishers, kg_knowledge_policy_ref, kg_knowledge_policy_sha256. Synthetic tests supply explicit policy; production values are untouched.
- Existing KnowledgeSet.active_version_id and KnowledgeVersion.status remain the sole active projection. The service changes only lifecycle fields through explicit table updates in an owned transaction after set→version locks; ORM source immutability remains. One active version, old content/history/calculations unchanged. Preview includes cases pinned to both candidate and current active versions.
- Immutable bounded250-event/16MiB journal with command/actor/policy/CAS/request hashes, semantic lifecycle replay, source/projection validation and scoped per-unit decision bindings. Exact retry preserves the original receipt. Before-commit failure rolls back status/pointer/audit; lost acknowledgement supports unchanged retry. Unjournaled active pointers fail closed. Raw corruption requires explicit recovery, never automatic reapproval.
- Explicit subset and pinned official-source review evidence. Missing value/effective date/owner/verification/review date, verify/practice/decision marks, conflict, expiry and changed findings refuse use. Historical journal validation uses evidence/time at the historical event; current eligibility is checked separately per unit. New source versions or decisions never inherit old approval. Withdrawal remains possible when findings have changed. Rollback requires current unchanged eligible evidence and matching policy.
- Runtime is an internal authenticated read adapter, not a bot rollout or public API. Consistent active/source/evidence read; literal values and provenance; no LLM or numeric rewrite. Policy revocation/change disables use. An expired/rejected/changed unit is unavailable while unaffected units continue.
- Additive0024 tables; SQLite scoped FK/model parity, PostgreSQL DDL and populated/offline downgrade refusal. PostgreSQL runtime and recovery UNKNOWN. Publication audit rejects ORM and bulk mutations; lifecycle Core updates are deliberately limited to the service.
- Native preview, source diff, linked case IDs, readiness vs active-rule eligibility, history, signed version/selection/revision/action/manifest/policy/actor/session form, full-admin/KG-OFF/workday/write gates, strict bounded input and exact uncertain-write retry even if reread fails. No arbitrary notes, URLs, file upload, roles or PII fields. Mobile390, desktop1365 without JavaScript and two-page print inspected.

## Development checks and limitations

Initial34 domain/migration/HTTP PASS (43.30s), followed by4 refinement/browser PASS (24.86s). A test expected the wrong deadline value key; corrected to the existing typed schema. A browser test called asyncio.run inside Playwright's running loop; moved the domain assertion outside Playwright. These were test-harness failures, not suppressed tests. Separate SELF_REVIEW added old-version impact/replay checks and an explicit changed-approval message in the UI.

Exact revision regression and snapshot identity follow in the matching handoff. No full-suite green, production acceptance or independent approval claim. Previously recorded tour-date baseline failure remains out of scope. Required independent CRITICAL review/audit, PostgreSQL runtime/recovery and owner/source approvals remain UNKNOWN. The parent goal stays ACTIVE after this slice.

Separate SELF_REVIEW found a real expiry-boundary race: eligibility and audit timestamp used separate clock reads. The new boundary test reproduces failure on a3316af; the fix uses one operation instant and rejects clocks earlier than the previous journal event before writing. This prevents an otherwise successful operation from creating a journal entry that fails subsequent historical validation. Final exact-revision checks must include this fix; the earlier323 PASS/2 PG SKIP on a3316af is supporting regression evidence, not the final fixed snapshot.
