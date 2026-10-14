# Current state — 14.10.2026

История (полный прежний STATE, без потерь): `ai/STATE-history.md`.

## Где мы
- Ветка `fix/tours-search-quality`, `main` = merge `338b611` (на GitHub, 14.10). Прод бота — `913feab` (ветка не выкатывалась).
- **Бот** (frunze-travel app/db/redis) работает. 13.10 чужая правка nginx `frunzetravel.kg` резала вебхуки Wappi (405, ~1.5 ч) — маршруты бота `/webhook/ /admin /t/ /health` возвращены; проверено живым сообщением.
- **Отдельная CRM** https://crm.frunzetravel.kg — выкачена 14.10 (коммит `d5886b7`, release `10dc6b02b0909c3042b0`, образ R9 `sha256:4f4afd16…`). Пустая рабочая БД `frunze_crm`, только ручной ввод, без связи с ботом/WhatsApp. Вход `alan`, пароль `/root/frunze-crm/first-login.json`. Откат и доказательства — `ai/STATE-history.md` (запись 14.10) и `docs/standalone-crm-operations.md`.
- **PDF въездного направления**: 99/100, открыт только J05 (люди: сотрудник, владельцы, разрешение пилота). Новых задач по въездному направлению не начинать без слова Алана.
- Bitrix: учёт продаж = лиды CONVERTED через `read_back_once` (единственный автоматический). Визовые менеджеры отвечают из Открытых линий Bitrix. Импорта из Bitrix нет.

## Активная работа (14.10, по брифу Алана) — НЕ закоммичено, без деплоя/пуша
1. `read_back_once`: ранний выход при пустом `bitrix24_webhook_url` + рубильник `bitrix_read_back_enabled` (дефолт ON — глобального `bitrix_pipeline_enabled` на проде нет, гейт по нему остановил бы учёт продаж). Файлы: `app/integrations/crm/bitrix_pipeline.py`, `app/config.py`, `app/admin/router.py`, `tests/test_read_back_guard.py`.
2. План отключения Bitrix (E4-02..E4-04, MIGR-2..4) — только план, `docs/plan-bitrix-exit.md`. Дата отключения — спросить у Алана.
3. `docs/modules-roadmap.md` — статусы по факту кода; этот файл и `ai/STATE-history.md` — гигиена контекста.
4. Черновик сообщения Грише — `docs/draft-message-grisha.md`, НЕ отправлять.

## Известные долги
- `tests/test_admin_shell_and_direction_split.py::test_internal_links_point_to_existing_routes` красный с `d5886b7`: статический скан не видит условие `{% if standalone_crm %}` у ссылки `/admin/intake` в `base.html`. Ссылка в боте не показывается; тест ложно-красный.
- Cloudflare-токен «Frunze new» попал в чат — удалить.
- Тестовый том CRM `frunze-crm-check_crm_pgdata` и бэкап `audit-recovery-r8` на сервере сохранены — решить, удалять ли.

## Решения Алана 14.10 (Bitrix-exit)
CRM = crm.frunzetravel.kg; продажа = полная оплата; импорт — вся история; пилот — визы, ведёт Гриша; Bitrix оплачен на откат. Срок — вариант Б: визы в CRM к 31.10, Bitrix для виз только чтение до конца ноября, туры и полный разбор истории — ноябрь. План и расписание: `docs/plan-bitrix-exit.md` §5–7.

## ВЫКАЧЕНО 14.10 ~05:50 Бишкек — «короткий путь» (решение Алана вместо B1 r4)
- `crm.frunzetravel.kg` → панель бота (только `/admin`, остальное 404; бэкап nginx `/root/crm.frunzetravel.kg.nginx.bak.20261014-014947-before-bot-panel`). Отдельная CRM R9 остановлена (том `frunze-crm_crm_pgdata` сохранён).
- Бот на проде: ветка `hotfix/panel-safety`, коммит `464a799` (от `913feab`): «Повторить» только своё failed + владелец + блокировка; проверка владельца при сбое запрещает send/claim; дожим/FAQ/тумблеры ботов и STT — только полный админ. Ревью ×2, аудит патча GO; полный прогон = набор падений `913feab`; гейт ловушек пройден.
- PROD_FUNCTIONALLY_VERIFIED: medina новый пароль 303 / старый 401; faq/followup/toggle 403; туровый диалог 404; resend клиентского сообщения `denied`; по HTTPS medina видит 2154 визовых, 0 туровых; вебхуки 200.
- Пароли medina/eliza/grisha сменены (18 симв.), файл `/root/panel-passwords-20261014.txt` (0600) — Алан передаёт сам. Бэкап prod.env в `/root/backups/`.
- Переход менеджеров с Bitrix — с пилота 27.10 (до этого только смотрят). `--proxy-headers` не включали (решение). Откат: nginx из бэкапа → `rollback_prod.sh 913feab` (именно в этом порядке).
- B1 r4 (CRM на данных бота) отложен до обновления бота в ноябре; материалы в `ai/reviews/2026-10-14-b1-*`.

## B1 — CRM на данных бота (ОТЛОЖЕН до ноября; не закоммичено)
- Кандидат r4 (release `a90bea9ffd9ec0de2b32`): ревью APPROVE, аудит GO локально / NO-GO прод (P1–P6, S1–S3). Всё в `ai/tasks/2026-10-14-b1-crm-on-bot-data.md` и `ai/reviews/2026-10-14-b1-*`. Остатки репетиции с копией ПД на сервере: `/root/frunze-b1-rehearsal`, том `frunze-b1-rehearsal-pgdata`, контейнеры `frunze-b1-*` — удалить.

## Следующий шаг
Решения Алана по P1/P2/P5 (окно миграции, допустимая потеря данных, допуск менеджеров), затем замеры P4, миграция с таймаутами по `…-b1-final-audit.md` §Required. Отправка — только после теста на номере (S1).
