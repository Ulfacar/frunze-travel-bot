# Project: Frunze Travel Bot

## Identity
- Project type: bot
- Work mode: solo
- Owner/business decision maker: Алан — ведёт проект и разрешает выкатки. Даулет — владелец
  бизнеса и заказчик по турам. Гриша — заказчик по визам (GetVisa). Продуктовые решения по
  деньгам, доступам и политике — только эти люди.
- Verified on / revision: 29.09.2026, ветка `fix/tours-search-quality`, коммит `eef6fb0`
  (рабочее дерево чистое, кроме неотслеживаемых артефактов). Прод на `5b04cc5` — на два
  коммита позади ветки.
- Purpose and users: AI-агент-продавец турагентства в Бишкеке. Принимает клиента в WhatsApp,
  квалифицирует, подбирает туры через TourVisor, консультирует по визам, передаёт «тёплого»
  менеджеру и зеркалит переписку в Bitrix24. Два бренда на одном коде: **Frunze Travel**
  (туры и авиабилеты, +996707660009) и **GetVisa** (визы, +996706660009). Пользователи —
  клиенты в WhatsApp и четыре менеджера (Адеми, Айсина, Медина, Элиза) через админ-панель.
  В боевой эксплуатации с 01.07.2026; считать статистику только с этой даты.
- Current milestone: формального milestone нет. Текущая работа — надёжность сторожей и
  наблюдаемость (ложные тревоги, шум в логах, расход LLM). Ближайшие даты: 30.09 встреча с
  Гришей по Битриксу, 01.10 истекает подписка Wappi по туровым каналам.

## Architecture
- Stack / runtime versions: Python 3.12 (`Dockerfile`: `python:3.12-slim`, локально 3.12.10),
  FastAPI 0.115, uvicorn 0.30, SQLAlchemy 2 (asyncio) + asyncpg, Alembic 1.13,
  PostgreSQL 16, Redis 7, httpx 0.27, pydantic 2.8+ / pydantic-settings, aiogram 3 (Telegram),
  Jinja2 (админка), aiosqlite (тесты). Зависимости — `requirements.txt`, без pyproject.
- Entry points / module map: `app/main.py` (FastAPI, вебхуки и планировщик) — главная точка входа;
  далее по слоям:
  - `app/main.py` — FastAPI: вебхуки `/webhook/{telegram,wappi,bitrix}`, `/health`, роутеры,
    регистрация джоб планировщика.
  - `app/core/orchestrator.py` — вход сообщения → состояние → ответ.
  - `app/core/scheduler.py` — фоновые джобы, тик 300 с, выполняются **последовательно**
    (медленная джоба задерживает остальные — это уже стоило нам дрейфа сторожей).
  - `app/agent/` — LLM-ядро: runner, routing, prompts, validator, facts, tools.
  - `app/funnels/` — три воронки: `tours.py`, `visa.py`, `tickets.py`.
  - `app/channels/` — адаптеры: `wappi.py` (WhatsApp), `telegram.py`, `bitrix_openlines.py`.
  - `app/core/` — ~50 модулей операционной логики: `state`, `flags`, `readiness`, `intercept`,
    `followup`, `schedule`, `stt_guard`, `channel_heartbeat`, `wappi_health`, `balance_guard`,
    `manager_sync`, `sale_check`, `morning_brief`.
  - `app/integrations/crm/` — `bitrix24.py`, `bitrix_mirror.py`, `bitrix_pipeline.py`.
  - `app/integrations/tourvisor/` — `client.py` (XML API), `cards.py`, `quota.py`.
  - `app/admin/` — панель менеджеров (Jinja, Basic-auth, канбан), `app/web/offers.py` — публичные
    страницы подборок `/t/<id>`.
