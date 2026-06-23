# Coolify deploy: Frunze Travel

## 0. Security

The Coolify token and Wappi token must not be committed to the repository.
If a token was pasted into a chat or screenshot, revoke it after setup and create a new one.

## 1. Coolify application

Recommended setup:

- source: this repository;
- build type: Docker Compose;
- compose file: `docker-compose.yml`;
- public service: `app`;
- public port: `8000`;
- health endpoint: `/health`.

The app exposes:

- `GET /health` - healthcheck;
- `POST /webhook/wappi` - Wappi webhook for both WhatsApp profiles;
- `/admin/board/visa` - visa board;
- `/admin/board/tours` - tours board.

## 2. Required env

Set these in Coolify environment variables:

```env
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_APP_NAME=Frunze Travel Bot
LLM_MODEL_MAIN=anthropic/claude-3.5-sonnet
LLM_MODEL_CHEAP=anthropic/claude-3-haiku

WAPPI_BASE_URL=https://wappi.pro
WAPPI_TOKEN=
BOTS=[{"id":"frunze_tours","scenario":"tours","title":"FrunzeTravel2","wappi_profile_id":"02a4708d-ec6c"},{"id":"getvisa","scenario":"visa","title":"GetVisa","wappi_profile_id":"2f099bc3-478d"}]

POSTGRES_PASSWORD=
CRM_BACKEND=postgres
STATE_BACKEND=redis
PANEL_BACKEND=postgres

ADMIN_ENABLED=true
ADMIN_USER=admin
ADMIN_PASSWORD=
```

Do not use `admin/frunze` in production. Generate a new strong `ADMIN_PASSWORD`.

Bitrix24 can be added after the first Wappi/admin test:

```env
CRM_BACKEND=bitrix24
BITRIX24_WEBHOOK_URL=
BITRIX_CATEGORY_BY_FUNNEL=
BITRIX_STAGE_MAP=
```

## 3. Cloudflare DNS

After Coolify gives the public server IP or target hostname:

- root domain `frunzetravel.kg`: add `A` record to the server IP, or `CNAME` if Coolify gives a hostname;
- `www`: add `CNAME` to `frunzetravel.kg`;
- proxy can stay enabled in Cloudflare;
- SSL/TLS mode should be compatible with Coolify HTTPS. Use `Full` if Coolify has a valid certificate.

Check:

```text
https://frunzetravel.kg/health
```

Expected response:

```json
{"status":"ok"}
```

## 4. Wappi setup

For both profiles:

- `FrunzeTravel2` profile `02a4708d-ec6c`;
- `GetVisa` profile `2f099bc3-478d`.

Set webhook URL:

```text
https://frunzetravel.kg/webhook/wappi
```

Enable incoming message webhook events. Both profiles can use the same webhook because the backend routes by `profile_id`.

## 5. First live test

Test without Bitrix first:

1. Send WhatsApp message to GetVisa: `Хочу визу в США`.
2. Send WhatsApp message to FrunzeTravel2: `Хочу тур в Турцию на июль`.
3. Open admin:
   - `https://frunzetravel.kg/admin/board/visa`
   - `https://frunzetravel.kg/admin/board/tours`
4. Check that cards appear, full context is saved, and manager takeover stops bot replies.

Only after this connect Bitrix24 as CRM mirror.
