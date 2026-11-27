> Приложение к `docs/crm-chronology.md`. Собрано 27.11.2026 агентом (Claude, отдельный контекст, только чтение) и проверено ведущим выборочно. Поправка: `service_cases_enabled` включён 19.10 по `app_flags.updated_at` (здесь местами 20.10 — это ночь 19→20.10 по STATE).

# B. Археология git: хронология CRM, 01.08–27.11.2026

Режим: только чтение. Источник — `git log --all` (509 коммитов с 01.08; даты — author date, +0600),
история `app/config.py`, `ai/STATE.md` (1684 строки, записи с 20.10 по 27.11), `ai/STATE-history.md`
(до 14.10), `ai/handoffs/*`, `ai/tasks/*` (74 файла), `docs/*`. Рабочее дерево не трогал.
Неотслеживаемый `docs/sources/2026-11/` (5 файлов, перенесён 27.11 кем-то параллельно) использован
только как вторичный источник и помечен «[sources, untracked]».

Ветки: рабочая `feat/owner-answers-2026-11-05` (= origin, `1e42c7c`). В неё влиты `main`/`origin/main`
(`64d5e13`, 14.10), `origin/feat/visa-bitrix-exit` (`f0eb438`), `origin/claude-pm/integration`
(`9712080`, 30.10), `origin/hotfix/panel-safety` (`464a799`). НЕ влиты:
`origin/feat/reports-conversion-2026-11-05` (+2: `1a69b72` черновик отчётов конверсии, `107b785`),
`origin/claude-pm/hotfix-menu` (+2: `2c0dee5`, `3019e31` — те же правки меню ⋮ есть в HEAD как
`cee00fa`/`f13f2ec`), `origin/hotfix/echo-dedupe` (+1: `81a31bd`, для отложенного B1),
`origin/fix/tours-search-quality` (+1: `b799d30`, docs).

Коммитов по неделям (ISO): W32 20 · W33 17 · W34 29 · W35 1 · W36 1 · W37 44 · W38 9 · W39 9 ·
W40 21 · **W41 102** · W42 58 · W43 53 · **W44 75** · W45 8 · W46 55 · W47 2 · W48 5.

---

## 1. Хронология по неделям

### W32, 03–09.08 — голосовые, сторожа каналов
- STT: `257cc1a` (голосовые идут текстовым путём), `475e2f7` (метрики, автоотключение), `20be79b`
  (stt_guard v1, режим наблюдения). ТЗ `docs/task-stt-guard-v1.md`.
- Сторож каналов: `568bd9a` (v1, 06.08), `86b9325` (v2, ТЗ `docs/task-channel-heartbeat-v2.md`),
  `271921d` (v3 — спрашивает Wappi, ТЗ `docs/task-wappi-health-v3.md`), `fe57afa`, `4cb6c60`, `430e4b1`.
- Bitrix: `2a2db0c` бот пишет в карточку менеджера; `14c3dfc`, `6e6aaf2` ссылки в карточку.
- Туры: `cb7f427` срок/бюджет кодом; `2f2eec2` график приёма — правило в коде.
- Процесс: `e67e7b0` «Веном v2», гейт до работы, `prod_traps_check`.
- Флаги (config.py): `instant_handoff_catchup_enabled`=True (`c2ce01c`), `stt_enabled`=False,
  `media_capture_enabled`=True (`257cc1a`), `stt_public_enabled`=False (`475e2f7`),
  `stt_guard_enabled`=True (`20be79b`), `channel_heartbeat_enabled`=True (`568bd9a`),
  `wappi_health_enabled`=True (`271921d`).

### W33, 10–16.08 — карточки туров, деплой скриптом
- `7409d44` подборка туров карточками + страница `/t/` (ТЗ `docs/task-tours-cards-v1.md`);
  `abda525` тумблер «бот пишет в карточку менеджера» (ТЗ `docs/task-bitrix-card-link-fix.md`).
- `26f6f0b` реплики бота видны в Контакт-центре (`bot_id=external_api`).
- `28e5ff6` **прод стал git-checkout, деплой/откат одной командой** (15.08).
- `49417d2` TourVisor по https. Марсель: `4907091`, `33ce74c`, `e4b4bc7` («у Марселя не будет Битрикса —
  наша панель для него единственное рабочее место» — первый зародыш идеи своей панели как рабочего места).
- Флаги: `tours_cards_enabled`=False (`abda525`).

### W34, 17–23.08 — бот ведёт карточку Bitrix, «сдача» 21.08
- `e4a4743` бот ведёт карточку до подтверждения менеджером (ТЗ `docs/task-bitrix-lead-pipeline.md`,
  заказчик Даулет — «учёт в конце месяца»); `9474586`, `b156a3d`, `ff4b3ae` досье/продажа в воронке
  (ТЗ `docs/task-bitrix-dossier-live.md`); `abdf047`, `e6f7476` факты тура (ТЗ `docs/task-tour-facts.md`).
- `9ef1f81`, `99a798a` канбан по фактам; `5ab70ac` досье при перехвате + алерты заказчику
  (ТЗ `docs/task-dossier-and-owner-alerts.md`); `06c8506` алерты о деньгах/каналах.
- `4e4b4d6`, `e239fa3` (19.08) — CLAUDE.md и ТЗ в репо. Сдача 21.08 (`docs/project-journey.md:105`).
- Флаги: `bitrix_pipeline_enabled`, `bitrix_autodeal_enabled` (`e4a4743`), `tour_facts_enabled`
  (`abdf047`), `service_notes_shield_enabled` (`e029ea2`), `bitrix_stage_catchup_enabled` (`99a798a`),
  `openrouter_balance_check_enabled`, `bitrix_health_enabled`, `dossier_when_intercepted_enabled`
  (`5ab70ac`) — все False.

### W35–W36, 24.08–06.09 — затишье (2 коммита: `0c0e861`, `6c8f6e3`, алерты тишины)

### W37, 07–13.09 — контроллер карточек Bitrix, учёт продаж
- `3b64b5a` протокол вместо Венома (07.09). `26a23b8` контроллер карточек; `48d7150` уход из «Нового
  лида»; `3737f9f` дожим порциями (818 сообщений залпом).
