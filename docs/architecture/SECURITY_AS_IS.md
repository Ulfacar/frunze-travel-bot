# SECURITY AS-IS — Provisional

> Status: PROVISIONAL AS-IS
> Repository baseline: a4edd5a824db6842b668f61e50f418f75b555f99
> Production snapshot: 2026-07-15T23:25–23:28Z
> Production image: sha256:1be488a9ca8e…
> Exact production source commit: UNKNOWN
> This document describes current state and does not approve target implementation.

No secret values, hashes, lengths, or partial characters are shown. Classification only.

## Authentication / secrets

- Admin password: **custom-looking** (not empty, not the known insecure default) `[RUNTIME-CONFIRMED]`.
- Session secret: **custom-looking** (not empty, not the known insecure default) `[RUNTIME-CONFIRMED]`.
- Application webhook secret (`WEBHOOK_SECRET`): **empty** → application-level webhook verification is inactive (fail-open) `[RUNTIME-CONFIRMED]`.
- Possible nginx compensating controls (IP allow-list, auth, path limits) in front of the app: **unknown** `[NOT AVAILABLE]`.
- Manager passwords: stored/compared in plaintext (timing-safe compare) `[CODE-CONFIRMED]`.

## Web application controls

- CSRF protection: **absent** (reliance on `same_site=lax` only) `[CODE-CONFIRMED]`.
- Login rate limiting: **in-memory**, failures-only, per client host, single-process (resets on restart) `[CODE-CONFIRMED]`.
- PII masking in logs/exports: **absent**; some diagnostic log paths include raw payloads `[CODE-CONFIRMED]`.
- Authorization: sensitive mutations (FAQ save/toggle, feature-flag/bot toggles, manual followup) gated by `require_admin` only, not `require_full_admin`, and without funnel/brand scope `[CODE-CONFIRMED]`.

## Network exposure

- Application bind: reachable only via loopback (`127.0.0.1:8077`) fronted by host nginx; not directly public `[RUNTIME-CONFIRMED]`.
- Postgres: bound to `127.0.0.1:5432` (localhost only) `[RUNTIME-CONFIRMED]`.
- HTTPS: nginx listener on `:443` observed; TLS certificate validity and HTTP→HTTPS redirect **not verified** (no external request performed) `[RUNTIME-CONFIRMED listener]` / `[NOT AVAILABLE certificate]`.
- Trusted proxy behavior (X-Forwarded-For handling behind nginx): **unknown** `[NOT AVAILABLE]`.

## Cookies (declared)

- Session cookie: `https_only=True` (Secure), `same_site="lax"`, HttpOnly (Starlette default) `[CODE-CONFIRMED]`.
- Observed cookie flags on a live panel response: **not verified** (panel not requested) `[NOT AVAILABLE]`.

## Data lifecycle

- Retention / right-to-delete: **absent**; only soft-archive exists; Postgres chat/qualification data persists indefinitely `[CODE-CONFIRMED]`.
- Local/documented backup mechanism: **not found** on server (no frunze backup script/cron/dump/timer) `[NOT FOUND]`.
- Provider-level snapshots (host/hypervisor): **not checked** `[NOT AVAILABLE]`.
