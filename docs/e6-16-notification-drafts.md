# Internal notification drafts — local contract

An existing full administrator can select one of the13 Appendix A templates,
enter typed manual values, preview the exact text, and explicitly preserve that
draft for one application. Source-marked blocked templates and unresolved slots
remain visibly blocked/unresolved. Approved or refused applications can retain
outcome drafts. Saving does not change the application outcome or any other
business journal and does not authorize publication, scheduling or transmission.

`kg_notification_storage_policy` defaults to an empty object. An explicit policy
must name existing permitted operators, finite dates, privacy/source/storage
evidence references and hashes, a retained renderer/catalog and allowed templates.
The policy authorizes internal storage only. Its presence does not certify the
entered facts or the source text. Real approval and retention decisions remain
outside this local synthetic implementation.

The application page links to its separate draft journal. Preview remains
read-only; saving requires an explicit checkbox and signed scope/value/version
confirmation. Existing authentication, KG and workday/write gates apply. Native
forms reject duplicate/extra fields and malformed or oversized UTF-8 input. All
source and entered text is escaped. There is no recipient, attachment or send
action. The original generic template preview remains read-only.

Migration `e6_notification_drafts_0032` adds one immutable scoped table. Each row
records the application event, applicant and case pins, exact command and result,
source/catalog/renderer, policy and authority, creator and server timestamp.
The per-application sequence has128 rows maximum,128KiB per canonical row and
4MiB per journal. A separate conservative SQL materialization guard permits up
to six times those numeric values in SQL text characters for JSON escapes and
separators; this is a character bound, not a physical UTF-8 byte measurement.
The canonical UTF-8 byte limits remain exact. SQL count/size checks precede JSON materialization; the selected
bounded history is semantically replayed, not merely checksum-checked. Foreign
keys, uniqueness and ORM/bulk immutability guards preserve scope and ordering.
An empty downgrade is allowed; a populated downgrade refuses to delete history.

The request-key namespace is one application. Concurrent identical confirmations
return one receipt. A changed command with the same key or a stale revision or
preview is rejected. Case/application locking precedes server-time, policy-day
and preview checks. Application changes while waiting invalidate the preview.
An exact authorized retry is resolved before current-policy or new-write capacity
checks, including a lost commit acknowledgement. The native retry retains the
original signed values even if rereading the journal also fails.

Old receipts use retained renderer/catalog assets. Current policy or source
unavailability blocks new writes but preserves valid old reads and retries.
Current application/source/authority state is displayed separately from the
immutable receipt. A later different template does not automatically supersede
all earlier drafts. Inputs remain explicitly `manual_unverified`, with sending
and publication flags always false. Complete database/asset forgery is outside
the semantic consistency guarantee.

Acceptance requires negative domain/native tests, actual isolated PostgreSQL
schema and concurrency checks, fresh-schema COPY recovery with old retry and new
write, mobile/no-JavaScript/print inspection, independent review and final audit.
Native pg_dump remains unavailable under the existing Windows App Control rule;
COPY rehearsal is not a production backup or PITR claim. No deploy, production
migration, activation, real client input or outbound integration is included.