- Учёт продаж: `2a7541c`, `c081d68`, `e540678` sale-check («клиент оплатил?» менеджеру), `5cb18e8`
  сделка заполненной. `fdc3c96` напоминание о клиенте, ждущем человека. `0f17014`, `32585da`
  дочитывание/прогон по истории; `53fe824`, `6c2721c`, `2b52e47` вранья в фактах.
- Флаги: `bitrix_stage_dialog_started_enabled`, `pipeline_controller_alert_enabled` (07.09),
  `sale_check_enabled` (`2a7541c`), `bitrix_deal_contact_enabled`, `awaiting_telegram_enabled` (11.09),
  `facts_when_silent_enabled`, `tour_facts_budget_enabled` (13.09) — все False.

### W38, 14–20.09 — карточки Bitrix, отчёт заказчику
- `24d4ddc` видно, что бот узнал; `ef41855`, `18af42f` дожим по воронкам; `74b8f4c` месячный отчёт.
- 17–22.09 бот молчал 6 дней (OpenRouter 402) — `docs/project-journey.md:115`, CLAUDE.md@`0fcce2e`.
- Флаги: `dossier_refresh_enabled`, `bitrix_lead_fields_enabled` (`24d4ddc`), `dossier_shared_cards_enabled`,
  `watchdog_telegram_enabled` (15.09) — False.

### W39, 21–27.09 — сторожа после аварии, документы
- `4c7b615`, `e2a2568` сторож тишины; `f706754` `docs/project-journey.md`; `643ed93` сервисы/деньги;
  `095d82d` сверка продаж. Прод на `4c7b615` (CLAUDE.md@`0fcce2e`:231).
- Флаги: `llm_fallback_handoff_enabled`, `watchdog_silence_enabled` (23.09), `silence_webhook_proof_enabled`
  (26.09) — False.

### W40, 28.09–04.10 — протокол v4, встреча 01.10, ТЗ CRM 03.10, начало «админка как CRM»
- `8feec27`, `453a401`, `2f203d7` протокол v4 (29.09).
- `5b04cc5`, `64214df`, `f6bbc86` Wappi connecting/QR (ТЗ `ai/tasks/2026-09-29-qr-advice-on-reconnect.md`).
- **01.10**: `f80a969` «ТЗ воронок после продажи» = `docs/task-post-sale-funnels-0110.md` (встреча с
  Даулетом: «в следующем месяце будем отказываться от Битрикса»); `c478d83` M1 единый каркас панели +
  разделение туров/виз; `739019c`.
- 02.10: `dc9cb06` M2 панель с телефона; `8a8de2f` инбокс страницей; `596ae70` рейсы в карточке тура
  (ТЗ `docs/task-tour-flights-and-tvcard-0210.md`, просьба Гриши 02.10).
- 03.10: `af8e440` передача контекста + разбор базы знаний по визам КР. ТЗ CRM — `ai/tasks/2026-10-03-crm-product-spec.md`
  (DONE, `docs/spec-crm-frunze-getvisa-2026-10-03.md`, 40 сценариев приёмки, этапы E0–E7/R1–R4), комплект
  `ai/tasks/2026-10-03-crm-spec-delivery-pack.md` (35 задач, `docs/crm-delivery/`). Закоммичено позже — `85be18b` (05.10).
- Флаги: `outcome_infer_skip_unchanged_enabled`, `wappi_connecting_grace_enabled` (28.09),
  `wappi_reconnecting_advice_enabled` (29.09), `admin_direction_split_enabled` (01.10), `tour_flights_enabled`,
  `admin_inbox_limit_enabled` (02.10) — False.

### W41, 05–11.10 — 102 коммита: доменный слой CRM (E1/E2) и PDF Гриши (E5/E6)
- 05.10 CRM-ядро: `070d476` услуги, права, договор, деньги, связь старых обращений (E1, E2-03);
  `817e9a6` задачи (E2-04); `99f82fe` билеты и путь тура (E2-01/02); `4a22ecb` рабочий день и карточка
  услуги (E2-06); `913feab` деньги ограничены направлением (DEC-11); `90d87a5` новый вид панели, чат
  «Пальма», «Фокус». Миграции 0007→0009 на прод 05.10 (`ai/STATE-history.md:316`).
- 07.10: `ebf4ee5` форма договора (`ai/tasks/2026-10-06-contract-form.md`).
- 07–11.10 линия PDF «Визы в Кыргызстан» (E5-01…E6-20): `41064f7` 208 черновых правил из PDF, `5cf53d8`,
  `653a20a`, `c8228e5`, `dba3847`, `ca387a0`, `cf7fb0d`, `abad74f`, `7722d37`, `e99e067` (E5-02/03);
  `56f84e0`, `2ebe7f4`, `f851f63`, `0520c8b`, `e23e39e` (E5-04 анкета/квалификация в CRM, 09.10);
  `91a43fa`, `f923a44`, `6af101f`, `1d3372e`, `5feb4e0`, `6c4b587`, `71ba91e`, `06df2a6`, `9e3048f`,
  `29c27ab`, `a3316af`, `26655d4`, `d9ecb11`, `4c570a3` (E6-01…E6-09, 10.10); `9f26aec`, `8ad7b78`,
  `594a9f3`, `c611b86`, `fe43b46`, `944bb41`, `4fcf694`, `214d88f`, `d1c9a38`, `dc474d8` (E6-10…E6-19, 11.10).
  Цель `ai/tasks/2026-10-10-pdf-to70.md` («лучше сто сделай»); баллы 42→67→74→77→82→84→89→90 (коммиты
  `68d61b1`, `419fe40`, `e9e7c35`, `8575f1f`, `e37749a`, `3efe3b6`, `8f41566`, `bdc47f0`).
- 08.10: онбординг Ермека (`b105f41`…`ff2b484`).
- Флаги: `admin_new_look_enabled`, `admin_chat_redesign_enabled`, `admin_focus_enabled`,
  **`service_cases_enabled`** (`90d87a5`), `admin_workday_enabled` (`4a22ecb`), `admin_kg_entry_enabled`
  (`56f84e0`, 09.10) — False.

