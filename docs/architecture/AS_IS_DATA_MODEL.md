# AS-IS DATA MODEL — Provisional

> Status: PROVISIONAL AS-IS
> Repository baseline: a4edd5a824db6842b668f61e50f418f75b555f99
> Production snapshot: 2026-07-15T23:25–23:28Z
> Production image: sha256:1be488a9ca8e…
> Exact production source commit: UNKNOWN
> This document describes current state and does not approve target implementation.

Source: `app/integrations/crm/db.py` `[CODE-CONFIRMED]`. Runtime table/index facts: `[RUNTIME-CONFIRMED, 2026-07-15T23:25Z]`. No table rows were read; only aggregate counts.

## Conversation — table `conversations`

Panel kanban card **and** chat header. PK `id` (int, autoincrement).

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| id | Integer | no | autoinc | PK |
| user_id | String(160) | no | — | **UNIQUE, indexed**; identity key `<bot_id>:<phone>` |
| phone | String(64) | no | "" | display only |
| channel | String(32) | no | "" | |
| chat_id | String(128) | no | "" | reply address (Bitrix DIALOG_ID ≠ user_id) |
| bot_id | String(64) | no | "" | |
| funnel | String(32) | yes | null | indexed |
| stage | String(64) | no | "greeting" | board position |
| intercepted | Boolean | no | False | manager took over |
| archived | Boolean | no | False | soft-hide |
| qualification | JSON | no | {} | collected fields (free-text values) |
| ai_summary / manager_next_step / escalation_reason | Text | no | "" | manager brief |
| lead_temperature | String(16) | no | "new" | |
| assigned_to | String(64) | no | "" | manager login (or sentinel "whatsapp") |
| assigned_at | DateTime(tz) | yes | null | |
| outcome | String(24) | no | "" | in_progress\|office\|manager\|won\|lost |
| last_text | Text | no | "" | preview |
| last_sender | String(16) | no | "" | client\|bot\|manager |
| followup_sent | Boolean | no | False | legacy |
| followup_count | Integer | no | 0 | |
| bitrix_lead_id | String(32) | no | "" | mirror lead id |
| readiness_tier | String(16) | no | "" | green\|warm\|noise\|insufficient |
| readiness_reason | Text | no | "" | |
| readiness_signals | JSON | no | {} | |
| readiness_scored_at | DateTime(tz) | yes | null | |
| estimated_value | Float | yes | null | |
| estimated_value_currency | String(8) | no | "" | |
| outcome_inferred | String(16) | no | "" | won\|lost\|ghosted\|active (advisory) |
| outcome_inferred_reason | Text | no | "" | |
| source | String(16) | no | "" | ad\|post\|"" |
| source_id | String(128) | no | "" | |
| source_headline | String(300) | no | "" | |
| source_url | Text | no | "" | |
| source_payload | JSON | no | {} | normalized referral |
| created_at | DateTime(tz) | no | now() | server_default |
| last_message_at | DateTime(tz) | no | now() | server_default, **no onupdate** (deliberate) |

- Unique constraints: `user_id`. Indexes (runtime): PK, `user_id`, `funnel` → **3** `[RUNTIME-CONFIRMED]`.
- FK: none outbound; owns `messages` via relationship `cascade="all, delete-orphan"`.
- Archive/delete: soft `archived` flag; no hard-delete API; no row TTL.

## ConvMessage — table `messages`

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| id | Integer | no | autoinc | PK |
| conversation_id | Integer | no | — | **FK → conversations.id**, indexed |
| sender | String(16) | no | — | client\|bot\|manager |
| text | Text | no | "" | |
| status | String(16) | no | "" | ""\|pending\|sent\|delivered\|failed |
| provider_msg_id | String(128) | no | "" | declared `index=True` |
| idempotency_key | String(128) | no | "" | declared `index=True` |
| created_at | DateTime(tz) | no | now() | server_default |

- FK: `conversation_id → conversations.id` `[CODE-CONFIRMED]` + `[RUNTIME-CONFIRMED]`.
- Indexes (runtime): **2** (PK + conversation_id) `[RUNTIME-CONFIRMED]`. Note: `status`/`provider_msg_id`/`idempotency_key` were added on existing installs via `_ensure_columns()` `ALTER TABLE ADD COLUMN`, which does **not** create the declared `index=True` indexes → the `provider_msg_id`/`idempotency_key` indexes are **absent** in this runtime `[RUNTIME-CONFIRMED]`.

## Deal — table `deals`

| Column | Type | Nullable | Default |
|---|---|---|---|
| id | Integer | no | autoinc (PK) |
| user_id | String(128) | no | — (indexed, **not unique**) |
| funnel | String(32) | no | — |
| stage | String(64) | no | "new" |
| contact | JSON | no | {} |
| data | JSON | no | {} |
| notes | JSON | no | [] |
| created_at / updated_at | DateTime(tz) | no | now() (updated_at onupdate) |

- No FK to Conversation. Indexes (runtime): 2 (PK + user_id). No archive/TTL.

## FaqEntry — table `faq_entries`

| Column | Type | Nullable | Default |
|---|---|---|---|
| id | Integer | no | autoinc (PK) |
| funnel | String(32) | yes | null (indexed) |
| enabled | Boolean | no | True (indexed) |
| priority | Integer | no | 0 (indexed) |
| title | String(160) | no | "" |
| patterns | JSON | no | [] |
| negative_terms | JSON | no | [] |
| answer | Text | no | "" |
| handoff_only | Boolean | no | False |
| allow_during_qualification | Boolean | no | True |
| updated_by | String(64) | no | "" |
| created_at / updated_at | DateTime(tz) | no | now() (updated_at onupdate) |

- Indexes (runtime): 4. No version/valid_from/valid_until columns; no rollback history.

## AuditLog — table `audit_log`

| Column | Type | Nullable | Default |
|---|---|---|---|
| id | Integer | no | autoinc (PK) |
| manager | String(64) | no | "" |
| action | String(32) | no | — |
| user_id | String(128) | no | "" (indexed) |
| detail | Text | no | "" |
| created_at | DateTime(tz) | no | now() |

- Records manager actions; stores no before/after content.

## AppFlag — table `app_flags`

| Column | Type | Nullable | Default |
|---|---|---|---|
| key | String(64) | no | — (PK) |
| value | Boolean | no | False |
| updated_at | DateTime(tz) | no | now() (onupdate) |

- Runtime feature flags; survives restart; no "changed-by" column.

## Missing domain entities `[CODE-CONFIRMED / NOT FOUND]`

The following are **absent** as first-class entities (fields NOT designed here):
- **Contact / Customer** — [NOT FOUND]; contact data inline in `Conversation.qualification`/`phone` and `Deal.contact`.
- **Separate Lead** — [NOT FOUND]; the Conversation row is the lead.
- **Request** — [NOT FOUND]; `funnel` is a column, not a request record.
- **Offer** — [NOT FOUND]; tour search results are ephemeral, no id/link stored.
- **Booking** — [NOT FOUND].
- **Payment** — [NOT FOUND]; "paid" is `outcome == "won"` string.

## Identity key and its consequences

```text
identity key = <bot_id>:<phone>   (Conversation.user_id, UNIQUE)
```

- One phone across **different bot_id** values → **different Conversation rows** (separate card/state/intercept) `[CODE-CONFIRMED]`.
- Repeated interest within the **same bot_id** reuses the **same Conversation** row `[CODE-CONFIRMED]`.
- A new service enquiry through the same bot_id can **overwrite** `qualification` / `funnel` / `stage` on that single row (no second concurrent request) `[CODE-CONFIRMED]`.
