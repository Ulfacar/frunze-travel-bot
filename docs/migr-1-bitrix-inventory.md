# MIGR-1: от чего в Bitrix реально зависит приложение

04.10.2026. Модуль MIGR-1 из [реестра модулей](modules-roadmap.md), задача E0-03 ТЗ.
Класс S — только чтение кода и трёх значений из `prod.env`. Ветка `fix/tours-search-quality`,
база `af8e440` плюс незакоммиченная панель.

Инвентаризацию кода собрал Sonnet-субагент (`grep -rn bitrix app` — 362 вхождения в 35 файлах),
ключевые утверждения перепроверены лично по коду и по проду. Ниже — только проверенное.

## Главный вывод: канал технически от Bitrix не зависит

| Проверка | Чем | Результат |
|---|---|---|
| Ядро не пишет лиды в Bitrix напрямую | `grep CRM_BACKEND prod.env` | **`postgres`** — ветка `crm_backend=bitrix24` (единственная жёсткая зависимость в коде, `app/integrations/crm/__init__.py:12-18`) на проде не активна |
| Эхо ответов менеджеров ловится | `grep CAPTURE_MANAGER_ECHO prod.env` | **`true`** — после отключения Bitrix панель продолжит видеть, что менеджер ответил, и перехват (`intercept.py`) не ослепнет |
| Входящие через Bitrix не идут | `grep -c bitrix_bot_id prod.env` | **0** — у ботов нет `bitrix_bot_id`, значит любое событие на `/webhook/bitrix` получает `unknown_bot` (`app/main.py:468-470`) |
| Исходящие не идут через Bitrix | чтение `app/channels/wappi.py:424-446` | `POST {wappi}/api/sync/message/send` напрямую; `bot_id=external_api` — лишь параметр, от которого зависит **видимость** реплики в чате Открытой линии, а не доставка клиенту |

Все остальные вызовы Bitrix — мягкие: либо за флагом (`_enabled`), либо в `try/except` с
логом, либо запускаются фоном через `fire()`. Падение портала не теряет переписку.

## Что обязательно заменить своим до отключения

1. **Учёт продаж.** Единственный автоматический источник «продано» — чтение лидов со
   `STATUS_ID = CONVERTED` (`bitrix_pipeline.py:681-703`, `bitrix24.py:166-193`). Это
   модуль MONEY-1 и REPORT-1: своя отметка договора и суммы в панели.
2. **Интерфейс ответа для визовых менеджеров.** Они отвечают клиентам из Контакт-центра
   Bitrix: «Открытая линия → Wappi API → WhatsApp», мимо нашего кода. Это зависимость
   не кода, а процесса — нужен свой способ ответа (панель или телефон). Модули PANEL-3/5.
3. **Карточка клиента и ответственный.** Сегодня «карточка» для менеджера — это лид
   Bitrix; ссылки в `sale_check.py:335-340`, `calendar_brief.py:295-306`,
   `instant_handoff.py:247` ведут в портал. Модуль PANEL-5 (UI-03).
4. **Фактическая стадия и ручные переносы менеджеров.** У нас хранится только «что
   поставил бот» (`bitrix_stage_by_bot`); «сменили руками» определяется сравнением с
   порталом (`bitrix_pipeline.py:138-148`). Своя модель — CORE-1 и CORE-3.
5. **Источник ID менеджеров.** Сейчас JSON в env (`config.py:328`, `:332`), не в нашей БД.
6. **Стадии воронки.** Коды `UC_*` и `STAGE_SEQUENCE` зашиты в `bitrix_pipeline.py:19-22`.
   Своя таблица — CORE-1.

## Что просто выключается флагами

`bitrix_mirror_enabled`, `bitrix_pipeline_enabled`, `bitrix_stage_catchup_enabled`,
`bitrix_stage_dialog_started_enabled`, `bitrix_lead_fields_enabled`, `dossier_*`,
`bitrix_autodeal_enabled`, `bitrix_deal_contact_enabled`, `bitrix_health_enabled`,
`pipeline_controller_alert_enabled`. Пустой `bitrix_portal_url` сам убирает ссылки
на карточки из уведомлений.

## Долг, найденный попутно — закрыт 14.10.2026

**`read_back_once` больше не ходит в портал без нужды** (коммит `83207f8`): ранний выход при
пустом `BITRIX24_WEBHOOK_URL` и рантайм-рубильник `bitrix_read_back_enabled` (кнопка «Учёт продаж
из Bitrix» в админке). Дефолт ON намеренно: это единственный автоматический учёт продаж, а
глобального ключа `bitrix_pipeline_enabled` на проде нет (только ключи по ботам) — гейт по нему
остановил бы учёт. При отказе от Bitrix: выключить рубильник или убрать URL.

## Дополнения 14.10.2026 (сверка с кодом)

- В список флагов выше добавить `bitrix_read_back_enabled` и `bitrix_prefer_openline_lead`.
- Вечерняя ссылка «Оплатил» (`app/core/sale_check.py`, `_convert_lead`) кроме `outcome=won` и суммы
  **пишет `CONVERTED` в Bitrix** — это ещё одна запись в портал, гейт `bitrix_pipeline._enabled` по боту.
- Номера строк в разделах выше сдвинулись; ориентироваться на имена функций.
- Прод бота с 14.10 — ветка `hotfix/panel-safety` (`464a799`), влита в `fix/tours-search-quality`.

## Что осталось UNKNOWN

- Замерено 14.10: на проде `bitrix_pipeline_enabled:<бот>` = t для трёх туровых ботов, `bitrix_autodeal_enabled`, `bitrix_deal_contact_enabled`, `bitrix_health_enabled`, `bitrix_lead_fields_enabled`, `bitrix_mirror_enabled`, `bitrix_stage_catchup_enabled` = t; `CAPTURE_MANAGER_ECHO=true`.

- Значения флагов `bitrix_*` в боевой `app_flags` целиком (смотрел выборочно: из девяти
  найденных по фильтру ключей `bitrix_*` в таблице нет вовсе — значит работают дефолты OFF).
- Есть ли в боевой БД диалоги с `channel="bitrix_openlines"` — от этого зависит, идёт ли
  хоть один исходящий через `imbot.message.add`.
- Поведение самих профилей Wappi, если коннектор Bitrix на их стороне отключить: это вне
  нашего кода, проверяется только у Wappi.
- `BITRIX_STAGE_MAP` в `prod.env` — не смотрел.

Перед отключением сверить на проде: `CRM_BACKEND`, `BOTS`, `CAPTURE_MANAGER_ECHO`,
`BITRIX_STAGE_MAP` и флаги `bitrix_*` в `app_flags`.