### W42, 12–18.10 — PDF до 99/100, отдельная CRM на домене, «короткий путь»
- 12–13.10 E6-21…E6-30: `c737457`, `d847a25`, `87ad9e7`, `643c455`, `d3f9464`, `9b60f51`, `e08338b`,
  `d57cb05`, `1458334`, `43ba1cc`, `d1d5138`, `ce335c7`; `5200ac1` «final local PDF acceptance at 99 points»
  (13.10). Приёмка владельцем — `docs/pdf-owner-acceptance.md` (13.10, «ответы не получены», J05).
- **14.10 01:40 `d5886b7`** «standalone CRM service released at crm.frunzetravel.kg» (R9, образ
  `frunze-crm:10dc6b02…`, пустая БД). В тот же день ~05:50 домен переключён на панель бота, CRM R9
  остановлена (`b799d30`:ai/STATE.md «ВЫКАЧЕНО 14.10»; nginx-бэкап `…20261014-014947-before-bot-panel`).
- 14.10 «короткий путь»: `a749887`, `4879308` — `docs/plan-bitrix-exit.md` §7 (вариант Б): пилот виз 27.10,
  Bitrix для виз только чтение к 31.10; решения Алана 14.10 — CRM = панель бота, продажа = полная оплата.
  `464a799` hotfix/panel-safety (прод); `53a7212` B1 режим «CRM на данных бота» (OFF, отложен:
  аудит NO-GO прод — `ai/tasks/2026-10-14-b1-crm-on-bot-data.md`); `091aaf4` B2a файлы; `f4e6806` B2b очередь
  ждущих; `aec5e6d` B2c напоминание; `990a3d9` B5 kill-switch зеркала Bitrix по боту; `83207f8` read_back guard;
  `7b63d2c` материалы к пилоту.
- 15.10 `9438f1f` + `c8673a6` B3 «продажа = полная оплата» (CRITICAL, `ai/tasks/2026-10-14-b3-sale-full-payment.md`).
- Флаги: `crm_standalone_enabled` (`d5886b7`), `bitrix_read_back_enabled`=**True** (`83207f8`),
  `crm_bot_send_enabled` (`53a7212`), `panel_send_media_enabled`, `panel_media_view_enabled` (`091aaf4`),
  `pilot_reply_queue_enabled` (`f4e6806`), `pilot_reply_alert_enabled` (`aec5e6d`),
  `sale_by_full_payment_enabled`, `sale_check_panel_contract_enabled` (`9438f1f`) — остальные False.

### W43, 19–25.10 — большой выкат, редизайн, простой режим, въездная ветка бота
- 19.10 `773eb46` — прод на `feat/visa-bitrix-exit`, БД 0009→0043 (`f1164b5`; handoff
  `ai/handoffs/2026-10-19-2345-deploy-visa-bitrix-exit.md`).
- 20.10 редизайн v2: `b2700c9`, `4459202`, `9303e81`, `f73794f`, `3e2cf50` (handoff `2026-10-20-0120-panel-redesign-v2.md`).
- 21.10: `0c522ad`+`826814d` перф инбокса (52 812 сообщений каждые 10 с); `2aee635` **простой режим**;
  `45edf10` клиенты без карточки Bitrix; `22df616` grisha — визовый менеджер; `1f47a40`, `48f0572`,
  `95ac5fc`, `fc12075` въездная ветка бота (KG entry) за флагом.
- 22–23.10: `2c6ac83`, `b6459dd`, `9fc319c`, `d955630` (534 подписанных куска), `fd1df48`, `90640f7`,
  `9aa9acb`, `4adb66d`, `8b81380`, `ee5e120`. `aadecc3`, `d908808` — `docs/tours-owner-answers-needed.md`.
- Флаги: `panel_simple_mode_enabled`, `panel_missing_cards_enabled`, `kg_entry_enabled`,
  `kg_entry_say_confirmed_enabled` (21.10), `kg_entry_knowledge_enabled` (`b6459dd`, 22.10) — False.

### W44, 26.10–01.11 — маршрутизация v2, CI, параллельные потоки PM 30.10
- 28–29.10: `aa00b68` routing v2 + стоп-факторы; `d19bd27`, `e516e89` CI (GitHub Actions); `aba6a6d`
  «субагенты codex — это Claude» (все прежние ревью same-vendor); `720ff83`; `593e84f` подготовка снятия
  подписи `KG.KB.12.3#011`.
- **30.10** (день опросника): четыре потока `pm/ux`, `pm/ux2`, `pm/bitrix`, `pm/pdf` слиты в
  `claude-pm/integration` (`f70f1a7`…`9712080`). Содержание: `5c4abdc` простой режим «как в WhatsApp»,
  `d4ce9b8` «Мои дела», `590e2b7` новый клиент/заметки/карточка клиента, `3a105bd` + `63ecccf` архив
  Bitrix24 (JSONL, поиск), `28eee59` + `cc5c6e9` B4 перенос открытых лидов из Bitrix (сухой прогон),
  `df050d2` сводка пилота, `ad20081` MSG-02 «не уверены, что дошло», `117207e` передача менеджеру,
  `3d0015c` направление задачи задаёт сервер, `5eb2136` доступ визового менеджера к въездной CRM,
  `15d2f12` черновик процесса визовой услуги по PDF 14.2–14.3, `0d0aeb3` изоляция въездного клиента.
- Флаги: `kg_entry_stop_factors_enabled`, `kg_entry_routing_v2_enabled` (29.10), `kg_entry_outbound_isolation_enabled`,
  `panel_manual_lead_enabled`, `panel_client_card_enabled`, `reassign_moves_tasks_enabled`,
  `kg_entry_manager_access_enabled`, `panel_send_unknown_status_enabled`, `panel_bitrix_archive_enabled`,
  `panel_pilot_summary_enabled` (30.10) — False.

### W45, 02–08.11 — ответы заказчика 05.11
- Новая ветка `feat/owner-answers-2026-11-05` от `9712080` (handoff `ai/handoffs/2026-11-05-owner-answers.md`):
  `15f4de5` снята подпись 12.3#011, `e9c01aa`, `e5660aa` (10 подписей), `463e706` въездная воронка + шенген
  после договора, `a917b38` права внутри направления (ответы 2.1/2.2) и рабочее окно CRM 2.5.
  Параллельно `1a69b72` черновик отчётов конверсии (ветка не влита).