- Data storage and boundaries: PostgreSQL — основные таблицы `conversations`, `messages`,
  `app_flags`, `dialogs`, `contacts`, `deals`, `outbox_jobs`, `bot_errors` (20 таблиц).
  Redis — состояние и защёлки сторожей (`wh:alert_state`, TTL 14 суток). Ключ состояния
  диалога — `bot_id:phone`. Часть словарей живёт только в памяти процесса (`_checked`,
  `_rejected`, `_judged_on`) — переживать рестарт не обязаны.
- Existing conventions: комментарии и докстринги по-русски, с историей инцидента («почему так
  сделано»). Чистая функция решения отделена от сетевого вызова, чтобы детектор можно было
  прогнать на истории без обращения к чужому API. Рантайм-флаги в БД с дефолтом из env;
  всё, что меняет поведение для клиента, включается флагом с дефолтом OFF.
- Related repositories / monorepo scopes: N/A — один репозиторий.

## Commands
- install: `pip install -r requirements.txt` (корень репозитория)
- dev: `uvicorn app.main:app --reload` (корень; нужен `.env` локально)
- test: `python -m pytest tests -q` — **именно `tests`, не корень**: в `runs/` лежат временные
  каталоги, на которых сборка падает по правам на Windows. Сейчас 1754 passed, 4 skipped.
- lint: N/A — линтер в репозитории не настроен (нет ruff/flake8/конфигов)
- typecheck: N/A — mypy не настроен
- build: `docker compose -f docker-compose.yml -f docker-compose.vps.yml --env-file prod.env build app`
- gate (проектная, обязательная перед продом): `python scripts/prod_traps_check.py --diff-base HEAD`
- calibration: `python scripts/alert_replay.py` (тишина каналов),
  `python scripts/watchdog_replay.py` (сбои), `python scripts/run_scenarios.py` (качество диалогов)

## Environments and release
- Local environment/setup and safe fixtures: SQLite через aiosqlite для тестов; Telegram-боты
  как песочница вместо живых WhatsApp-номеров. Тестовый прогон проходит и на SQLite, и на PG16.
- Staging / production identifiers (no credentials): прод — VPS `62.171.185.155`, Ubuntu 24.04,
  каталог `/root/frunze-travel`. Docker compose: `app` (uvicorn на 127.0.0.1:8077) + postgres16 +
  redis7. Наружу смотрит **системный** nginx с Let's Encrypt, домен `frunzetravel.kg`.
  Docker — snap-версия: работает только из `/root` и не читает скрытые файлы, поэтому файл
  окружения называется `prod.env` и лежит вне git. Отдельного staging нет.
- Deployment command/process and owner: `git push prod <branch>`, затем на сервере
  `/root/frunze-travel/scripts/deploy_prod.sh <branch>`. Скрипт бэкапит `prod.env`, ждёт
  `/health` и откатывается, если приложение не поднялось. Руками compose не поднимать; рабочая
  форма — `docker compose -f docker-compose.yml -f docker-compose.vps.yml --env-file prod.env up -d app`
  (пропуск любого из флагов уже приводил к инцидентам). Владелец процесса — Алан.
- Standing authorization / approval boundaries: **постоянного разрешения на деплой нет.**
  Каждая выкатка — по прямому слову Алана; «почини» деплой не разрешает. Правка `prod.env`,
  миграции, рассылки, смена ключей — только с отдельной авторизацией.
- Smoke scenario and expected result: `scripts/smoke_test.py` по проду **не гонять** — он
  создаёт мусорный диалог через вебхук. Вместо него после деплоя обязательна функциональная
  проверка: вызвать изменённую функцию в боевом контейнере и показать вывод
  (`docker compose … exec -T app python -` с коротким скриптом). `/health` доказывает только
  то, что контейнер поднялся.
- Rollback / restore procedure: `/root/frunze-travel/scripts/rollback_prod.sh [commit]`.
  Перед правкой `prod.env` — бэкап рядом (например `prod.env.bak-<дата>-<тема>`).
