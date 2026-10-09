# E6-07A — knowledge review evidence packet

CRITICAL / solo, local synthetic target. Independent reviewer and final auditor UNKNOWN. This packet is not a release approval; parent70-point goal remains ACTIVE. Review the requirement and actual changes before these builder notes.

## Scope and invariants

D03 (PDF appendicesГ/Д): durable confirmation/rejection/correction evidence for a specific imported version/unit. `knowledge_decisions.py`, model KnowledgeDecision/migration0023, native `kg_knowledge_decisions`, and related tests. Original unit value, marks/conflict, version status and active pointer are untouched. A recorded confirmation is not legal source verification or permission to publish/quote. Technical-check evidence must not become legal confirmation in the later publication adapter.

- Named full admin before engine/payload; existing KG-OFF/workday/write and scoped actor/session/version/unit/revision/verdict HMAC. No new roles/permissions.
- Verify accepted sealed source bundle and unit; lock set→version, pin unit/bundle hashes. Bounded immutable250-revision/2MiB chain, scoped FK, CAS, exact command/actor/request retry and owned transactions. No mutable history or caller-supplied source body.
- Evidence kinds/reasons/ref codes/proof/date are typed and bounded. Explicit next-review date for confirmation; no invented review period. Past review records remain readable and visibly expired. No fetched URL, arbitrary free text, file upload or personal data.
- New source versions do not inherit old findings. Blocked/NULL imported values remain blocked/NULL even when a reviewer records a confirmation. Old snapshots/history remain available; raw mismatch stops read/write/retry. Source publishing is separate D04/D05 work.
- Additive migration, SQLite FK/model parity, PostgreSQL DDL, populated/offline downgrade refusal. PostgreSQL runtime/recovery UNKNOWN. ORM and bulk decision mutations rejected.
- Native catalog search/pagination/version selection, source and decision history, readonly historical views, uncertain-write retry even when reread fails, no fresh forms on uncertainty, mobile/no-JS/one-page print.

## Evidence and remaining gates

Development focused domain21 PASS; HTTP5 PASS; migration/browser5 PASS before minor empty-catalog form cleanup. Final exact revision/checks are recorded in the matching handoff/snapshot after commit. Mobile390, desktop1365 without JS and one-page print visually inspected. All data/confirmation evidence is synthetic; all208 real source units remain drafts,22 actual typed deadline values remain NULL.

SELF_REVIEW examines lost commit acknowledgement, concurrent saves, reused keys/actor substitution, scoped source link, raw corruption, schema immutability and HTTP protection; it is not independent approval. No full-suite/production/deploy claim. Existing tour-date baseline failure and critical independent/PG gates remain open.