- Флаги: `manager_sees_direction_cases_enabled`, `manager_can_take_colleague_dialog_enabled`,
  `awaiting_working_hours_enabled` (`a917b38`) — False.

### W46, 09–15.11 — блокеры C, ответы Медины, показ 13.11
- 09.11: `fa1d7f9` (запись по делу — по владению), `b95984e`, `f886675`, `449c4f6` (task class-c-blockers).
- 11.11 (ответы Медины): `006a7d5` шенген, `e7471ef` США, `c03b3b7` Китай/Корея/Япония; `3c3ec27`
  колонки доски по направлению; `2d9c47d`, `89ec376` касания задачами; `1620bf0` причина закрытия;
  `94c3a41` клиент забирается с услугой; `d9ad18b`, `1d269a5`, `615e911` учётки; `cc1ddd2` проигрыватель
  сторожа; `1bdca60` готовность к демонстрации.
- 12.11 (правка Медины, ночное ревью): `0e0e040`, `100c86c`, `5af84bd` автозакрытие; `028bbbc`, `4f05d62`
  поля визовой карточки; `58cf6bd` «Новый лид → В работе»; `acb1818`, `fca71a5` хеши паролей; `69fe5c7`;
  `bb650dd`; `aa8275c` лечение 7 из 25 владельцев; `50a5a97` правки Гриши к въездной воронке от 05.11;
  `a0fb67c`; `e4b2d93`, `22b8416` отчёты по списку Медины; `7e85a60` backfill стадий; `b091776` калибровка.
- Флаги: `board_columns_by_direction_enabled` (`3c3ec27`), `visa_touch_tasks_enabled` (`2d9c47d`),
  `lost_reason_enabled` (`1620bf0`), `auto_close_after_touches_enabled` (`0e0e040`), `visa_card_fields_enabled`
  (`028bbbc`), `auto_stage_on_manager_reply_enabled` (`58cf6bd`), `panel_reports_enabled` (`22b8416`) — False.

### W47, 16–22.11 — только документы (`a3156b6`, `e510481`); работа 19.11 по Марселю не закоммичена
### W48, 23–29.11 — коммит 19.11 и сдача 27.11
- 24.11 `0bf8c65` сборы e-Visa и деловая США 600$ (работа 19.11, handoff `2026-11-19-marsel-fees-usa-600.md`); `d9f0235`.
- 27.11 `a74b9ac` свежие лиды сверху, `67762ee` обрезка колонок доски + фильтр не слетает, `1e42c7c`.
- Флаги: `kg_entry_fees_reply_enabled`, `visa_usa_business_price_enabled` (`0bf8c65`), `panel_fresh_first_enabled`
  (`a74b9ac`), `panel_board_column_cap_enabled` (`67762ee`) — False.

Ранее 01.08 (для полноты): `calendar_autotask_enabled` (`d0b9537`, 27.07), `instant_handoff_enabled` (`97ea0b8`, 30.07).
Флага `cases_write_enabled` в истории `app/config.py` нет ни в одной ветке.

---

## 2. Выкаты на прод

| Дата | Коммит прода | Что включало / действия | Источник |
|---|---|---|---|
| 06–07.08 | (три выката сторожа) | сторож каналов v1/v2 | `docs/project-journey.md:96` |
| 15.08 | `28e5ff6` | деплой стал git-checkout скриптом | коммит |
| ≤24.09 | `4c7b615` | сторож тишины | CLAUDE.md@`0fcce2e`:231 |
| ~28.09 | `5b04cc5` | Wappi connecting grace, outcome_infer ON | `ai/STATE-history.md` табл. |
| 02.10 | `c80fa32` → `41c8e12` | M1 каркас панели, M2 телефон, инбокс страницей, рейсы (флаги OFF) | `ai/handoffs/2026-10-02-1900…`, `…-2200-deploy-three-flags-off.md` |
| 05.10 | (хеш не записан) | миграции 0007→0009 (E1/E2-03 деньги), бэкап + проверка восстановления | `ai/STATE-history.md:316` (handoff `2026-10-05-2100` при этом пишет «выкатки нет») |
| 14.10 01:40 | отдельный стек `d5886b7` | crm.frunzetravel.kg → standalone CRM R9 | `d5886b7`, `779ed81` |
| 14.10 ~05:50 | `464a799` (hotfix/panel-safety) | домен crm → панель бота; R9 остановлена; пароли менеджеров сменены | `b799d30`:ai/STATE.md |
| 19.10 ~23:40 | `773eb46` | ветка feat/visa-bitrix-exit, БД 0009→0043 (76 таблиц), флаги OFF | `f1164b5`, ai/STATE.md:1602 |
| 20.10 ~00:40 | — | ВКЛ: `admin_new_look`, `admin_chat_redesign`, `admin_focus`, `admin_workday`, **`service_cases_enabled`**, `panel_send_media`, `pilot_reply_queue`; засеяно 9 продуктов, опубликованы `tour_package`, `visa_usa` | ai/STATE.md:1608 |
| 20.10 | `b2700c9`→`4459202`→`9303e81`→`f73794f` | редизайн v2 | ai/STATE.md:1615 |
| 21.10 | `0c522ad`/`826814d`, `2aee635`, `b2664b7`, `59e712d`, `fc12075` | перф, простой режим (ВКЛ 21.10 10:14), въездная ветка (флаги OFF) | ai/STATE.md:1540, 1631 |
| 22.10 | `7724886` | знания въезда, три выката подряд | ai/STATE.md:1361 |
| 23.10 | `8b81380`, `4adb66d` | ВКЛ `kg_entry_enabled:getvisa`, `kg_entry_say_confirmed_enabled:getvisa`, `kg_entry_knowledge_enabled:getvisa` | ai/STATE.md:992–1003 |
| между 09 и 11.11 | `2f0969d` | ответы 05.11 + блокеры C (флаги OFF) — **факт выката не записан**, известен только как «точка отката» | ai/STATE.md:676 |
| 11.11 | `3c3ec27` → `89ec376` → `1bdca60` → `c03b3b7` → `1620bf0` | ВКЛ `board_columns_by_direction`, `visa_touch_tasks`, `panel_pilot_summary`, `lost_reason`; шенген опубликован на боевой CRM | ai/STATE.md:497–700, `dfd6057`, `16713ee`, `7216b49` |
| 12.11 | `0e0e040` → `bb650dd` → `4f05d62` | автозакрытие (OFF), ночное ревью, поля визовой карточки (OFF) | ai/STATE.md:242, 313, 470 |
| 13.11 ночь | `a0fb67c` | auto_stage, отчёты, воронка Гриши в образе (OFF) | ai/STATE.md:172 |
| ≤16.11 | `22b8416` | отчёты Медины (OFF) — **запись о выкате отсутствует**, впервые «прод на 22b8416» в `a3156b6` | CLAUDE.md@`a3156b6` |
| 27.11 | `67762ee` (+`0bf8c65`) | ВКЛ `panel_fresh_first_enabled`, `panel_board_column_cap_enabled`; сборы e-Visa/США 600 уехали с флагами OFF; PROD_FUNCTIONALLY_VERIFIED под grisha (доска 6524→973 КБ) | ai/STATE.md:19–24, `1e42c7c` |

