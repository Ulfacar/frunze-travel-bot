# Current state — 20.10.2026

История (полный прежний STATE, без потерь): `ai/STATE-history.md`.

## Прод (не трогать без слова Алана)
- **19.10 ~23:40 Бишкек: бот переведён на ветку `feat/visa-bitrix-exit`, коммит `773eb46`, БД мигрирована
  `e2_payments_0009` → `e6_sop_review_evidence_0043` (76 таблиц).** Все новые флаги OFF — поведение для
  менеджеров и клиентов не изменилось (`/admin/work` 404). Handoff:
  `ai/handoffs/2026-10-19-2345-deploy-visa-bitrix-exit.md`. Дамп до миграции:
  `/root/backups/frunze-before-0043-20261019-193324.dump`. Откат кода `rollback_prod.sh 464a799` (старый код
  живёт на новой схеме), схему не даунгрейдить.
- **20.10 ~00:40 по слову Алана («делай») включены тумблеры показа** через `/admin/flags/*` (аудит есть):
  `admin_new_look_enabled`, `admin_chat_redesign_enabled`, `admin_focus_enabled`, `admin_workday_enabled`,
  `service_cases_enabled`, `panel_send_media_enabled`, `pilot_reply_queue_enabled`. В боевой базе заведены
  9 продуктов ТЗ (`seed_products`, актор `alan`): процесс опубликован у `tour_package` (сидер) и `visa_usa`
  (9 этапов по ТЗ §7.4, версия 1 неизменяема). Остальные 7 продуктов без процесса — в формах договора не
  показываются. KG-блок (`admin_kg_entry_enabled`) и `pilot_reply_alert_enabled`, `sale_by_full_payment_enabled`,
  `sale_check_panel_contract_enabled` — по-прежнему OFF. Откат показа — те же тумблеры OFF.
- **20.10 ~01:20: редизайн панели v2 на проде, коммит `b2700c9`** (после `3e2cf50`, фикс логина).
  Дизайн-система `docs/design-system/frunze-panel/MASTER.md` (скилл `ui-ux-pro-max`, стиль
  Data-Dense Dashboard, navy `#1E40AF` / тёмная `#8FB4FF`, системный шрифт, иконки `_icons.html`).
  Handoff: `ai/handoffs/2026-10-20-0120-panel-redesign-v2.md`. Откат вида: тумблер
  `admin_new_look_enabled` OFF (старый вид байт-в-байт) или `rollback_prod.sh 3e2cf50`.
- `deploy_prod.sh` миграции не запускает — ручной шаг (порядок в handoff).
- 🔴 Туровые профили Wappi не авторизованы с 17.10 (401, сообщений по турам 0) — кабинет Wappi, Алан в курсе.
- `crm.frunzetravel.kg` → панель бота (только `/admin`, остальное 404). Отдельная CRM R9 остановлена, том сохранён. Откат nginx: бэкап `/root/crm.frunzetravel.kg.nginx.bak.20261014-014947-before-bot-panel`.
- Пароли medina/eliza/grisha сменены 14.10, файл `/root/panel-passwords-20261014.txt` (0600) — Алан передаёт сам.
- Учёт продаж сейчас: `read_back` из Bitrix (рубильник `bitrix_read_back_enabled`, ON) + вечерняя ссылка sale_check.

## Цель (бриф Алана 14.10, «короткий путь»)
К пилоту виз 27.10 визовые менеджеры целиком работают в панели бота без Bitrix: текст и файлы, очередь ждущих, уведомление, продажа = полная оплата. К 31.10 Bitrix для виз — только чтение. План — `docs/plan-bitrix-exit.md` §7.

## Работа сейчас — ветка `feat/visa-bitrix-exit` (от `main`), только локальные коммиты, без push/деплоя
Блоки: 0 контекст → B2a файлы → B2b очередь ждущих → B2c уведомление → B3 продажа=полная оплата (CRITICAL) → B4 импорт на фикстурах → B5 репетиция «Bitrix выкл» → материалы к пилоту → закрытие. Всё новое — флаги OFF.

Сделано к 15.10: B2a, B2b, B2c, B5, материалы к пилоту (коммиты до `990a3d9`).
**B3 — закоммичен `9438f1f`** + `c8673a6` (ревью р.2 APPROVE, аудит р.3 GO на коммит; PG не гонялось).
Полный `pytest tests` 15.10 кусками по файлам: кусок 1/4 (102 файла) — 1255 passed, 13 failed, из них
12 — чужой хвост, падают так же на базе `990a3d9` (PDF-блок `test_admin_actual_dates*`,
`test_admin_operator_sop`, `test_conditional_deadline_legacy_upgrade`, 2× alembic); 1 — регрессия B3
(hex-цвета в `case.html`) → починена `c8673a6`. Куски 2–4 (308 файлов) — **UNKNOWN**: прогон убит ОС
по памяти, без просьбы Алана не перезапускать. Handoff:
`ai/handoffs/2026-10-15-1500-b3-sale-full-payment.md`.
Флаги `sale_by_full_payment_enabled`, `sale_check_panel_contract_enabled` (OFF). Решение Алана 15.10
(S6): возврат после продажи `won` не снимает. Открыто для Алана: должна ли вечерняя ссылка ставить
`won` без полной оплаты (S8); один диалог или все при продаже.
B4 (импорт истории Bitrix) — не начат.

## Решения Алана (14.10)
CRM = панель бота на crm.frunzetravel.kg; продажа = полная оплата (записано в ТЗ §20 и handover); импорт — вся история; пилот — визы, ведёт Гриша; переход менеджеров — с 27.10; тумблеры ботов/STT — только админ; `--proxy-headers` не включаем; Bitrix оплачен на откат.

## Отложено
- B1 (CRM на данных бота, r4): ревью APPROVE, аудит GO локально / NO-GO прод. `ai/tasks/2026-10-14-b1-crm-on-bot-data.md`, `ai/reviews/2026-10-14-b1-*`. Образ `frunze-crm:a90bea9ffd9ec0de2b32` на сервере.

## Известные долги
- Тесты условных сроков краснели по календарю после 13.10 10:00 UTC — фикстура часов починена (`ebca10a`).
- `test_alembic_domain_migration` — 2 падения в полном прогоне 14.10, не разобраны; 15.10 воспроизведены
  на базе `990a3d9` вместе с 10 падениями PDF-блока (`test_admin_actual_dates*`, `test_admin_operator_sop`,
  `test_conditional_deadline_legacy_upgrade`) — baseline, не из ветки.
- Реальная отправка из панели на тестовый номер (S1) не проверялась.

## Следующий шаг
Блоки очереди по порядку; итог — handover `ai/handoffs/2026-10-14-*-visa-bitrix-exit.md`.
