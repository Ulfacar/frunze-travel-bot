# BASELINE — Provisional AS-IS

> Status: PROVISIONAL AS-IS
> Repository baseline: a4edd5a824db6842b668f61e50f418f75b555f99
> Production snapshot: 2026-07-15T23:25–23:28Z
> Production image: sha256:1be488a9ca8e…
> Exact production source commit: UNKNOWN
> This document describes current state and does not approve target implementation.

## Repository

- Branch: `feature/token-economy-phase1` `[CODE-CONFIRMED]`
- HEAD: `a4edd5a824db6842b668f61e50f418f75b555f99` `[CODE-CONFIRMED]`
- Working tree: no tracked or staged changes to `app/`, `tests/`, config `[CODE-CONFIRMED]`
- Untracked at baseline: only `docs/*` and `scripts/make_calendar_pptx.py` — no effect on app/tests `[CODE-CONFIRMED]`

## Deployed image (server)

- No `.git` on server → image-based deploy `[RUNTIME-CONFIRMED, 2026-07-15T23:25Z]`
- Image: `sha256:1be488a9ca8e…`, built `2026-07-11T20:53:59Z` `[RUNTIME-CONFIRMED]`
- Container: created/started `2026-07-11T20:54Z`, uptime ~4 days, `healthy` `[RUNTIME-CONFIRMED]`

## Repository vs deployed image — divergence

- The deployed image is OLDER than repository HEAD `[RUNTIME-CONFIRMED]`.
- Deployed image **contains** the change marker `app/core/morning_brief.py` (a change introduced before a later boundary) `[RUNTIME-CONFIRMED]`.
- Deployed image **does NOT contain** markers `DOZHIM_AND_PRICE_FORK`, `FOLLOWUP_PINGS_SECOND`, or the "УСТАЛОСТЬ ОТ ВОПРОСОВ" block (introduced by commits `0bc2a96` / `a4edd5a`) `[RUNTIME-CONFIRMED]`.
- Exact deployed source commit: **UNKNOWN** `[NOT AVAILABLE]` — no `.git`, file-copy deploy; only bounded, not pinned.

## Declared topology (repository)

- `Dockerfile`: `python:3.12-slim`, non-root, `EXPOSE 8000`, `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000` (no `--workers`) `[CONFIG-CONFIRMED]`
- `docker-compose.yml`: services `app` + `db` (postgres:16-alpine, volume `pgdata`) + `redis` (redis:7-alpine appendonly, volume `redisdata`); healthchecks; `restart: unless-stopped`; publishes `8000:8000` `[CONFIG-CONFIRMED]`
- `docker-compose.vps.yml` overlay: remaps to `127.0.0.1:8077:8000` (host nginx fronts) `[CONFIG-CONFIRMED]`
- No Alembic dir; schema via `create_all` + `_ensure_columns()` ALTER at startup `[CODE-CONFIRMED]`

## Actual runtime topology (server)

- 1 app container, 1 uvicorn process, no `--workers` `[RUNTIME-CONFIRMED]`
- Scheduler runs inside the web process (no separate scheduler container) `[CODE-CONFIRMED]` + `[RUNTIME-CONFIRMED single container]`
- Postgres `16.14` (up ~11 days, healthy), Redis `7.4.9` AOF enabled (up ~11 days, healthy) `[RUNTIME-CONFIRMED]`
- Host nginx on `:80`/`:443`; app published only on `127.0.0.1:8077`; Postgres bound `127.0.0.1:5432` `[RUNTIME-CONFIRMED]`

## Defaults vs production

| Aspect | Repo / compose default | Production runtime | Marker |
|---|---|---|---|
| Deployed code | HEAD `a4edd5a` | older image; bounded, exact SHA UNKNOWN | `[RUNTIME-CONFIRMED]` |
| STATE_BACKEND / PANEL_BACKEND / CRM_BACKEND | code: memory/memory/stub | overridden (effective redis/postgres/postgres) | `[RUNTIME-CONFIRMED]` |
| LLM_MODEL_MAIN / LLM_MODEL_CHEAP | claude-3.5-sonnet / claude-3-haiku | overridden (values not disclosed) | `[RUNTIME-CONFIRMED]` |
| SESSION_SECRET / ADMIN_PASSWORD | insecure/empty in compose | custom-nonempty | `[RUNTIME-CONFIRMED]` |
| WEBHOOK_SECRET | empty | empty (verification off) | `[RUNTIME-CONFIRMED]` |
| bitrix_mirror_enabled / outcome_infer_enabled | code default OFF | ON | `[RUNTIME-CONFIRMED]` |
| bots_enabled (global) | code default True | false; per-bot overrides apply | `[RUNTIME-CONFIRMED]` |

## Test baseline

- Command: `python -m pytest -q` on HEAD `a4edd5a` `[TEST-CONFIRMED]`
- Collected: **335**; Passed: **335**; Failed/Skipped/xfail: **0/0/0**; Duration: **32.46s**; Warnings: **1** (Starlette testclient deprecation, not project code) `[TEST-CONFIRMED]`
- Composition: **334 product tests** in `tests/` + **1 BMAD tooling test** (`_bmad/scripts/tests/test_resolve_customization.py`, collected because `_bmad` is not a dot-directory) → **335 total collected** `[TEST-CONFIRMED]`
- Network guard: **absent** — no `conftest.py`, no socket guard `[NOT FOUND]`
- The current suite passed **without known external calls** (mocks/monkeypatch/FakeAsyncClient/FakeRedis; LLM disabled by empty key). This is not proof of a systemic network barrier. `[TEST-CONFIRMED]`

## Evidence limitations

- Production secret VALUES intentionally not read (presence/classification only).
- Successful Wappi/TourVisor operations are not fully log-instrumented → call volumes not measurable from logs.
- Log window limited to current container lifetime (`docker` json-file, since 2026-07-11 start; older may be rotated).
- Exact deployed commit not resolvable without `.git`.

## Known unknowns

- Exact production source commit.
- Real values of overridden LLM models and secrets.
- TLS certificate/redirect behavior, trusted-proxy handling behind nginx.
- Live CTWA payload schema.
- Bitrix Lead→Deal conversion / won-lost workflow (outside our DB).
- Backup/restore procedure (none found locally).