---

## 3. Статусы задач

### 3.1 `ai/tasks/` (74 файла)
Статус «по документу» → «по последующим данным». Линия E5/E6 — вся локальная синтетика; код уехал на
прод с `773eb46` (19.10, миграции 0036–0043), но экраны закрыты `admin_kg_entry_enabled` (OFF);
весь PDF — 99/100, J05 (приёмка людьми) открыт (`docs/e5-pdf-progress.md:3`, `docs/pdf-owner-acceptance.md`).
Ревью с пометкой APPROVE/GO делались субагентами Claude — same-vendor (`aba6a6d`, `720ff83`).

| Файл | Тема | Статус документа | Итог |
|---|---|---|---|
| 2026-09-29-qr-advice-on-reconnect | не советовать QR при переподключении | нет строки | DONE, выкачено 02.10 с флагом OFF (STATE-history табл.) |
| 2026-10-03-crm-product-spec | ТЗ CRM | DONE (документ) | DONE как документ; из 40 AC ни один не принят менеджерами (laptop-handoff:124) |
| 2026-10-03-crm-spec-delivery-pack | комплект к ТЗ (35 задач) | DONE (документ) | backlog отстал (laptop-handoff:134) |
| 2026-10-06-contract-form | форма договора | PARTIALLY_READY | код `ebf4ee5`, на проде с 19.10; дел создано 0 → PARTIAL |
| 2026-10-06-e5-02a-validation | валидация анкеты/пакета | DONE local | PARTIAL (локально) |
| 2026-10-07-e5-01b-search-corpus | корпус поиска PDF | нет (handoff DONE) | DONE local, `5cf53d8` |
| 2026-10-07-e5-02b-import | атомарный импорт черновиков | PARTIALLY_READY | PG16 частично; PARTIAL |
| 2026-10-07-e5-02b-source-bundle | 208 черновых правил | DONE | DONE local, `41064f7` |
| 2026-10-07-e5-02c-review-diff | сравнение версий | DONE (SELF_REVIEW) | DONE local |
| 2026-10-07-e5-02d-country-index | индекс стран | нет (handoff DONE) | DONE local, `dba3847` |
| 2026-10-07-e5-02e-conditions | условия особых режимов | нет (handoff DONE) | DONE local, `ca387a0` |
| 2026-10-07-e5-02f-projection | атомарная проекция | PARTIALLY_READY | PARTIAL |
| 2026-10-07-e5-03a-stay-days | расчёт дней пребывания | PARTIALLY_READY | PARTIAL (`abad74f`) |
| 2026-10-07-e5-03b-deadlines | календарь/сроки | PARTIALLY_READY | PARTIAL (`7722d37`) |
| 2026-10-09-e5-01c-knowledge-search | поиск фрагментов PDF | DONE local | DONE local, `e23e39e` |
| 2026-10-09-e5-03c-calculation-storage | история поездок/расчёты | PARTIALLY_READY | PARTIAL (`4cd8f6d`) |
| 2026-10-09-e5-03d-qualification-review | единая квалификация | нет (handoff PARTIALLY_READY) | PARTIAL (`cdc490c`) |
| 2026-10-09-e5-03e-qualification-storage | хранение квалификации | PARTIALLY_READY | PARTIAL (`2ebe7f4`) |
| 2026-10-09-e5-04a-crm-qualification | анкета из карточки услуги | PARTIALLY_READY | PARTIAL (`56f84e0`) |
| 2026-10-09-e5-04b-review-card | карточка анкеты | PARTIALLY_READY (доступ менеджера ждёт решения) | доступ сделан `5eb2136` (30.10) за `kg_entry_manager_access_enabled` OFF → PARTIAL |
| 2026-10-09-e5-04c-intake | расширенная анкета | PARTIALLY_READY | PARTIAL |
| 2026-10-09-e5-04d-history-crm | история пребывания в CRM | PARTIALLY_READY | PARTIAL (`f851f63`) |
| 2026-10-09-e6-01a-applications | реестр заявителей/заявок | PARTIALLY_READY | PARTIAL; заявок на проде 0 (demo-readiness) |
| 2026-10-10-e6-01b-group-overview | обзор группы | DONE local | DONE local |
| 2026-10-10-e6-01c-process-preview | превью процесса | DONE local | DONE local |
| 2026-10-10-e6-02a-document-checklists | чек-листы документов | DONE local | DONE local |
| 2026-10-10-e6-02b-document-inventory | инвентарь документов | PARTIALLY_READY | PARTIAL |
| 2026-10-10-e6-02c-issued-documents | выданные документы | PARTIALLY_READY | PARTIAL (`6c4b587`) |
| 2026-10-10-e6-03a-template-preview | превью шаблонов | нет (handoff DONE) | DONE local (`1d4a73c`) |
| 2026-10-10-e6-04-applicant-profiles | профили заявителей | PARTIALLY_READY | PARTIAL (`71ba91e`) |
| 2026-10-10-e6-05-application-deadlines | сроки заявок | нет | UNKNOWN по документу; код `06df2a6`, позже закрыт E6-20 (DONE local) |
| 2026-10-10-e6-06-deadline-tasks | задачи по срокам | нет (handoff PARTIALLY_READY) | закрыт E6-19 (`dc474d8`, `996059e`) → DONE local |
| 2026-10-10-e6-07a-knowledge-decisions | решения по знаниям | нет (handoff PARTIALLY_READY) | PARTIAL (`29c27ab`) |
| 2026-10-10-e6-07b-knowledge-publication | публикация версий знаний | нет (handoff PARTIALLY_READY) | PARTIAL; на проде подписано 534→454→453 куска (`d955630`, `15f4de5`) |
| 2026-10-10-e6-08-complete-document-packages | пакеты документов | нет (handoff DONE 11.10) | DONE local (`26655d4`) |
| 2026-10-10-e6-09-document-quarantine | карантин документов | DONE local | DONE local (`4c570a3`) |
| 2026-10-10-pdf-to70 | цель «PDF до 100%» | PARTIALLY_READY | 99/100 (`5200ac1`), J05 открыт → PARTIAL |
| 2026-10-11-e6-10 … e6-13 | этапы, портал, интервью, расчёты стоимости | DONE local | DONE local (`9f26aec`, `8ad7b78`, `594a9f3`, `c611b86`) |
| 2026-10-11-e6-14-channel-handoff | подавление канала при передаче | «in progress» | код `fe43b46` есть → документ устарел; UNKNOWN по ревью |
| 2026-10-11-e6-15-source-scenarios | сценарии SOP/B.8 | PARTIALLY_READY | PARTIAL; позже `ca78933` (B8 goldens) |
| 2026-10-11-e6-16-notification-drafts | черновики уведомлений | pre-audit GO | код `4fcf694`; UNKNOWN |
| 2026-10-11-e6-17-profile-integrity | целостность профилей | «implementation pending» | код `214d88f` есть → документ устарел |
| 2026-10-11-e6-18-typed-journal-audit | аудит журналов | нет | код `d1c9a38`; UNKNOWN |
| 2026-10-11-e6-19-deadline-task-review | закрытие ревью E6-06 | нет | `996059e` «close scoped deadline task review» → DONE local |
| 2026-10-11-e6-20-deadline-review | ревью сроков | DONE local | DONE local |
| 2026-10-11-overnight-local-pdf | ночная работа | DONE | DONE (отчёт `f06f5ea`) |
| 2026-10-12-e6-21 … e6-28 | ответы со ссылкой на источник, кандидаты маршрута, расчёты, профили, история | DONE local (e6-22a — в задаче FIX_REQUIRED, в handoff DONE) | DONE local |
| 2026-10-12-e6-29/29a/29b/29c | прерывание диалога, эскалация | 29c «IMPLEMENTING» | handoff 29c DONE (`2026-10-12-1840`) → DONE local; задача устарела |
| 2026-10-13-e6-30/30b/30c/30d/30e | дело до договора, квота специалиста, приёмка источника, якоря, SOP | 30c «IMPLEMENTING», остальные DONE | handoffs 30c DONE (`2026-10-12-2125/2205/2245`) → DONE local |
| 2026-10-13-standalone-crm-release | отдельная CRM на домене | PARTIALLY_READY | выкачено 14.10 и снято с домена в тот же день; стек поднят, домен на панель бота (CLAUDE.md §8) → BLOCKED/заморожено |
| 2026-10-14-b1-crm-on-bot-data | CRM на данных бота | нет (аудит NO-GO прод) | отложено «до ноября» (`plan-bitrix-exit.md` §7), в ноябре не возобновлялось → BLOCKED |
| 2026-10-14-b3-sale-full-payment | продажа = полная оплата | 8 DONE, 1 NEEDS_HUMAN_DECISION (S8) | на проде с 19.10, флаги OFF; S8 открыт → PARTIAL |
| 2026-10-29-unsign-kg-kb-12-3-011 | снять подпись льготы швейников | «ПОДГОТОВЛЕНО, НЕ ПРИМЕНЕНО» | применено `15f4de5` 05.11 → DONE, документ устарел |
| 2026-11-09-class-c-blockers | блокеры C по ответам 05.11 | «В РАБОТЕ» | 6 блокеров закрыто (`fa1d7f9`,`b95984e`,`f886675`), кросс-вендора нет → PARTIAL (ai/STATE.md:740) |
| 2026-11-11-demo-readiness | три дыры к демонстрации | «ЕСТЬ ТРИ ДЫРЫ» | дыра 3 (сводка пилота) закрыта 11.11 (`a23f6e6`); дыра 2 частично — опубликован шенген (`dfd6057`), 2 воронки нет, заявок 0; дыра 1 (учётки daulet/marsel) открыта (CLAUDE.md §8) → PARTIAL |
| 2026-11-11-pre-contract-funnel | до-договорная воронка Медины | «ГЕЙТ ДО КОДА» | сделано: `3c3ec27`, `2d9c47d`, `1620bf0`, `028bbbc`, `58cf6bd`, `0e0e040`; ВКЛ колонки/касания/причины/поля; auto_stage и автозакрытие OFF → PARTIAL, документ устарел |

