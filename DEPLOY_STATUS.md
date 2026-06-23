# Frunze Travel Bot: Deploy Status

## Done

- Repository is prepared for Coolify Docker Compose deploy.
- `docker-compose.yml` defines:
  - `app` service on port `8000`;
  - Postgres service;
  - Redis service;
  - persistent volumes for Postgres and Redis.
- Wappi webhook route is implemented:
  - `POST /webhook/wappi`
- One shared Wappi webhook is used for both WhatsApp profiles. The backend routes messages by `profile_id`.
- Wappi webhook URL was set in both Wappi accounts:
  - `FrunzeTravel2`, profile_id `02a4708d-ec6c`
  - `GetVisa`, profile_id `2f099bc3-478d`

## Verified Locally

- Docker Compose config is valid:
  - `docker compose config`
- Test suite passes with local Python path:
  - command: `$env:PYTHONPATH='.'; $env:PYTEST_ADDOPTS='-p no:cacheprovider'; pytest`
  - result: `69 passed`
- Git repository is clean and `main` is synced with `origin/main`.

## Public URLs

After DNS and Coolify deploy are working:

```text
https://frunzetravel.kg/health
https://frunzetravel.kg/webhook/wappi
https://frunzetravel.kg/admin/board/tours
https://frunzetravel.kg/admin/board/visa
```

The Wappi webhook URL for both accounts:

```text
https://frunzetravel.kg/webhook/wappi
```

## Current Blockers

- `frunzetravel.kg` currently does not resolve to an app server IP/CNAME.
- Coolify deploy API returned `401 Unauthorized` with the available token, so deploy could not be triggered from the CLI.

## DNS Needed In Cloudflare

If Coolify/VPS provides a public IPv4 address:

```text
Type: A
Name: @
Content: <COOLIFY_SERVER_IP>
Proxy status: DNS only first
TTL: Auto
```

```text
Type: CNAME
Name: www
Target: frunzetravel.kg
Proxy status: DNS only first
TTL: Auto
```

If Coolify provides a hostname instead of an IP:

```text
Type: CNAME
Name: @
Target: <COOLIFY_HOSTNAME>
Proxy status: DNS only first
TTL: Auto
```

## Next Steps

1. Add DNS records in Cloudflare.
2. Deploy the app in Coolify using Docker Compose.
3. Set Coolify public service:
   - service: `app`
   - port: `8000`
   - health endpoint: `/health`
4. Set required environment variables in Coolify:
   - `OPENROUTER_API_KEY`
   - `WAPPI_TOKEN`
   - `POSTGRES_PASSWORD`
   - `ADMIN_PASSWORD`
   - `CRM_BACKEND=postgres`
   - `STATE_BACKEND=redis`
   - `PANEL_BACKEND=postgres`
5. Check:

```text
https://frunzetravel.kg/health
```

Expected response:

```json
{"status":"ok"}
```

6. Send WhatsApp test messages:
   - to `FrunzeTravel2`: `Хочу тур в Турцию`
   - to `GetVisa`: `Хочу визу в США`

