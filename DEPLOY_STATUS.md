# Frunze Travel Bot: Deploy Status

## LIVE (deployed 2026-06-23)

Развёрнут на собственном VPS (не Coolify — от Coolify отказались, потом клиент купит свой хостинг).

- **Сервер:** `62.171.185.155` (Ubuntu 24.04), SSH `root` по ключу.
- **Путь:** `/root/frunze-travel` (НЕ /opt — там snap-docker не видит файлы).
- **Docker:** snap-версия (Canonical). Работает только из `$HOME` (/root) и не читает
  скрытые файлы → `.env` переименован в `prod.env`, запуск с `--env-file prod.env`.
- **Стек:** `app` (uvicorn, слушает только `127.0.0.1:8077`) + postgres16 + redis7.
  Публичный порт наружу НЕ открыт — наружу смотрит host-nginx.
- **Reverse-proxy + TLS:** системный nginx (`/etc/nginx/sites-available/frunzetravel.kg`)
  проксирует `frunzetravel.kg` → `127.0.0.1:8077`; сертификат Let's Encrypt (certbot,
  до 2026-09-21, автопродление). HTTP→HTTPS редирект включён.
- **DNS:** Cloudflare A `frunzetravel.kg` и `www` → `62.171.185.155` (DNS only / серое облако).

### Проверено вживую (снаружи)

- `https://frunzetravel.kg/health` → `{"status":"ok"}`
- `https://frunzetravel.kg/admin/board/tours` → 401 без авторизации, 200 с Basic-auth
- HTTP → HTTPS 301 редирект
- `POST /webhook/wappi`: эхо `is_me` → skipped; неизвестный profile → unknown_profile

### Wappi (оба профиля авторизованы, webhook указывает на наш домен)

- FrunzeTravel2 (туры) `02a4708d-ec6c`, номер **+996707660009**, оплата до 2026-07-16
- GetVisa (визы) `2f099bc3-478d`, номер **+996706660009**, оплата до 2026-07-17
- `webhook_url = https://frunzetravel.kg/webhook/wappi` у обоих, тип `incoming_message`.

## Команды эксплуатации (на сервере)

```bash
cd /root/frunze-travel
# редеплой после обновления кода:
docker compose -f docker-compose.yml -f docker-compose.vps.yml --env-file prod.env up -d --build
# логи приложения:
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs app -f
# рестарт:
docker compose -f docker-compose.yml -f docker-compose.vps.yml --env-file prod.env restart app
```

## Доступы

- Админка (полная страница со стилями): **`https://frunzetravel.kg/admin`** — логин `admin`,
  пароль в `prod.env` (`ADMIN_PASSWORD`). Сгенерирован при деплое.
  ⚠ `/admin/board/{funnel}` — это HTMX-ФРАГМЕНТ (без `<head>`/CSS), не открывать напрямую.
- `POSTGRES_PASSWORD` / `WAPPI_TOKEN` / `TOURVISOR_*` — в `prod.env` на сервере (chmod 600).

## Осталось

- **Живой ИИ включён ✅** (2026-06-23): `OPENROUTER_API_KEY` прописан в `prod.env`,
  `LLM_MODEL_MAIN=anthropic/claude-sonnet-4.6`, `LLM_MODEL_CHEAP=anthropic/claude-haiku-4.5`.
  Проверено внутри контейнера: `llm_enabled=True`, модель отвечает по-русски.
  (Старые слаги `anthropic/claude-3.5-sonnet` на OpenRouter уже 404 — нужны новые.)
- **Живой тест менеджерами:** написать в WhatsApp на +996707660009 (туры) и +996706660009 (визы),
  проверить карточки в админке и перехват.
- **Bitrix24** (CRM-зеркало) — после теста: `CRM_BACKEND=bitrix24` + webhook/категории/стадии.
- **TourVisor** — активировать XML-поиск (сейчас `Authorisation Error`).
- ⚠ **Отозвать токены, засвеченные в чате:** Cloudflare API token и Coolify token (Coolify больше
  не нужен).