### 3.2 `docs/task-*.md`
| Файл | Дата, коммит | Тема / источник | Статус |
|---|---|---|---|
| task-tours-dates-and-budget | 30.06 `b774475` | даты в прошлом, бюджет (живой диалог) | исторический, вне окна |
| task-stt-guard-v1 | 05.08 `20be79b` | фильтр доверия STT | DONE (39/39 в самом ТЗ), флаг ON |
| task-channel-heartbeat-v2 | 07.08 `86b9325` | сторож v2 | DONE, но v2 шум не убрал — заменён v3 |
| task-wappi-health-v3 | 07.08 `271921d` | сторож спрашивает Wappi | DONE; дыра: 402 «Profile not paid» падает в общий except (`wappi_health.py:422`, ai/STATE.md 28.10) |
| task-bitrix-card-link-fix | 11.08 `abda525` | ссылка в карточку | DONE |
| task-tours-cards-v1 | 11.08 `7409d44` | карточки туров (встреча 11.08) | DONE, флаг `tours_cards_enabled` |
| task-bitrix-lead-pipeline | 17.08 `e4a4743` | бот ведёт карточку (Даулет) | DONE |
| task-bitrix-dossier-live | 18.08 `198bac3`/`81dd9be` | досье за клиентом | DONE; ⚠ флаг `offer_change_notice_enabled` из ТЗ в config.py не найден (возможно переименован) — UNKNOWN |
| task-tour-facts | 18.08 `2d633c1` | факты без поиска | DONE (`abdf047`) |
| task-worker-visa-marsel | 19.08 `4e4b4d6` | бот Марселя, рабочие визы | MISSING (отложено; 19.11 Марсель: отдельная B2B-воронка, требований нет) |
| task-dossier-and-owner-alerts | 21.08 `5ab70ac` | досье при перехвате + алерты | DONE |
| task-post-sale-funnels-0110 | 01.10 `f80a969` | **встреча с Даулетом 01.10: после продажи + своя CRM, отказ от Bitrix** | PARTIAL: модель этапов/договор/деньги/задачи — да (E1/E2), дашборд до/после, напоминания чек-ин/шенген, бот после продажи (опросник, отзыв 2ГИС) — MISSING; отказ от Bitrix — не состоялся |
| task-tour-flights-and-tvcard-0210 | 02.10 `0d44c80` | рейсы и tourcart (Гриша) | рейсы DONE (флаг OFF), tourcart BLOCKED (ждём TourVisor) |

