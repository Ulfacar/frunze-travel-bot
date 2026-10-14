# B1 — репетиция на копии боевой БД (14.10.2026)

Builder: Claude. Сервер 62.171.185.155, каталог `/root/frunze-b1-rehearsal` (0700), docker-сеть
`frunze-b1-rehearsal` с `--internal` (без выхода в интернет). Боевые контейнеры бота не трогались.
Исходные данные — ночной бэкап `/root/backups/frunze_daily_20261013_0320.dump` (4 013 058 байт).
К живой БД бота обращений не было.

| Шаг | Команда / сценарий | Результат |
|---|---|---|
| Восстановление | `pg_restore --no-owner` в `postgres:16-alpine` (`frunze-b1-db`) | схема `e2_payments_0009`; conversations 4032, messages 49955, calendar_tasks 2343 |
| Отпечатки до | `count(*)` + `md5(string_agg(row::text ORDER BY pk))`: conversations, messages, audit_log, app_flags, contacts, assignments, calendar_tasks (ключевые колонки) | сохранены в `before.txt` |
| Миграции | образ R9 `frunze-crm:10dc6b02b0909c3042b0`, `alembic upgrade head`, `ALEMBIC_DATABASE_URL` | **34 шага, 8,19 с**, `e6_sop_review_evidence_0043`, 76 таблиц. Первая попытка без `ALEMBIC_DATABASE_URL` миграции не выполнила (env.py отказал) — не засчитана |
| Отпечатки после | тот же запрос, сравнение отсортированных строк | **7/7 идентичны** — миграции не изменили ни одной существующей строки |
| Бот `913feab` на мигрированной копии | прод-образ `sha256:d7db9d47…`, `STATE_BACKEND=memory`, без токенов, во внутренней сети | `/health` ok, restarts 0, ошибок, кроме недоступности внешних сервисов, нет |
| Запись кодом `913feab` | `store.add_message` / `update_meta` / `add_audit`; `CalendarTaskService.create(kind="call")` | legacy: ok (msg 50088); calendar_tasks: ok (id 2345), новые колонки `service_case_id`/`claimed_by` = NULL. Первая попытка с видом `callback` — DomainError (вида нет), не дефект |
| Образ B1 | снимок `b1-r1` (база `779ed81`, 26 файлов, сверены с рабочим деревом), `crm_release_bundle.py` → release `a1ff389d552c2352d296`, 422 файла сверены на сервере, `docker build` | `sha256:d80c7228a82707290eb4ff3a127a7f7d10a9edd02fe7795e6ac98dfefca1b37d` |
| Роль БД | `scripts/crm_bot_role.py` → psql | `rolsuper/createdb/createrole = f/f/f`; запись только в 8 таблиц (assignments, audit_log, calendar_task_events, calendar_tasks, contact_identities, contacts, conversations, messages) |
| Негативные SQL под `frunze_crm` | DELETE messages, UPDATE app_flags, INSERT service_payments, CREATE TABLE, DROP messages, TRUNCATE audit_log | все **отказ** (permission denied / must be owner); `b1_probe` не создана |
| Старт CRM `CRM_DATA_MODE=bot` | `--read-only --tmpfs /tmp --cap-drop ALL --pids-limit 128`, отдельный Redis с ключом диалога, отправка OFF, без Wappi-токена | готовность пройдена (схема, переписка, Redis), healthy |
| HTTP-сценарий в контейнере | login medina → GET /admin → GET переписки → takeover; eliza takeover; запрещённые POST; аноним | 303 / 200 / 200 (переписка видна) / `claimed`; eliza `denied`; flags, resend, send (выкл), suggest, intake, cards — 404; аноним — 401 |
| Перехват в общий Redis | `GET frunze:dialog:<key>` | `intercepted=True`; БД: `assigned_to=medina`, `intercepted=t`, активное назначение medina; audit `medina takeover` |

## Не проверено на этой репетиции
- Реальная отправка в WhatsApp из CRM и эхо на боте: нужен тестовый номер и выход в интернет. Это
  отдельный шаг до включения `CRM_BOT_SEND_ENABLED`.
- Миграция под нагрузкой работающего бота и `lock_timeout`: на копии нагрузки не было.
  ACCESS EXCLUSIVE на `calendar_tasks` держался в пределах общих 8,19 с.
- TLS / nginx / настоящий домен для режима bot.

