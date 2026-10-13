# Separate-domain CRM release

- User request: finish the PDF scope and deploy the CRM as a separate application/domain.
- Class / mode / target: CRITICAL / solo / separately hosted reviewed release.
- Base: `5200ac1bdec2faab82840e01e6372b33851b9a1d`, runtime `ce335c740748affdb3ec07ace202e37e1c74d16e`.
- Status: PARTIALLY_READY. Reviewed R9 runs on the isolated synthetic server;
  exact public hostname remains unanswered. Private administrator access is the
  stated default; no other accounts or public anonymous access are added.

## Authority and scope

The current user request explicitly authorizes a separate CRM deployment and
supersedes the prior no-deployment boundary for this new service. It does not
authorize replacing/restarting the existing bot, copying its customer data or
secrets, turning on messages, inventing business policy, or marking J05 accepted.
New isolated service/database initialization, its own credentials, HTTPS and
bounded routing are implementation details within the authorized deployment.
Existing production data and its database must remain untouched.

User follow-ups: send a completion notice and CRM link/PDF through the existing
personal Telegram bot after completion. Revalidate the configured private user
destination; no customer/team/group sends. Prepare a Claude handoff document and
link it from CLAUDE.md; no need to invoke a paid/external model for this handoff.

Preserve the three existing UI changes. Inspect them as the requested visual
baseline before including them in the separate release; preserve unrelated files.
Root .env remains unread; all application tests/builds use env-free snapshots.
Do not reuse the pytest-based loopback demo as a hosted entry point.

## Observable acceptance

1. Separate durable CRM app with existing native domain flows, safe configured
   authentication, secure sessions and required access enforcement.
2. No bot startup/scheduler, provider webhooks, automatic/customer sending or
   production credentials/data in the new service; external effects blocked.
3. Isolated database/volumes/network/private proxy and complete image assets;
   explicit schema initialization for the new database only; backup and rollback.
4. Login, denied anonymous/invalid writes, case creation/profile/documents/tasks,
   persistence after restart, relevant mobile readability and real TLS routing.
5. Independent review and separate release audit of the actual candidate, then
   authorized deployment to the user's confirmed hostname. Existing bot health
   and service identity remain unchanged.
6. Updated final PDF and runbook with actual URL/revision, performed checks and
   real remaining owner decisions. Deployment alone does not award J05.

## Pre-audit and required evidence

Pre-audit and independent review completed; current actual image R9 is mapped
in the separate final audit. Local compatibility144 PASS; standalone/recovery
20 PASS; UI/calendar/card27 PASS in distinct env-free snapshots. Connected real
browser/native writes and post-replacement12 GET pages pass. Actual isolated
Linux backup/restore compares78 tables,61 sequences and160 foreign keys.
No claim that these separate executions are one full suite.

Manifest `10dc6b02b0909c3042b07b229f87429e983d82b909f3445bb8b387c039ebe89b`,
image `sha256:4f4afd16d8ef3198fb72ccfaae84b44394ec8d1cd3e6e65f6b85ca97e1df43bb`.
Current code is an uncommitted R9 snapshot on the stated base. Existing bot,
database and Redis retain original container IDs/start times and healthy state.
No main nginx change, public route, source approval or completion Telegram send.

Remaining: exact hostname, fresh separate operator database/secrets, actual
public TLS/proxy/acceptance and final release evidence. J05 real owner acceptance
remains UNKNOWN. Handoff: `ai/handoffs/2026-10-13-standalone-crm-checkpoint.md`.
