# E6-29 — dialogue interrupts and specialist escalation

CRITICAL / solo. Parent: full local inbound PDF/CRM continuation. Target:
reviewed local H02 implementation and evidence; no production, live channel
binding, actual outbound messages, source/privacy approval or pilot activation.

Fixed H02 (2 points), PDF4/17/Б.6: interrupts, stop factors and specialist
escalation in dialogue flow. Existing typed interview has pause/interrupt/
handoff/ACK and immutable consent stop semantics; its retained old state says
channel_suppression=not_integrated. Existing entry_channel_stops and dialogue
integration must be inspected before assuming a new integration is needed.

First perform independent source-first risk/gap audit against actual code and
checks. Identify the smallest missing connected behavior: exact person/channel
scope, pending/accepted handoff, consent withdrawal, late correction, intake or
qualification stops, human-requested stop, uncertain answers and actual
orchestrator/outbound suppression. Explicit current server authority is required
for any binding. Do not infer payer identity as applicant or enable real channels.

Acceptance must exercise actual connected functions on synthetic local data,
including missing/expired/revoked authority, case/person/channel isolation,
concurrency and failure recovery. Old immutable interview replay stays unchanged;
new connection evidence belongs to a separate versioned receipt if necessary.
No POINTS until implementation, relevant checks, independent review and separate
final audit are evidenced. J01/J02/J03 and real J05 remain separate.

Status: IMPLEMENTING. Independent source-first pre-audit completed in
`ai/reviews/2026-10-12-e6-29-pre-audit.md`, covering all57 section17 rows and
4.1/Б.6 stops. Initial pure RU/EN conservative triage is an unconnected draft;
it does not close H02. Explicit route/person authority, atomic cause/handoff/
permanent suppression, current calendar/history stops and positive normal-turn
handling still need implementation and evidence. Source policy remains empty.
