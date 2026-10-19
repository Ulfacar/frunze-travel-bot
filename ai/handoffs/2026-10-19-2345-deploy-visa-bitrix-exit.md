# HANDOFF: 2026-10-19-2345 — деплой ветки `feat/visa-bitrix-exit` на прод с миграцией БД 0009→0043

- STATUS: DONE (release; поведение для клиентов и менеджеров не изменилось — все новые флаги OFF)
- CLASS / MODE: CRITICAL (C — миграция боевой базы) / solo; независимого ревью релиза не было (решение Алана
  «сами сделайте» → «делайте по своим лучшим рекомендациям» → «продолжайте», 19.10)
- Task and project: `docs/plan-bitrix-exit.md` §7 (пилот виз 27.10), `ai/PROJECT.md`
- Scope / branch / revision: `feat/visa-bitrix-exit`, прод-коммит **`773eb46`** (от `550237b` + этот коммит:
  compose-дефолты 27 настроек KG/CRM и список таблиц в тесте миграций). Прежний прод `464a799`.
- Completion target: release

## Outcome and files

На проде теперь код всех блоков B2a/B2b/B2c/B3/B5 и доменная схема `e6_sop_review_evidence_0043`
(76 таблиц, было 25 на `e2_payments_0009`). Флаги `admin_workday_enabled`, `service_cases_enabled`,
`panel_send_media_enabled`, `panel_media_view_enabled`, `pilot_reply_queue_enabled`, `pilot_reply_alert_enabled`,
`sale_by_full_payment_enabled`, `sale_check_panel_contract_enabled`, `admin_kg_entry_enabled`,
`crm_standalone_enabled`, `admin_new_look_enabled`, `admin_focus_enabled` — все **False** (проверено печатью
`settings` внутри боевого контейнера). Политики KG пустые (= запрет).

Изменённые файлы этого коммита: `docker-compose.yml` (+30 строк env-дефолтов), `tests/test_alembic_domain_migration.py`
(+9 таблиц 0036–0043 в `DOMAIN_TABLES`). Кода приложения коммит не меняет.

Серверные артефакты: дампы `/root/backups/frunze-before-0043-20261019-193324.dump` (боевой, перед миграцией) и
`/root/backups/frunze-before-0043-rehearsal-20261019-133547.dump` (репетиционный); `/root/deploy_1910.sh`
(этапы dump/migrate/verify_db/deploy/cleanup); `/root/migrate-live-*.log`, `/root/migrate-rehearsal-1910.log`.
Временные `frunze_restorecheck`, образ `frunze-migrate:1910`, клон `/root/frunze-next` удалены.

**Важно для следующих деплоев:** `scripts/deploy_prod.sh` миграции НЕ запускает. Для этой ветки они были
обязательны (0010/0022/0043 добавляют колонки в `calendar_tasks`, без них ломается календарь). Порядок,
который сработал: дамп → образ из отдельного клона → `docker run --rm --network frunze-travel_default
-e ALEMBIC_DATABASE_URL=postgresql+asyncpg://postgres:<pw>@db:5432/frunze <image> alembic upgrade head` при
работающем старом приложении (миграции аддитивные) → `deploy_prod.sh`.

## Evidence

| Claim / criterion | Command or scenario | Environment / revision | Result | Limitation |
|---|---|---|---|---|
| Ловушки прода | `python scripts/prod_traps_check.py --diff-base 464a799` | локально, 773eb46 | 28 ERROR → **1 ERROR** (`SET_BUT_NOT_DELIVERED: ANTHROPIC_API_KEY`, базовый, не из дифа), 57 WARN | базовый ERROR не закрыт |
| Compose-дефолты парсятся | `Settings(_env_file=None)` с env = дефолтам; `docker compose … config` на сервере | локально + сервер | PASS: dict → `{}`, list → `[]`, `kg_actual_anchor_policy` → `None` | — |
| Тест миграций | `pytest tests/test_alembic_domain_migration.py` | локально, SQLite | 10 passed, 2 skipped (было 2 failed с 14.10) | — |
| Полный pytest | 12 кусков по 35 файлов (`-p no:cacheprovider`), см. `pytest-full*.log` в scratchpad сессии | локально, SQLite, ветка 773eb46 (кусок 1–5 на 550237b, те же файлы) | куски 7, 8, 10: **2058 passed, 0 failed**; остальные — падения только базового PDF-блока/артефактов/даты (ниже) | PDF-блок с восстановленным артефактом догонялся фоном, итог не дождался |
| Падения — не регрессии | те же тесты в `git worktree` на `main` (64d5e13): `test_entry_notifications` ×4, `test_entry_quarantine`, `test_pdf_engineering_progress`, `test_work_process_migration`, `test_standalone_crm` ×3 | локально | FAIL одинаково на `main` | — |
| Флап | `pytest tests/test_entry_storage.py` ×2 | локально | 63 passed, 63 passed (в куске падал под нагрузкой) | — |
| Дамп и восстановление | `pg_dump -Fc` → `pg_restore` в `frunze_restorecheck` | сервер | 25 таблиц; 2514 tasks / 2967 contacts / 4181 conv / 52812 msgs = живой базе | — |
| Репетиция миграции | образ 773eb46, `alembic upgrade head` на `frunze_restorecheck` | сервер, PG16 | 34 шага, 8,9 с, `0043`, 76 таблиц, строки целы | без нагрузки |
| Боевая миграция | `bash /root/deploy_1910.sh dump && migrate && verify_db` | сервер, живая база, старое приложение 464a799 работает | 34 шага, **13,3 с**, `0043`, 76 таблиц, 2514/2967/4181/52824 до и после; `calendar_tasks` получила `service_case_id, ticket_segment_id, claimed_at, claimed_by` | `lock_timeout` не ставился |
| Старое приложение на новой схеме | `curl localhost:8000/health` между миграцией и деплоем | сервер | 200 ok | окно ~1 мин |
| Деплой | `scripts/deploy_prod.sh feat/visa-bitrix-exit` | сервер | «было 464a799 → стало 773eb46», образ собран, контейнер пересоздан, `/health` ok, rc=0 | PROD_HEALTHY |
| **PROD_FUNCTIONALLY_VERIFIED** | python внутри контейнера: логин учёткой из `MANAGERS`, GET панели | сервер, 773eb46 | `/admin`, `/inbox`, `/calendar`, `/buyers`, `/morning`, `/stats`, `/search`, `/board/visa`, `/board/tours` — **200**; `/admin/work`, `/focus`, `/overdue`, `/kg-entry/knowledge` — **404** (флаги OFF); реальная переписка открывается 200 | один аккаунт |
| Внешние адреса | `curl` с ПК | интернет | `frunzetravel.kg/health` 200, `crm.frunzetravel.kg/admin/login` 200, `/admin/work` 401 (аноним), `/webhook/{wappi,telegram,bitrix}` 405 на GET (маршруты живы) | — |
| Логи после рестарта | `docker compose logs --since 6m` фильтр traceback/error | сервер | новых ошибок 0 (кроме базового Wappi 401 по турам) | 6 минут наблюдения; входящих вебхуков за это время 0 — ночь воскресенья |
| Флаги в БД | `select … from app_flags` | сервер | 541 строк, `bots_enabled:getvisa=t`, `bots_enabled:frunze_tours=t`, `sale_check_enabled=t` — без изменений | — |