- CI workflow and required checks: N/A — GitHub Actions нет. Гейты локальные: `pytest tests -q`
  плюс `scripts/prod_traps_check.py --diff-base HEAD`.

## Business rules and security
- Confirmed rules + source/date:
  - Разговаривать бот может в любой день, но **визит в офис назначать только пн–сб**
    (перекрывает «работаем ежедневно» из туровой анкеты; бот однажды записал на воскресенье).
  - Визы: называть только официальный прайс (250$/100€ и т.д.). Депозиты, проценты и любые
    гарантии выдачи запрещены. По «своим» странам консультирует сам, по чужим (Бразилия и пр.)
    сразу отдаёт менеджеру.
  - Цены по турам публикует только админ; клиенту — вилка как приманка в офис.
  - Менеджер перехватил диалог → бот замолкает (`intercept.py`, TTL). Владение диалогом
    закреплённое, перехват чужого запрещён (кроме админа).
  - Сегодняшняя дата инъектится в промпт каждый ход, иначе модель гадает месяц.
  - Из Бишкека реально вылетают Турция, ОАЭ, Мальдивы, Азербайджан; по Египту, Таиланду и
    Кипру TourVisor честно возвращает 0 отелей — этого нельзя объяснять клиенту бюджетом.
  Источник — `CLAUDE.md` и `docs/`, подтверждено на проде 28–29.09.2026.
- Roles, visibility, tenant boundaries: менеджеры видят свои диалоги в админ-панели (Basic-auth
  + cookie-сессия), админ видит все. Разделение по `bot_id` (канал) и владельцу диалога.
  Авторизация проверяется на сервере (`authz_enforce_enabled`), не только в интерфейсе.
- Sensitive data / retention / deletion policy: в базе переписка клиентов, телефоны, расшифровки
  голосовых. Формальная политика хранения и удаления — **UNKNOWN**, вопрос к владельцам.
- Protected areas and irreversible actions: миграции Alembic, `prod.env`, детекторы с порогами
  (ложная тревога обесценивает все остальные), рассылки клиентам, смена ключей, любые записи в
  Bitrix24 заказчика. Общая карточка Открытой линии может содержать нескольких клиентов —
  перезаписывать её целиком нельзя.
- Secret variable names and storage locations only (значений здесь нет и не будет):
  `OPENROUTER_API_KEY`, `WAPPI_TOKEN`, `BITRIX24_WEBHOOK_URL`, `STT_API_KEY`,
  `POSTGRES_PASSWORD`, `SESSION_SECRET`, `WEBHOOK_SECRET`, `ADMIN_PASSWORD`,
  `TOURVISOR_LOGIN`/`TOURVISOR_PASS`, `MANAGERS_TELEGRAM_BOT_TOKEN`. Хранятся в
  `/root/frunze-travel/prod.env` на проде (вне git) и в локальном `.env` (в `.gitignore`).