## Остатки на сервере (удалить после решения)
Контейнеры `frunze-b1-db`, `frunze-b1-bot`, `frunze-b1-redis`, `frunze-b1-crm`, сеть `frunze-b1-rehearsal`,
том `frunze-b1-rehearsal-pgdata` (копия персональных данных клиентов!), каталог `/root/frunze-b1-rehearsal`
с паролями 0600. Образ `frunze-crm:a1ff389d552c2352d296`.

---

## Раунд 2 — исправления по ревью (кандидат r3)

Кандидат r3: снимок `%TEMP%\crm-accept\b1-r3` (база `779ed81`, 30 файлов), release
`c8f6766deceb5ecab7dd`, 422 файла сверены на сервере, образ
`sha256:34f11489722bccdacfd746045e3ce4111eeb6d3f65fe62bcbb156caeb6a76d27`. Стенд — та же изолированная
копия; отправка ВКЛЮЧЕНА с фиктивным токеном, выхода в интернет нет.

| Проверка | Результат |
|---|---|
| Все разрешённые маршруты под ролью `frunze_crm` на PG16 (`routes_flow.py` в контейнере) | GET index/inbox/search/board/calendar/stats/conversation — 200; takeover — `claimed`; stage/outcome/task create — 200; calendar quick create/snooze/reschedule/complete/cancel — 303; send — `failed` (нет выхода к Wappi, ожидаемо); повтор с тем же ключом — `duplicate`; reassign/release админом — 200; direction у менеджера — 403 (полный админ, by design) |
| `permission denied` в логе CRM | **0** |
| Traceback в логе CRM | 1 цепочка (2 строки) — ошибка отправки в Wappi без выхода в сеть, ожидаемо |
| Браузер Playwright, настоящий CSP CRM, через туннель `crm.invalid` (`runs/crm-b1-browser/check.py`, `result.json`) | ключ в форме (32 hex), уходит в POST, двойной клик → **1** POST, после ответа поле очищено и ключ сменён; опрос идёт без фокуса и **0** при фокусе в поле; CSP-нарушений 0, ошибок консоли 0, HTTP-ошибок 0, внешних запросов 0 |
| Атомарность ключа на PG16 (`tests/test_crm_bot_mode_postgres.py`, локальный кластер 55971) | 8 одновременных запросов → 1 строка, 1 «создано». Мутант без advisory-блокировки → **8 строк, тест падает**: тест чувствителен. Первая версия теста была нечувствительна (гонку закрывало открытие соединений) — исправлено прогревом пула |
| Хотфикс бота (`hotfix/echo-dedupe`, на базе `913feab`) | эхо-тесты 51/51; полный прогон: чистый `913feab` 2246 passed / 1 failed против хотфикса 2250 passed / 1 failed, **набор падений совпадает** (`test_facts_live_errors::test_still_reads_a_plain_request` — датозависимый, есть и на чистом коде) |

---

## Раунд 3 — кандидат r4 (после ревью r2: APPROVE с минорами)

Исправлено: `duplicate` очищает поле и меняет ключ; перехват и назначение ставятся только при реально
созданном сообщении (поздний повтор не глушит бота заново, тест
`test_duplicate_retry_does_not_reintercept_released_dialog`); скрипт роли — только через pipe в psql.
Известное ограничение (не исправлено, решение): падение процесса между захватом ключа и вызовом
Wappi оставляет `pending`, повтор отдаёт `duplicate` — автоповтор опаснее (сообщение могло уйти).

r4: снимок `%TEMP%\crm-accept\b1-r4` (база `779ed81`, 30 файлов), release `a90bea9ffd9ec0de2b32`,
422 файла сверены, образ `sha256:c3ee75f0752c636fca2a40767310932cf34b1bdf17906de4ad5e8e67b217141c`.

| Проверка на r4 | Результат |
|---|---|
| Тесты снимка (bot mode, role, R9 standalone ×4, chat redesign, new look) | 118 passed |
| Старт CRM на копии под `frunze_crm` | healthy — стартовая проверка прав роли (rolsuper/…/CREATE public) выполнена и пройдена на PG16 |
| Все разрешённые маршруты под ролью | как в r3; `permission denied` — **0** |
| Браузер под CSP CRM | ключ, 1 POST на двойной клик, поле очищено, ключ сменён; опрос 2/0; CSP 0, консоль 0, HTTP-ошибок 0, внешних 0 |
