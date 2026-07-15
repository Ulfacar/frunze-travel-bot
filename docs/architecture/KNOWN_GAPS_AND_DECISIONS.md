# KNOWN GAPS AND DECISIONS — Provisional

> Status: PROVISIONAL AS-IS
> Repository baseline: a4edd5a824db6842b668f61e50f418f75b555f99
> Production snapshot: 2026-07-15T23:25–23:28Z
> Production image: sha256:1be488a9ca8e…
> Exact production source commit: UNKNOWN
> This document describes current state and does not approve target implementation.

## Confirmed technical gaps

- No exact deployed-commit traceability (no `.git` on server; only bounded markers) `[RUNTIME-CONFIRMED]`.
- No durable outbox for outbound messages `[CODE-CONFIRMED]`.
- No versioned DB migrations (schema via `create_all` + `_ensure_columns()` ALTER; some declared indexes absent on existing tables) `[CODE-CONFIRMED]` + `[RUNTIME-CONFIRMED]`.
- No distributed lock / leader election for scheduler or dialog serialization (single-process assumption) `[CODE-CONFIRMED]`.
- No Bitrix CRM ingestion (one-way mirror only; won/lost not read back) `[CODE-CONFIRMED]` + `[RUNTIME-CONFIRMED, 0 inbound]`.
- No working advertising attribution (no successful CTWA capture; no captured referral metadata across 1074 Conversation records) `[RUNTIME-CONFIRMED]`.
- No application-level webhook verification (empty `WEBHOOK_SECRET`) `[RUNTIME-CONFIRMED]`.
- No PII masking in logs/exports `[CODE-CONFIRMED]`.
- No documented local backup/restore mechanism found `[NOT FOUND]`.
- Mixed Conversation/Lead/Customer/Request responsibilities in one entity `[CODE-CONFIRMED]`.
- Manual Kanban stage overwrite by the bot on next inbound `[CODE-CONFIRMED]`.
- Weak manager ownership protection (only the buyers-claim path is atomic) `[CODE-CONFIRMED]`.

## Business decisions required `[BUSINESS-UNCONFIRMED]`

- Source of truth **per entity** (not one global answer).
- Where managers answer (own panel vs Bitrix vs WhatsApp).
- Contact ownership.
- Lead ownership.
- Request / Deal ownership.
- Payment / "won" source.
- Bitrix workflow (Lead→Deal conversion; where a sale is recorded).
- Manual override rules (should a drag survive the next bot turn).
- Manager locking (block another manager's active dialog).
- FAQ price publishing process (review/approval gate).
- PII retention policy.
- Advertising attribution priority.
- Scaling expectation (single worker vs horizontal).
- Final GetVisa / "Frunze Travel Visa" branding (residual "GetVisa" strings exist).

## Not approved

Explicitly, at this stage:

- Target architecture is **not approved**.
- Implementation is **not approved**.
- Production rollout is **not approved**.
- Fable UX work is **not approved**.

This document records current state and open decisions only.