Прочие документы: `docs/tours-owner-answers-needed.md` (23.10, `d908808`) — 14 вопросов Даулету, все 14
полей «**Ответ:**» пусты (строки 46–202) → MISSING. `docs/pdf-owner-acceptance.md` (13.10) — «пакет никому не
отправлен» → J05 BLOCKED на людях. `docs/plan-bitrix-exit.md` — пилот 27.10 и 31.10 не состоялись
(laptop-handoff:122; в STATE после 23.10 записей о пилоте нет). `docs/modules-roadmap.md` — сверен 14.10 (`a749887`), устарел.

---

## 4. Ключевые повороты курса — подтверждение из репо

| Поворот | Подтверждение |
|---|---|
| Идея «панель — рабочее место» (Марсель без Битрикса) | `e4b4bc7` 14.08 |
| **01.10 встреча с Даулетом: своя CRM, отказ от Bitrix «в следующем месяце»** | `docs/task-post-sale-funnels-0110.md` (`f80a969`), цитаты §1 |
| ТЗ CRM 03.10 | `ai/tasks/2026-10-03-crm-product-spec.md` (DONE), `docs/spec-crm-frunze-getvisa-2026-10-03.md` (в git с `85be18b` 05.10), комплект `docs/crm-delivery/` |
| PDF Гриши (въездные визы) | `41064f7` 07.10 (208 черновых правил), линия E5/E6 07–13.10, 99/100 `5200ac1`; PDF в репо не лежит (`docs/e5-pdf-section-coverage.md` — хеш); экраны — 36 файлов `app/admin/kg_*.py`, 5548 строк, гейт `admin_kg_entry_enabled` (`app/admin/kg_entry.py:50`). Дата поступления PDF (сентябрь) — только [sources, untracked] pm-chronology |
| Отдельный стек frunze-crm (13/14.10) | `d5886b7` 14.10 01:40 +0600 (=13.10 19:40 UTC); снят с домена 14.10 (`b799d30`) |
| «Короткий путь»: CRM = панель бота, пилот 27.10, Bitrix только чтение к 31.10 | `docs/plan-bitrix-exit.md` §7 (`4879308`, 14.10); ai/STATE.md:1651 |
| Пилот 27.10 / Bitrix только чтение к 31.10 | **в репо нет подтверждения, что состоялись**; laptop-handoff:122 — «не состоялись». Причины по STATE 28–29.10: GetVisa Wappi 402 (1046 раз за 72 ч), туры 401 по QR, бот GetVisa молчит с 24.10 22:38 |
| panel_simple_mode | `2aee635` 21.10, ВКЛ на проде 21.10 10:14 (ai/STATE.md:1631); расширение `5c4abdc`, `999d990` 30.10 |
| Опросник 30.10 | в коммитах: потоки PM 30.10 (`9712080`), памятка `0d912b6`; ответы — только [sources, untracked] `opros-otvety-2026-10-30.md`; текст опросника в репо — UNKNOWN |
| Ответы 05.11 | `ai/handoffs/2026-11-05-owner-answers.md`, `a917b38` (ответы 2.1/2.2/2.5), `463e706`, `e5660aa` (ответ 5.5); созвон Гриши с Марселем 05.11 — `50a5a97` 12.11 («правки Гриши от 05.11 — наконец применены») |
| Медина 11–12.11 | `006a7d5`, `e7471ef`, `c03b3b7`, `3c3ec27`, `2d9c47d`, `1620bf0` (11.11); правка 12.11 — `028bbbc`, `58cf6bd`, `0e0e040`; задача `ai/tasks/2026-11-11-pre-contract-funnel.md` |
| Показ 13.11 | `ai/tasks/2026-11-11-demo-readiness.md`; nginx — сессия 13.11 10:53–12:33 UTC (laptop-handoff:163); презентация 13 слайдов — только [sources] |
| Сборы Марселя 19.11 | handoff `2026-11-19-marsel-fees-usa-600.md`; закоммичено только 24.11 `0bf8c65` |
| Выкат 27.11 | `67762ee`, `1e42c7c`, ai/STATE.md:19 |
| 20.11 «CRM не готова» (Алан) | в git нет; только [sources, untracked] pm-chronology |

---

## 5. Расхождения

1. **`cases_write_enabled` не существует.** Нет в `app/config.py` ни в одной версии; запись дел читает
   `service_cases_enabled` (`app/admin/router.py:95`, `app/admin/workday.py:93`, config.py:762), и он
   **ВКЛ с 20.10 ~00:40** (ai/STATE.md:1610). Ошибочно указан как «выключенный тумблер, без которого дело
   завести нельзя» в CLAUDE.md §6/§8, `ai/CLAUDE_HANDOFF.md` §4, ai/STATE.md:129, 163 (записи 16.11 и 19.11).
   Реальная причина `service_cases = 0` — никто не создаёт дела + опубликованы процессы только у
   `tour_package`, `visa_usa`, `visa_schengen` (demo-readiness, `dfd6057`). Ошибочное имя проникло в код:
   `app/integrations/panel/reports.py:36` — пользовательский текст «запись дел выключена (cases_write_enabled)»
   — ложь при ON (страница за `panel_reports_enabled` OFF, пока не видно).