## Integrations
| Service | Purpose | Secret variable name | Timeout/retry/duplicates | Failure behavior |
|---|---|---|---|---|
| Wappi Pro | WhatsApp: приём и отправка, статус профиля | `WAPPI_TOKEN` | статус 15 с; чтение истории чата 12 с (`wappi_messages_timeout_seconds`); дедуп вебхуков — 2000 id в памяти + `is_own` TTL 15 мин + сверка текста | Каналы отваливаются по QR, и по трафику это не видно. Сторож спрашивает статус профиля, а не считает тишину. `connecting`/`close` при живой авторизации — переподключение, не разлогин (грация 90 мин, флаг ON) |
| Bitrix24 | CRM: лиды, стадии, досье, сделки, зеркало переписки | `BITRIX24_WEBHOOK_URL` | таймаут 20 с; ретрай только на сбой соединения (паузы 1 с, 2 с); таймаут чтения не повторяется намеренно — портал мог запись принять | На `403` программной реакции нет, только лог (у Битрикса это и «нет прав», и лимит запросов). Отдельная реплика в таймлайн при сбое теряется; стадии, досье и продажи догоняются каждые 10 минут |
| TourVisor | Подбор туров (XML API) | `TOURVISOR_LOGIN`, `TOURVISOR_PASS` | квота через `quota.py` | Обязательны `childage1..N`, иначе выдача пустая. Валюта в ответах плавает. Блокировка при запросе с EU-IP |
| OpenRouter | LLM: роутинг Haiku/Sonnet + кэш | `OPENROUTER_API_KEY` | суточный лимит `LLM_DAILY_BUDGET_USD` | Кончились деньги — бот молчит клиентам (так и было 17–22.09, шесть дней, 402). Сторож баланса считает запас в ДНЯХ, порог 7 |
| OpenAI STT | Расшифровка голосовых | `STT_API_KEY` | ~28 голосовых в день | Кыргызского языка в модели нет: 54% кыргызской речи — нечитаемая каша, поэтому `stt_guard` фильтрует доверие к расшифровке |
| Telegram | Уведомления менеджерам, тестовая песочница | `MANAGERS_TELEGRAM_BOT_TOKEN` | — | Мост Telegram → Claude Code не отвечает с 21.08 (409) |

## Verification and continuity
- Representative acceptance scenario: клиент пишет в WhatsApp «хочу в Турцию в октябре, двое
  взрослых» → бот уточняет недостающее, ищет тур через TourVisor, отправляет карточки, ставит
  лиду стадию «Предложение отправлено» в Bitrix24 и пишет досье в карточку; при перехвате
  менеджером замолкает. Проверяется тренажёром `scripts/run_scenarios.py` (судья шумит,
  базлайн 12/20) и симулятором `scripts/sim_tour_card.py`.
- Known baseline failures and technical debt:
  - `pytest` из корня падает по правам на Windows (`runs/`) — гонять `pytest tests`.
  - `prod_traps_check` даёт один предсуществующий ERROR `ANTHROPIC_API_KEY` (не из наших правок)
    и 57 WARN — это фон, не регрессия.
  - Продажи в Bitrix24 не заносятся с 13.06.2026 → конверсия объективно не меряется: в портале
    13 «Подписан», у таргетологов речь о 158 продажах.
  - `profile_health()` требует `app_status == "open"`, поэтому сторож тишины при переподключении
    может снова посоветовать сканировать QR по живому каналу (баг 01.09). Не исправлено.
  - Ночные `403` Битрикса (869 за 20–22.09) — причина UNKNOWN, не повторяется с 23.09.
  - Причина флапа Wappi `open ↔ connecting` — UNKNOWN.
  - Скилл `/protocol` живёт в `.claude/` (в `.gitignore`), на другом устройстве его нет.
- Relevant playbook: ai/playbooks/bot.md
- Active task and handoff: see ai/STATE.md
- Independent reviewer / critical auditor availability: доступны два, и оба использовались 29.09.
  1) агент `codex-reviewer` — Claude Opus, read-only, вызывается Agent tool.
  2) `codex review --uncommitted` / `--base <ветка>` — Codex CLI 0.159.0, модель `gpt-6-astra`,
     `model_reasoning_effort=xhigh`. Свой промпт не сочетается с этими флагами. Его собственный
     прогон pytest даёт на Windows ~160 `PermissionError` — артефакт запуска из корня.
  Для класса CRITICAL в режиме solo независимое ревью обязательно — это выполнимо.
- Business acceptance: UNKNOWN — формальной приёмки владельцами нет. Ближайшая возможность —
  встреча с Гришей 30.09.2026 по работе с Битриксом.

Факты выше сняты с кода, конфигурации и прода 28–29.09.2026. Значения секретов здесь
отсутствуют намеренно. Команды — данные для осмотра перед выполнением, а не разрешение
выполнять их без нужды.
