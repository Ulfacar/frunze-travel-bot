# TASK — application deadline evidence and recalculation

- CRITICAL / solo, local implementation/checks plus review packet. Parent70-point goal remains active. TargetsG01/G02; task worker/notifications remain separate requirements.
- Source PDF §§13,14,16.5,18/19. Existing22 deadline units have null typed values and draft calendars. Do not turn their prose into approved legal arithmetic or invent counting policy.
- Observable acceptance: per-application deadline history binds a source unit/version, actual application/travel event, exact calendar versions and proposed counting policy. It distinguishes a hypothetical calculated date, a manually recorded official date with evidence, and an unknown date. Planned/client-entered trip dates cannot silently become actual anchors. Cross-person/event references are refused. Recalculation and manual changes preserve earlier snapshots, explain the reason, and invalidate a prior override when its base changes. Native scoped forms/history show uncertainty.
- Reuse existing DeadlineReview and verified WorkCalendar sources. Only supported source-anchor semantics are evaluated; missing rule value, event, calendar or mapping remains unknown. No guessed deadlines, automatic client quotes/messages, service-stage changes or fees.
- Manual operator dates require explicit confirmation, dated portal/official-document fingerprint and reason. They are recorded facts for internal follow-up, not legal publication approval. Source/owner decisions remain pending.

## Risk pre-audit

- Wrong deadline/person: existing case/application/applicant scope validation plus event-chain proof, exact source/calendars and composite scope FKs. Future/planned event cannot substitute for actual event.
- Stale dates: full immutable revisions; CAS and request identity; no automatic transfer of an old manual override onto changed sources/calendar/anchor.
- Unknowns: no partially computed date on missing source/calendar; no fallback to calendar days or another person's history.
- Actor/security: existing named full-admin/OFF/workday/write gates and signed scoped forms; strict bounded fields; no files/PII/note dumps. No new permissions.
- Reliability: locked parent, atomic append, bounded history, hash/source verification, exact uncertain-commit retry; no automatic external action.
- Migration: additive only, scoped links, populated/offline downgrade refusal; synthetic SQLite and PG DDL checks. PG runtime, independent review/audit and release approval remain UNKNOWN until evidenced.

Acceptance checks cover actual event and travel anchors, missing/foreign/future anchors, missing/different calendar versions, draft/unknown source, manual date correction/withdrawal/recalculation, replay, duplicate/concurrent/stale writes, migration recovery, native forms/mobile/no-JS.