2. **`_workday_note()` читает env, а не рантайм-флаг** (`app/admin/router.py:1088`: `settings.service_cases_enabled`,
   compose-дефолт `false`, `docker-compose.yml:259`) — тумблер «Рабочий день» в админке, вероятно, пишет
   «Запись в реестр услуг выключена», хотя `app_flags` = ON. На проде не проверял (UNKNOWN).
3. **Экраны kg_* закрыты не тем флагом, что в CLAUDE.md.** CLAUDE.md §8 (стр. ~426): «закрыты флагами
   `kg_entry_enabled` и `kg_entry_manager_access_enabled` — оба OFF». В коде — `admin_kg_entry_enabled`
   (env-настройка, `app/admin/kg_entry.py:50,68,112`) + `kg_entry_manager_access_enabled`. А `kg_entry_enabled`
   — флаг въездной ветки бота, и он **ВКЛ на getvisa с 23.10** (ai/STATE.md:1002).
4. **Дата показа:** `a74b9ac` и ai/STATE.md:6, laptop-handoff:71 — 14.11 (слова Алана); `67762ee`, ai/STATE.md:14,
   laptop-handoff:163 — 13.11 по nginx (16:53–18:33 Бишкек); 14.11 — один заход в Входящие. Вероятно 13.11.
5. **Прод в CLAUDE.md §8 залип:** «Прод на `4c7b615`» стоял с 24.09 (`0fcce2e`) до 05.11 (`a917b38`) включительно,
   хотя прод сменился ≥15 раз (02.10, 14.10, 19–23.10). Сейчас CLAUDE.md:324 и `ai/CLAUDE_HANDOFF.md:84` пишут
   «прод на 22b8416» рядом с обновлением про `67762ee` (CLAUDE.md:318); CLAUDE.md §6 всё ещё помечает
   `kg_entry_fees_reply_enabled`/`visa_usa_business_price_enabled` «(19.11, не выкачено)» — выкачены 27.11.
6. **Незаписанные выкаты:** `2f0969d` (между 09 и 11.11) и `22b8416` (между 13 и 16.11) — нет записи «выкачено»
   ни в STATE, ни в handoff. 05.10: STATE-history:316 «выкатка состоялась», handoff `2026-10-05-2100`:8 «выкатки нет»
   (вероятно, разное время записи), хеш кода не записан.
7. **`visa_card_fields_enabled`:** ai/STATE.md:248 (12.11) — OFF; CLAUDE.md §6/§8 — ВКЛ; laptop-handoff:106 —
   «ON с 12.11». Момент включения и чьё слово — не записаны.
8. **Работа 19.11** в STATE 19.11 значится «лежит на GitHub», коммит появился 24.11 (`0bf8c65`, признано ai/STATE.md:44).
9. **Устаревшие статусы задач:** `2026-10-29-unsign-kg-kb-12-3-011` («не применено» — применено `15f4de5`);
   `2026-11-11-pre-contract-funnel` («гейт до кода» — код есть); `e6-14` «in progress», `e6-17` «pending»,
   `e6-29c`/`e6-30c` «IMPLEMENTING» при наличии коммитов и DONE-handoff; `2026-11-09-class-c-blockers` «В РАБОТЕ».
10. **Wappi GetVisa 402 «с 23.10»** (laptop-handoff:122) — в STATE: бот GetVisa молчит с 24.10 22:38, 402 проверено
    28–29.10 (ai/STATE.md:899, 958). Точная дата начала — UNKNOWN; когда оплатили — не записано (с 11.11 визы живы).
11. **Отдельный стек frunze-crm:** CLAUDE.md §8 — «релиз 13.10, поднят 12.11»; коммит `d5886b7` 14.10 01:40 +0600
    (13.10 UTC), в тот же день остановлен (`b799d30`). Запись о подъёме 12.11 в git не нашёл.
12. **Устаревшие числа:** CLAUDE.md §3 «136 файлов, 1687 тестов» — сейчас 461 `tests/test_*.py`; уже 05.10
    было «2142 passed» (STATE-history:283). `docs/modules-roadmap.md` (14.10) и `docs/crm-delivery/backlog.md`
    отстали на ~217 коммитов (laptop-handoff:134). CLAUDE.md §8 «Калибровка автозакрытия (13.11)» — коммит `b091776`
    датирован 12.11 (ночь). Подписанных кусков: 534 (`d955630`) → 454 (`a4a1d71` «454 signed pieces», 23.10) → 453 (`15f4de5`).
13. **`deploy_prod.sh` дефолт — `fix/tours-search-quality`** (`scripts/deploy_prod.sh:23`), а рабочая ветка с 05.11 —
    `feat/owner-answers-2026-11-05`. Запуск без аргумента выкатит ветку, отставшую на месяц (риск, не расхождение
    документа: CLAUDE.md §4 так и пишет).
14. **Флаг из ТЗ не найден:** `offer_change_notice_enabled` (`docs/task-bitrix-dossier-live.md:107`) отсутствует в
    истории `app/config.py` — UNKNOWN (мог жить только в FEATURE_FLAGS/flags.py; не проверял).
15. **Ревью:** все APPROVE/GO до 29.10 под именами `codex-*` — Claude (same-vendor) (`aba6a6d`); реестр PDF теперь
    `independently_reviewed: false` (`720ff83`). Кросс-вендорного ревью нет ни у 0bf8c65, ни у 67762ee (ai/STATE.md:24).

## Что не проверено
- Прод не трогал: значения `app_flags` взяты из записей STATE/handoff, не из базы.
- Дата и содержимое выкатов до 02.10 восстановлены по `docs/project-journey.md` и CLAUDE.md, не по логам.
- `docs/sources/2026-11/*` — неотслеживаемые файлы, их достоверность не проверял.