## Review and remaining gates

Независимого ревью/аудита релиза не было; B3 имел ревью р.2 APPROVE и аудит р.3 GO на коммит (15.10). Этот
коммит — только compose и тест. Решение о выкатке — Алана (19.10). Включение флагов к пилоту — отдельные
решения, по одному тумблеру через `/admin/system`.

## Unknowns, risks, and baseline failures

- Полный прогон на точном дереве 773eb46 не получен одним куском: куски 1–5 шли на 550237b (тот же код
  приложения, диф только compose и тест), куски 6–12 — на 773eb46. PDF-блок (53 файла) с восстановленным
  `runs/specialist-source.pdf` догонялся фоном, результат не в этом handoff.
- Базовые падения (воспроизведены на `main`): PDF-блок без артефактов `runs/specialist-source.pdf` (= PDF Гриши,
  sha `141b9e1e…`, восстановлен из Desktop) и `release-source.pdf` (нет); `test_crm_bot_mode`/`test_standalone_crm`
  требуют отсутствия корневого `.env` (у Алана есть) — гонять из чистого worktree; `test_pdf_engineering_progress`;
  stale-тесты паритета `test_entry_deadline_tasks_migration` (ревизия 0022 vs колонка `expected_at` из 0043) и
  `test_work_process_migration` (0040 vs таблицы 0041–0043); `test_admin_kg_deadlines` падает только 19.10
  (штамп даты на странице).
- Миграция шла одной транзакцией без `lock_timeout` (замечание пре-аудита B1); прошла за 13 с без ожиданий.
- Входящих сообщений после рестарта за окно наблюдения не было — приём вебхука подтверждён только маршрутом
  (405 на GET) и логами до рестарта. Проверить утром по `last_inbound_seconds_ago`.

## Found out of scope

- 🔴 Туровые профили Wappi `frunze_tours` (FrunzeTravel2) и `frunze_tours_sezim` (FrunzeTravel) **не
  авторизованы с 17.10 ~16:40**: сторож пишет `authorized=False app_status=connecting`, API отдаёт 401
  (553 раза за сутки), сообщений по турам 0 с 17.10 16:43. Визы живы (30 клиентских за сутки). Нужен
  кабинет Wappi: QR или оплата. Сообщено Алану.
- `bots_enabled=f` глобально в `app_flags` с 24.06 — боты работают по ключам `bots_enabled:<bot>=t`.
- Токены Cloudflare (14.10 «Frunze new», 16.08 «Edit zone DNS») не отозваны; пароли менеджеров
  (`/root/panel-passwords-20261014.txt`) ждут передачи.

## Next action / resume

1. Утром проверить `frunzetravel.kg/health` → `last_inbound_seconds_ago` и логи за ночь.
2. К пилоту 27.10 включать тумблеры по одному в `/admin/system`: `admin_workday_enabled` → `service_cases_enabled`
   → `panel_send_media_enabled` (+S1 на тестовом номере) → `pilot_reply_queue_enabled` → `pilot_reply_alert_enabled`.
   `sale_by_full_payment_enabled` и `sale_check_panel_contract_enabled` — после решений S8 и «один/все диалоги».
3. B4 (импорт истории Bitrix) не начат.
4. Откат кода: `rollback_prod.sh 464a799` (старый код работает на схеме 0043, колонки аддитивные). Откат схемы —
   только восстановление из `frunze-before-0043-20261019-193324.dump`, downgrade не гонять.
