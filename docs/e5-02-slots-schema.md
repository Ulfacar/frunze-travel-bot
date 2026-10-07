# E5-02 — Схема слотов квалификации и импорта въездных правил КР

05.10.2026. Класс задачи — S (документ, кода нет). Роль — архитектура/схема до первой миграции (Fable); реализация — Sonnet по этой схеме, ревью — Codex.

Источники: [KB v1.1 (производная конверсия)](kb-visa-inbound-v1.1-derived.md) — Б.3 (с. 87), Б.5 (с. 88), блок 2 (с. 19–25), блок 13 (с. 61–62), блок 18.4–18.5, 18.11; [ТЗ](spec-crm-frunze-getvisa-2026-10-03.md) §9 (KB-01..05, CALC-01..05), §16 (SRC-04/05/06), §17 (AC-18..23), §20 (DEC-01, DEC-07); [карточка E5-02](crm-delivery/backlog.md); стиль таблиц — [technical-design §2](crm-delivery/technical-design.md). Код-контекст: `app/domain/models.py` (DomainBase, `Product`/`WorkflowVersion`/`ServiceCase`/`ServiceEvent`, `_ServiceJSON`), `alembic/versions/e1_services_0007.py`.

Статус на 05.10: **архитектурный проект**. 06.10 Codex по просьбе Алана реализовал
первый локальный этап [E5-02A — проверка файлов](e5-02a-validation.md): JSON Schema,
семантика анкеты, preflight пакета и CLI. На том этапе таблицы и импорт ещё не были реализованы.
Ниже сохранён исходный проект; номер `e5_knowledge_0008` устарел, следующую миграцию
нужно привязывать к фактическому head. Уточнения исполняемого контракта перечислены в E5-02A.

07.10: подготовлен [E5-02B-SOURCE — реальный черновик из PDF](e5-02b-source-bundle.md),
208 записей, 0 confirmed. Источники/конфликты сохранены.

07.10, следующий этап: [E5-02B-IMPORT](e5-02b-import.md) — четыре таблицы draft-хранилища,
миграция **e5_knowledge_0013 после e2_taskclaim_0012**, атомарный импорт/журнал/дедупликация
и локальная SQLite-репетиция. CRITICAL, PARTIALLY_READY: PG16 и независимые проверки UNKNOWN.
Это не весь проект ниже: DB-индекс стран, публикация/CAS/откат, календарь и квалификация ещё впереди.
Для текущей реализации source_hash = hash PDF, bundle_hash = hash normalized bundle;
review_period_days nullable до DEC-07, снимки immutable уже в draft, populated downgrade запрещён.
Старые номера миграций и инструкция downgrade в §6 — исторический проект, не команда к исполнению.

07.10: [E5-02D — локальный индекс стран](e5-02d-country-index.md) связывает гражданство
с черновыми единицами и показывает неполноту/конфликты. Это чистый review lookup + CLI;
таблица `entry_country_rules`, выбор применимого режима и активация ещё не реализованы.

07.10, E5-02C: [read-only сравнение версий](e5-02c-review.md), контроль согласованности снимков,
изменения отдельных полей и список фактических неизвестных. Никакого разрешения публикации.
Предыдущие этапы закоммичены локально; ссылки на историю — в документе этапа и текущем STATE.

---

## 0. Коротко: что проектируется и какие решения приняты

| Вопрос | Решение в этой схеме |
|---|---|
| Где живут правила | Отдельная версионируемая база знаний (`knowledge_sets` → `knowledge_versions` → `knowledge_units`), не в промпте. Промпт получает только результат калькулятора (E5-03). |
| Слоты Б.3 | Настоящая JSON Schema (draft 2020-12) `kg-entry-slots/1`: типы, enum, условия `if/then`, два профиля обязательности (`collecting`, `handoff`). `unknown` / `not_applicable` / `false` / «не спрошено» — четыре разных состояния, `null` запрещён. |
| SRC-06 | Таблица `stay_intervals`: все интервалы въезд–выезд, основание, вид доказательства, подтверждённость. `days_in_window` из слотов **удалён** — его считает только калькулятор. |
| SRC-04 | У единицы знания есть `confirmation_status = blocked` и отдельное поле `blocked_value` с исходным значением и ссылкой на конфликт. Заблокированная единица не котируема клиенту, остальные работают. |
| SRC-05 | Освобождение от регистрации — **единица на страну** (источник — перечень 2.10, не группа Б.5). Греция 90 и Чили 60 — обычные строки. Импорт отвергает inline-комментарии после значений (lint-правило). |
| Поиск по правилам | Через нормализованную таблицу `entry_country_rules` (страна × тип документа × версия), **не** через поиск внутри JSON. Поэтому `jsonb` не нужен, остаёмся на `json` как в E1-01. |
| Публикация | `draft → review → approved → active → retired`. Смена активной версии — один `UPDATE knowledge_sets SET active_version_id` с CAS по ожидаемому значению, в одной транзакции со сменой статусов версий. Старая версия остаётся. |
| Импорт | Все проверки в памяти (синтаксис → схема → семантика), только потом одна транзакция вставки черновика. Отказ пишется в `knowledge_imports` с адресом ошибки; активная версия не затрагивается никогда. |
| Календарь | `work_calendars` + `work_calendar_days`, одна активная версия на (юрисдикция, год), признак `provisional` для года, где плавающие праздники ещё не объявлены. Нет года — ошибка, не пн–пт. |
| Направление | Новое направление `visa_inbound` **не вводится** (решение Алана). Знания привязаны к `jurisdiction='KG'`, `domain='entry'`, а не к `products.direction`. |

---

## 1. Сущности

Нумерация и стиль — как в technical-design §2. «?» — поле nullable по смыслу, не «по умолчанию». Все `*_at` — `DateTime(timezone=True)`, все календарные даты — `Date` (бишкекская дата, Asia/Bishkek; без времени). JSON-колонки — `_ServiceJSON` (замороженный после чтения), в PostgreSQL рендерится как `json`.

### 1.1 База знаний

| Объект | Таблица | Минимальные поля | Инвариант |
|---|---|---|---|
| KnowledgeSet | `knowledge_sets` | `id`, `code` (uniq, напр. `kg_entry`), `jurisdiction` (`KG`), `domain` (`entry`), `name`, `review_period_days` (дефолт срока проверки), `active_version_id?`, `created_at`, `updated_at` | Одна активная версия на набор. `active_version_id` меняется только операцией `activate_version` (CAS). Удаление запрещено. Составной FK `(active_version_id, id) → (knowledge_versions.id, set_id)` — версия чужого набора не активируется (паттерн `products.current_version_id`). |
| KnowledgeVersion | `knowledge_versions` | `id`, `set_id`, `version` (int ≥1), `status` (`draft/review/approved/active/retired/rejected`), `source_document` (`kb-visa-inbound v1.1`), `source_hash` (sha256 импортированного бандла), `source_prepared_by`, `effective_from?`, `notes?`, `created_by`, `created_at`, `reviewed_by?`, `reviewed_at?`, `approved_by?`, `approved_at?`, `activated_at?`, `retired_at?`, `import_report` JSON | Уник. `(set_id, version)`, уник. `(id, set_id)`. После `approved` единицы версии неизменяемы (хук как у `WorkflowVersion`). Физического FK `set_id → knowledge_sets` нет (встречный FK как в E1-01), целостность — хук `before_insert`. Переходы статусов только вперёд: `draft→review→approved→active→retired`, `draft/review→rejected`. Один `active` на `set_id` (partial unique index `WHERE status='active'`). |
| KnowledgeUnit | `knowledge_units` | `id`, `version_id`, `unit_id` (стабильный, напр. `KG.REG.EXEMPT.GRC`), `kind` (enum §3.1), `title`, `section` (`2.10`), `page` (`24-25`), `source_ref` (`ПР-600 прил.2`), `source_text?` (цитата), `label` (`none/verify/practice/decision`), `confirmation_status` (`confirmed/needs_verification/blocked/decision_pending`), `value` JSON (по схеме kind), `value_schema_version`, `blocked_value?` JSON, `conflict_ref?` (`SRC-04`), `effective_from?`, `effective_to?`, `verified_at?`, `verified_by?`, `review_due_at?`, `owner` (логин/роль), `created_at` | Уник. `(version_id, unit_id)`. `unit_id` стабилен между версиями — по нему сравнивают черновик с активной. `confirmation_status='blocked'` ⇒ `value IS NULL` и `blocked_value IS NOT NULL` и `conflict_ref IS NOT NULL` (CHECK). `effective_to >= effective_from` (CHECK). Неизвестная дата действия — `NULL`, не дата файла (KB-03). Единицы версии в статусе ≥ `approved` — только чтение. |
| EntryCountryRule | `entry_country_rules` | `id`, `version_id`, `country_iso3`, `document_type` (`ordinary/diplomatic/service`), `regime_kind` (`visa_free/visa_required_simplified/visa_required_general/special/check_portal`), `regime_unit_id` (FK на `knowledge_units.id`), `visa_free_days?`, `window_days?`, `work_needs_unified_permit?` (bool), `simplified_scope?` (`all_types/business_tourist/tourist_gcc_resident`), `reg_exempt_unit_id?`, `reg_exempt_days?`, `reg_exempt_status` (`confirmed/needs_verification/blocked/not_in_list`), `quotable` (bool, материализован), `created_at` | Уник. `(version_id, country_iso3, document_type)`. Строится **только импортом** из единиц версии — это индекс, не источник правды; поле `regime_unit_id`/`reg_exempt_unit_id` даёт провенанс. Страны без строки → общий порядок (`KG.VR.GENERAL`) с флагом `country_not_listed` в калькуляторе. |
| KnowledgeImport | `knowledge_imports` | `id`, `set_id`, `bundle_hash`, `filename`, `started_by`, `started_at`, `finished_at`, `result` (`accepted/rejected`), `version_id?` (при accepted), `error_stage?` (`syntax/schema/semantic/db`), `error_location?` (`units.yaml:143:7` или JSON pointer `/units/17/value/days`), `error_message?`, `report` JSON | Append-only. `rejected` ⇒ `version_id IS NULL` (CHECK). Повторный импорт того же `bundle_hash` в тот же набор при существующем черновике возвращает его, не создаёт второй. |

### 1.2 Производственный календарь (CALC-03)

| Объект | Таблица | Минимальные поля | Инвариант |
|---|---|---|---|
| WorkCalendar | `work_calendars` | `id`, `jurisdiction` (`KG`), `year`, `version` (int ≥1), `status` (`draft/approved/active/retired`), `completeness` (`complete/provisional`), `provisional_note?` (что не объявлено: «Орозо айт 2027»), `week_rest_days` JSON (`[6,7]` ISO-дни; дефолт сб–вс для госоргана), `source_ref`, `approved_by?`, `approved_at?`, `activated_at?`, `created_at` | Уник. `(jurisdiction, year, version)`. Одна `active` на `(jurisdiction, year)` (partial unique). Офисный график пн–сб здесь **не хранится** — это другой календарь (`schedule.py`), и он не подменяет госорган. Отсутствие активного календаря нужного года → калькулятор возвращает ошибку `calendar_missing`, не считает по пн–пт. |
| WorkCalendarDay | `work_calendar_days` | `id`, `calendar_id`, `day` (Date), `is_working` (bool), `kind` (`public_holiday/floating_holiday/transfer_rest/transfer_working/weekend_override`), `title`, `source_ref?` | Уник. `(calendar_id, day)`. Строка переопределяет дефолт недели: `transfer_working` на субботу ⇒ `is_working=true`; праздник ⇒ `false`. Плавающие (Орозо айт, Курман айт) — `floating_holiday`; пока их нет в году, календарь `provisional`, и расчёт через провизорный период помечается `calendar_provisional` (AC-21). |

### 1.3 Факты о клиенте

| Объект | Таблица | Минимальные поля | Инвариант |
|---|---|---|---|
| StayInterval | `stay_intervals` | `id`, `contact_id` (FK `contacts.id`), `applicant_id?` (резерв под E6-01, FK добавит та миграция), `entry_date` (Date), `exit_date?` (Date; NULL = ещё в КР), `basis` (`visa_free/visa/ep/resident_card/residence_permit/registration_contract/unknown`), `visa_type?` (код визы при `basis=visa`), `passport_country_iso3`, `passport_label?` (как клиент называет паспорт, не номер), `evidence` (`esuvm/passport_stamp/boarding_pass/visa_document/client_statement/crm_record`), `confirmed` (bool), `confirmed_by?`, `confirmed_at?`, `entered_by` (логин или `bot`), `source_dialog_ref?`, `note?`, `superseded_by?` (self-FK), `created_at` | `exit_date IS NULL OR exit_date >= entry_date` (CHECK). Не более одного открытого интервала на человека среди не-замещённых (partial unique `contact_id WHERE exit_date IS NULL AND superseded_by IS NULL`). **Append-only**: исправление = новая строка + `superseded_by` у старой; удаления нет. `confirmed=true` ⇒ `confirmed_by`/`confirmed_at` не NULL (CHECK). `evidence='client_statement'` ⇒ `confirmed=false` при вставке (хук). Пересечения/дубли на уровне БД **не** запрещены — разные источники могут дать разные границы; слияние делает калькулятор (CALC-02) и дубль не увеличивает пребывание (AC-19). |
| EntryQualification | `entry_qualifications` | `id`, `contact_id`, `dialog_id?`, `service_case_id?`, `schema_version` (`kg-entry-slots/1`), `profile` (`collecting/handoff`), `slots` JSON, `knowledge_version_id?` (версия, по которой заполнялось), `status` (`collecting/handed_off/closed`), `handed_off_at?`, `revision`, `updated_by`, `created_at`, `updated_at` | `slots` валидны по JSON Schema на запись (валидация в домене, не в БД). `revision` как `version_id_col` — два писателя не затирают друг друга. Блок `slots.decision` пишется только калькулятором (`updated_by` операции `apply_calculation`), LLM-путь с непустым `decision` отклоняется. Интервалы из `slots.previous_visits.intervals` при сохранении **упсертятся в `stay_intervals`** (confirmed=false, evidence=client_statement) — источник правды по поездкам всегда таблица. Персональные поля (`contact.*`) в `slots` не хранятся: `contact_id` главнее, блок `contact` отбрасывается при записи. |

Расчёт (`Calculation`) здесь **не проектируется** — это E5-03. Ему потребуется ссылаться на `knowledge_versions.id`, `work_calendars.id`, `entry_qualifications.id` + `revision` и список `stay_intervals.id`, использованных в расчёте. Эти ключи схема даёт.

### 1.4 Как сущности связаны

```
knowledge_sets ──active_version_id──▶ knowledge_versions ──▶ knowledge_units
                                            │                      ▲
                                            └──▶ entry_country_rules ┘ (regime_unit_id, reg_exempt_unit_id)
knowledge_imports ──version_id?──▶ knowledge_versions

work_calendars ──▶ work_calendar_days

contacts ──▶ stay_intervals (append-only, superseded_by)
contacts ──▶ entry_qualifications ──knowledge_version_id──▶ knowledge_versions
                    (slots JSON по kg-entry-slots/1; decision только от калькулятора)
```

---

## 2. JSON Schema слотов квалификации (`kg-entry-slots/1`)

### 2.1 Семантика состояний — KG-01

Четыре состояния у каждого слота, и схема обязана их различать:

| Состояние | Представление | Смысл |
|---|---|---|
| не спрошено | ключ **отсутствует** | бот ещё не дошёл; обязательность профиля `handoff` ловит именно это |
| неизвестно | строка `"unknown"` | спросили — клиент не знает / не ответил |
| не применимо | строка `"not_applicable"` | условие не выполнено (нет второго гражданства — паспорт въезда не нужен) |
| значение | типизированное: `true`/`false`, дата, enum, число | ответ есть |

`null` **запрещён везде** (`"type": "null"` нигде не допускается, `additionalProperties: false`) — чтобы модель не могла размыть «неизвестно» в «пусто». В Б.3 `null` используется как «пусто» — это и есть то, что мы убираем.

Для булевых слотов: `enum [true, false, "unknown", "not_applicable"]` — `false` («не было нарушений») и `"unknown"` («не знаю») не склеиваются.

### 2.2 Изменения относительно Б.3 (и почему)

| Поле Б.3 | Что сделано | Основание |
|---|---|---|
| `previous_visits.days_in_window` | **удалено** | SRC-06, CALC-02: счётчик считает только калькулятор по `stay_intervals` |
| `previous_visits.last_entry/last_exit` | заменены на `intervals[]` (черновик, упсертится в `stay_intervals`) + `history_complete` | SRC-06, AC-20 |
| `current_basis_in_kg: "visa:<type>"` | разделено на `current_basis_in_kg` enum + `current_visa_type` enum | строка с параметром не валидируется enum'ом |
| `entry_point: other_land` | добавлено `entry_point_other` (название КПП) | 2.6: другой КПП — только после подтверждения портала |
| `citizenship: ["ISO-страна"]` | ISO 3166-1 alpha-3 (`^[A-Z]{3}$`) | единый код со справочником стран; русские названия только в алиасах импорта |
| `decision.*` | `readOnly`, добавлены `rule_ids`, `knowledge_version`, `calculation_id`, `calendar_version` | CALC-01/05: результат воспроизводим и подписан версией |
| `contact.*` | допускается во входном документе, не хранится в `slots` | дубль `contacts`; меньше ПДн в JSON |
| новое `previous_kg_visas[]`, `inviting_party.contact`, `employment.has_quota/existing_ep`, `stop_factors[]` | добавлены | D5, F2, F6, F8, 4.1 — есть в вопроснике 3.3, не было в Б.3 |

Коды вопросов блока 3.3 (A1–H4) привязаны к слотам в `x-question-code` — это идентификаторы соответствия, не часть валидации (KG-02).

### 2.3 Схема

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://frunzetravel.kg/schemas/kg-entry-slots/1",
  "title": "Слоты квалификации въезда в КР",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version"],

  "$defs": {
    "unk": {"enum": ["unknown", "not_applicable"]},
    "tri_bool": {"enum": [true, false, "unknown", "not_applicable"]},
    "opt_date": {"anyOf": [{"type": "string", "format": "date", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}, {"$ref": "#/$defs/unk"}]},
    "opt_str": {"anyOf": [{"type": "string", "minLength": 1, "maxLength": 500}, {"$ref": "#/$defs/unk"}]},
    "opt_int": {"anyOf": [{"type": "integer", "minimum": 0}, {"$ref": "#/$defs/unk"}]},
    "iso3": {"type": "string", "pattern": "^[A-Z]{3}$"},
    "opt_iso3": {"anyOf": [{"$ref": "#/$defs/iso3"}, {"$ref": "#/$defs/unk"}]},
    "visa_type": {"enum": ["TS","B","TR","RL","FF","S","SW1","SW2","DN","J","M","I","R","T","A","L","D","O"]},
    "purpose": {"enum": ["tourism","private_visit","relatives_kg_citizen","family_of_foreigner","business_meeting","event","sport","medical","study","work_hire","work_individual_employer","entrepreneur","investor","it_remote","journalism","volunteer","equipment_installation","transit","religious","driver","accompanying_gcc","official"]},
    "stay_basis": {"enum": ["visa_free","visa","ep","resident_card","residence_permit","registration_contract","unknown"]},
    "interval": {
      "type": "object", "additionalProperties": false,
      "required": ["entry_date", "exit_date"],
      "properties": {
        "entry_date": {"type": "string", "format": "date"},
        "exit_date": {"anyOf": [{"type": "string", "format": "date"}, {"const": "open"}, {"const": "unknown"}]},
        "basis": {"$ref": "#/$defs/stay_basis"},
        "visa_type": {"$ref": "#/$defs/visa_type"},
        "passport_country": {"$ref": "#/$defs/iso3"},
        "evidence": {"enum": ["client_statement","passport_stamp","boarding_pass","visa_document","esuvm","crm_record"]}
      }
    }
  },

  "properties": {
    "schema_version": {"const": "kg-entry-slots/1"},

    "language": {"type": "string", "pattern": "^[a-z]{2}$", "x-question-code": "A2"},
    "contact": {
      "type": "object", "additionalProperties": false, "x-question-code": "A1,A3,A4",
      "x-persist": "dropped; contact_id is authoritative",
      "properties": {
        "name": {"type": "string", "maxLength": 200},
        "phone": {"type": "string", "pattern": "^\\+?[0-9]{7,15}$"},
        "messenger": {"enum": ["whatsapp","telegram","other"]},
        "email": {"type": "string", "format": "email"}
      }
    },
    "client_type": {"anyOf": [{"enum": ["b2c","b2b"]}, {"const": "unknown"}], "x-question-code": "A5"},
    "applicants_count": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 200}, {"const": "unknown"}], "x-question-code": "A5"},
    "pd_consent": {
      "type": "object", "additionalProperties": false, "x-question-code": "A6",
      "required": ["given"],
      "properties": {
        "given": {"$ref": "#/$defs/tri_bool"},
        "date": {"$ref": "#/$defs/opt_date"},
        "policy_version": {"type": "string", "maxLength": 32}
      }
    },

    "citizenship": {"anyOf": [{"type": "array", "minItems": 1, "maxItems": 5, "uniqueItems": true, "items": {"$ref": "#/$defs/iso3"}}, {"const": "unknown"}], "x-question-code": "B1"},
    "entry_passport_country": {"$ref": "#/$defs/opt_iso3", "x-question-code": "B2"},
    "document_type": {"anyOf": [{"enum": ["ordinary","diplomatic","service","un_lp","stateless","refugee","other","id_card","internal","unrecognized"]}, {"const": "unknown"}], "x-question-code": "B3"},
    "passport_expiry": {"$ref": "#/$defs/opt_date", "x-question-code": "B4"},
    "passport_pages_ok": {"$ref": "#/$defs/tri_bool", "x-question-code": "B5"},
    "residence_country": {"$ref": "#/$defs/opt_iso3", "x-question-code": "B6"},
    "gcc_or_brunei_residence": {"$ref": "#/$defs/tri_bool", "x-question-code": "B6"},
    "longterm_us_uk_schengen_visa": {"$ref": "#/$defs/tri_bool", "x-question-code": "B7"},

    "current_location": {"anyOf": [{"enum": ["abroad","in_kg"]}, {"const": "unknown"}], "x-question-code": "B8"},
    "in_kg_since": {"$ref": "#/$defs/opt_date", "x-question-code": "B8"},
    "in_kg_entry_point": {"anyOf": [{"enum": ["manas","osh","ak_jol","other_land"]}, {"$ref": "#/$defs/unk"}], "x-question-code": "B8"},
    "current_basis_in_kg": {"anyOf": [{"enum": ["visa_free","visa","ep","resident_card","residence_permit","registration_contract","none"]}, {"$ref": "#/$defs/unk"}], "x-question-code": "E1"},
    "current_visa_type": {"anyOf": [{"$ref": "#/$defs/visa_type"}, {"$ref": "#/$defs/unk"}], "x-question-code": "E1"},
    "current_basis_until": {"$ref": "#/$defs/opt_date", "x-question-code": "E4"},
    "current_visa_inviting_party": {"$ref": "#/$defs/opt_str", "x-question-code": "E3"},
    "registration_until": {"$ref": "#/$defs/opt_date", "x-question-code": "E2"},
    "registration_address": {"$ref": "#/$defs/opt_str", "x-question-code": "E2"},
    "residence_or_citizenship_petition_filed": {"$ref": "#/$defs/tri_bool", "x-question-code": "E5"},
    "purpose_declared_at_border": {"$ref": "#/$defs/opt_str", "x-question-code": "E6"},

    "purpose": {"anyOf": [{"$ref": "#/$defs/purpose"}, {"const": "unknown"}], "x-question-code": "C1"},
    "purpose_details": {"type": "string", "maxLength": 1000, "x-question-code": "C2"},
    "entry_date": {"$ref": "#/$defs/opt_date", "x-question-code": "C3"},
    "exit_date": {"$ref": "#/$defs/opt_date", "x-question-code": "C4"},
    "multiple_entries_needed": {"$ref": "#/$defs/tri_bool", "x-question-code": "C5"},
    "entry_point": {"anyOf": [{"enum": ["manas","osh","ak_jol","other_land"]}, {"$ref": "#/$defs/unk"}], "x-question-code": "C6"},
    "entry_point_other": {"type": "string", "maxLength": 100, "x-question-code": "C6"},
    "tickets_bought": {"$ref": "#/$defs/tri_bool", "x-question-code": "C7"},
    "accommodation_address": {"$ref": "#/$defs/opt_str", "x-question-code": "C8"},
    "urgency_deadline": {"$ref": "#/$defs/opt_date", "x-question-code": "C9"},
    "organized_group": {
      "type": "object", "additionalProperties": false, "x-question-code": "C10",
      "properties": {"is_group": {"$ref": "#/$defs/tri_bool"}, "size": {"$ref": "#/$defs/opt_int"}, "operator": {"$ref": "#/$defs/opt_str"}}
    },
    "event_dates": {
      "type": "object", "additionalProperties": false, "x-question-code": "C11",
      "properties": {"from": {"$ref": "#/$defs/opt_date"}, "to": {"$ref": "#/$defs/opt_date"}}
    },

    "previous_visits": {
      "type": "object", "additionalProperties": false, "x-question-code": "D1,D2,D5",
      "required": ["was_in_kg"],
      "properties": {
        "was_in_kg": {"$ref": "#/$defs/tri_bool"},
        "history_complete": {"$ref": "#/$defs/tri_bool"},
        "intervals": {"type": "array", "maxItems": 100, "items": {"$ref": "#/$defs/interval"},
                      "x-persist": "upsert into stay_intervals (confirmed=false unless evidence from manager)"},
        "previous_kg_visas": {"type": "array", "maxItems": 20, "items": {
          "type": "object", "additionalProperties": false,
          "properties": {"visa_type": {"$ref": "#/$defs/visa_type"}, "valid_from": {"$ref": "#/$defs/opt_date"}, "valid_to": {"$ref": "#/$defs/opt_date"}}}}
      }
    },
    "violations": {
      "type": "object", "additionalProperties": false, "x-question-code": "D3",
      "required": ["overstay", "deportation_or_ban"],
      "properties": {
        "overstay": {"$ref": "#/$defs/tri_bool"},
        "deportation_or_ban": {"$ref": "#/$defs/tri_bool"},
        "ban_until": {"$ref": "#/$defs/opt_date"},
        "fines": {"$ref": "#/$defs/tri_bool"}
      }
    },
    "previous_refusals_kg": {"$ref": "#/$defs/tri_bool", "x-question-code": "D4"},
    "previous_refusals_details": {"type": "string", "maxLength": 500, "x-question-code": "D4"},

    "inviting_party": {
      "type": "object", "additionalProperties": false, "x-question-code": "F1-F4",
      "required": ["exists"],
      "properties": {
        "exists": {"$ref": "#/$defs/tri_bool"},
        "type": {"anyOf": [{"enum": ["company","university","clinic","relative_kg_citizen","state_body","individual","tour_organization","other"]}, {"$ref": "#/$defs/unk"}]},
        "name": {"$ref": "#/$defs/opt_str"},
        "inn": {"anyOf": [{"type": "string", "pattern": "^[0-9]{14}$"}, {"$ref": "#/$defs/unk"}]},
        "contact": {"$ref": "#/$defs/opt_str"},
        "has_portal_cabinet": {"$ref": "#/$defs/tri_bool"},
        "can_issue_letter": {"$ref": "#/$defs/tri_bool"},
        "tax_debts_absent": {"$ref": "#/$defs/tri_bool"}
      }
    },
    "employment": {
      "type": "object", "additionalProperties": false, "x-question-code": "F5-F9",
      "properties": {
        "position": {"$ref": "#/$defs/opt_str"},
        "salary_kgs": {"$ref": "#/$defs/opt_int"},
        "contract_months": {"$ref": "#/$defs/opt_int"},
        "employment_form": {"anyOf": [{"enum": ["hire","individual_entrepreneur","company_head","other"]}, {"$ref": "#/$defs/unk"}]},
        "sector": {"$ref": "#/$defs/opt_str"},
        "tpp_member": {"$ref": "#/$defs/tri_bool"},
        "employer_issued_ep_before": {"$ref": "#/$defs/tri_bool"},
        "has_quota": {"$ref": "#/$defs/tri_bool"},
        "existing_ep": {"$ref": "#/$defs/tri_bool"},
        "existing_ep_until": {"$ref": "#/$defs/opt_date"}
      }
    },
    "investment": {
      "type": "object", "additionalProperties": false, "x-question-code": "F10",
      "properties": {"amount_kgs": {"$ref": "#/$defs/opt_int"}, "authority_letter": {"$ref": "#/$defs/tri_bool"}}
    },

    "family": {
      "anyOf": [
        {"type": "array", "maxItems": 20, "items": {
          "type": "object", "additionalProperties": false, "required": ["relation"],
          "properties": {
            "relation": {"enum": ["spouse","child","parent","other"]},
            "age": {"$ref": "#/$defs/opt_int"},
            "travels_together": {"$ref": "#/$defs/tri_bool"},
            "arrives_later": {"$ref": "#/$defs/tri_bool"},
            "both_parents_travel": {"$ref": "#/$defs/tri_bool"},
            "born_in_kg": {"$ref": "#/$defs/tri_bool"},
            "kg_status_of_principal": {"anyOf": [{"enum": ["ep","resident_card","residence_permit","visa","citizen","none"]}, {"$ref": "#/$defs/unk"}]},
            "documents_apostilled": {"$ref": "#/$defs/tri_bool"}
          }}},
        {"$ref": "#/$defs/unk"}
      ],
      "x-question-code": "G1-G7"
    },

    "payer": {"anyOf": [{"enum": ["self","company"]}, {"const": "unknown"}], "x-question-code": "H1"},
    "extra_services": {"type": "array", "uniqueItems": true, "items": {"enum": ["hotel","transfer","tour","tickets","insurance","registration"]}, "x-question-code": "H3"},
    "referral_source": {"type": "string", "maxLength": 200, "x-question-code": "H4"},

    "stop_factors": {
      "type": "array", "uniqueItems": true, "readOnly": true,
      "items": {"enum": ["diplomatic_or_service_passport","stateless_refugee_other_document","unrecognized_passport","overstayed_in_kg","less_than_5_wd_left","deportation_ban_or_refusal","criminal_mention","work_purpose_with_ts_b","minor_without_parents","illegal_request","group_over_5_or_b2b_or_ep","residence_or_citizenship","limit_margin_3_days_or_less"]}
    },

    "decision": {
      "type": "object", "additionalProperties": false, "readOnly": true,
      "x-writer": "calculator only (E5-03); LLM path rejected if present",
      "required": ["regime", "rule_ids", "knowledge_version", "calculation_id"],
      "properties": {
        "regime": {"enum": ["visa_free","visa_simplified","visa_general","special","escalate","insufficient_data"]},
        "visa_free_limit": {"type": "object", "additionalProperties": false, "properties": {"days": {"type": "integer"}, "window_days": {"type": "integer"}}},
        "days_remaining": {"anyOf": [{"type": "integer"}, {"const": "unknown"}]},
        "recommended_product": {"type": "string"},
        "alternatives": {"type": "array", "items": {"type": "string"}},
        "registration_needed_by": {"$ref": "#/$defs/opt_date"},
        "flags": {"type": "array", "items": {"type": "string"}},
        "escalation_reason": {"type": "string"},
        "price_quote_usd": {"type": "object", "additionalProperties": false, "properties": {"government": {"anyOf": [{"type": "number"}, {"const": "unknown"}]}, "service": {"anyOf": [{"type": "number"}, {"const": "unknown"}]}}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rule_ids": {"type": "array", "items": {"type": "string", "pattern": "^KG\\.[A-Z0-9_.]+$"}},
        "knowledge_version": {"type": "integer"},
        "calendar_version": {"type": "integer"},
        "calculation_id": {"type": "integer"},
        "not_quotable_units": {"type": "array", "items": {"type": "string"}}
      }
    }
  },

  "allOf": [
    {"if": {"properties": {"citizenship": {"type": "array", "minItems": 2}}, "required": ["citizenship"]},
     "then": {"required": ["entry_passport_country"], "properties": {"entry_passport_country": {"$ref": "#/$defs/iso3"}}}},
    {"if": {"properties": {"citizenship": {"type": "array", "maxItems": 1}}, "required": ["citizenship", "entry_passport_country"]},
     "then": {"properties": {"entry_passport_country": {"anyOf": [{"$ref": "#/$defs/iso3"}, {"const": "not_applicable"}]}}}},
    {"if": {"properties": {"current_location": {"const": "in_kg"}}, "required": ["current_location"]},
     "then": {"required": ["in_kg_since", "current_basis_in_kg"]}},
    {"if": {"properties": {"current_location": {"const": "abroad"}}, "required": ["current_location"]},
     "then": {"properties": {
        "in_kg_since": {"const": "not_applicable"}, "current_basis_in_kg": {"const": "not_applicable"},
        "current_basis_until": {"const": "not_applicable"}, "registration_until": {"const": "not_applicable"}}}},
    {"if": {"properties": {"current_basis_in_kg": {"const": "visa"}}, "required": ["current_basis_in_kg"]},
     "then": {"required": ["current_visa_type"], "properties": {"current_visa_type": {"$ref": "#/$defs/visa_type"}}}},
    {"if": {"properties": {"current_basis_in_kg": {"not": {"const": "visa"}}}, "required": ["current_basis_in_kg", "current_visa_type"]},
     "then": {"properties": {"current_visa_type": {"const": "not_applicable"}}}},
    {"if": {"properties": {"entry_point": {"const": "other_land"}}, "required": ["entry_point"]},
     "then": {"required": ["entry_point_other"]}},
    {"if": {"properties": {"previous_visits": {"properties": {"was_in_kg": {"const": true}}, "required": ["was_in_kg"]}}, "required": ["previous_visits"]},
     "then": {"properties": {"previous_visits": {"required": ["history_complete"]}}}},
    {"if": {"properties": {"previous_visits": {"properties": {"was_in_kg": {"const": false}}, "required": ["was_in_kg"]}}, "required": ["previous_visits"]},
     "then": {"properties": {"previous_visits": {"properties": {"intervals": {"maxItems": 0}}}}}},
    {"if": {"properties": {"violations": {"properties": {"deportation_or_ban": {"const": true}}, "required": ["deportation_or_ban"]}}, "required": ["violations"]},
     "then": {"properties": {"violations": {"required": ["ban_until"]}}}},
    {"if": {"properties": {"inviting_party": {"properties": {"exists": {"const": true}}, "required": ["exists"]}}, "required": ["inviting_party"]},
     "then": {"properties": {"inviting_party": {"required": ["type", "name"]}}}},
    {"if": {"properties": {"inviting_party": {"properties": {"exists": {"enum": [false, "not_applicable"]}}, "required": ["exists"]}}, "required": ["inviting_party"]},
     "then": {"properties": {"inviting_party": {"properties": {
        "type": {"const": "not_applicable"}, "name": {"const": "not_applicable"}, "inn": {"const": "not_applicable"},
        "has_portal_cabinet": {"const": "not_applicable"}}}}}},
    {"if": {"properties": {"purpose": {"enum": ["work_hire","work_individual_employer","entrepreneur"]}}, "required": ["purpose"]},
     "then": {"required": ["employment"]}},
    {"if": {"properties": {"purpose": {"const": "investor"}}, "required": ["purpose"]},
     "then": {"required": ["investment"]}}
  ]
}
```

### 2.4 Профили обязательности

Схема выше — профиль `collecting`: обязателен только `schema_version`; остальное накапливается. Профиль `handoff` (3.4, «карточка квалификации») — та же схема плюс `required`:

```
citizenship, document_type, current_location, purpose, entry_date, exit_date,
client_type, violations, previous_refusals_kg, family, previous_visits, inviting_party
```

«Заполнено» = ключ есть, значение любое допустимое (включая `"unknown"`). `inviting_party.exists` при `purpose ∈ {tourism, transit}` может быть `"not_applicable"`. Стоп-фактор (4.1) передаёт карточку **не** в профиле `handoff` — неполная карточка уходит как есть со `stop_factors[]` (KG-01).

### 2.5 Семантические проверки вне JSON Schema (домен, при записи)

JSON Schema не сравнивает поля между собой. Эти проверки делает доменный слой при `save_slots`:

| # | Проверка | Реакция |
|---|---|---|
| S1 | `exit_date >= entry_date`, если обе даты известны | отказ записи с указанием поля |
| S2 | `entry_passport_country ∈ citizenship`, если оба известны | отказ |
| S3 | `passport_expiry` в прошлом | не отказ — флаг `passport_expired` в `stop_factors` |
| S4 | интервалы: `exit_date >= entry_date`, не более одного `open` | отказ |
| S5 | `gcc_or_brunei_residence` задано (не `not_applicable`) только если гражданство из `KG.VR.SIMPLIFIED_GCC_RESIDENT`-списка активной версии | предупреждение в отчёт, значение сохраняется (правило может измениться) |
| S6 | `longterm_us_uk_schengen_visa` — аналогично для CHN/IND | предупреждение |
| S7 | `decision` присутствует и `updated_by != 'calculator'` | отказ |
| S8 | `contact.*` в документе | отбрасывается, в `slots` не пишется |
| S9 | ISO3 в `citizenship` нет в справочнике стран активной версии | отказ: `unknown_country` |

---

## 3. Схема правил въезда

### 3.1 Единица знания — виды (`kind`) и схема `value`

Каждая единица `knowledge_units` имеет `kind`; `value` валидируется JSON Schema своего вида (реестр схем в коде, версия в `value_schema_version`). Единица — это **одно утверждение с одним источником**, а не «вся группа стран» (KB-03: «для каждого значения отдельная метка»).

| `kind` | ID-префикс | `value` | Откуда в KB |
|---|---|---|---|
| `visa_free_regime` | `KG.VF.<GROUP>` | `{days, window_days, work_needs_unified_permit, countries: [iso3…]}` | Б.5 `visa_free.*`, 2.2 |
| `registration_exemption` | `KG.REG.EXEMPT.<ISO3>` | `{days}` — **на страну** | 2.10 (Перечень ПР-600), не группа Б.5 |
| `registration_default` | `KG.REG.DEFAULT` | `{deadline_working_days_from_border: 5}` | Б.5, ЗВМ ст.6 |
| `registration_term` | `KG.REG.TERM.<ISO3>` | `{days}` (на сколько оформляется — отличать от освобождения) | 2.10 п.28 |
| `special_regime` | `KG.SP.<CODE>` | `{days, reentry_after_days?, visa_inside_kg?, requires?, applies_to: {countries?|document_type?|condition}}` | Б.5 `special.*`, 2.5 |
| `visa_required_regime` | `KG.VR.<CODE>` | `{procedure: simplified|general, scope: all_types|business_tourist|tourist_gcc_resident|null, gknb_approval: bool, countries: [...]|"all_others"}` | Б.5 `visa_required.*`, 2.4 |
| `rule_param` | `KG.RULE.<NAME>` | `{value, unit: days|working_days|calendar_days|bool|list, anchor?, inclusive?}` | Б.5 `rules.*` |
| `deadline` | `KG.DL.<NAME>` | `{value, unit: hours|calendar_days|working_days|months, anchor, direction: before|after, timezone: "Asia/Bishkek", boundary_inclusive, shift_from_nonworking: none|next_working|previous_working}` | 13.2, 18.11 |
| `processing_time` | `KG.PT.<PRODUCT>` | `{standard_wd, urgent_wd?, urgent_multiplier?, anchor: full_package}` | 13.1 |
| `tariff` | `KG.FEE.<KIND>.<PRODUCT>` | `{amount, currency, per: person|application, component: service|government|bank|partner}` | 0.5, 12.x; SRC-03 → `decision_pending` |
| `template` | `KG.TPL.<CODE>` | `{lang, text, placeholders: [...]}` | Прил. А; SRC-07/08 — без чисел внутри текста |
| `escalation_trigger` | `KG.ESC.<CODE>` | `{condition, action}` | 4.1, Б.6 |

Три поля, которые делают единицу **котируемой** клиенту (точный ответ), вычисляются при чтении, не хранятся:

```
quotable(unit, today) =
      unit.confirmation_status == 'confirmed'
  and unit.label in ('none')                    # practice — внутренне; verify/decision — нет
  and (unit.effective_from is null or unit.effective_from <= today)
  and (unit.effective_to   is null or unit.effective_to   >= today)
  and (unit.review_due_at  is null or unit.review_due_at  >= today)
  and unit.conflict_ref is null
```

`entry_country_rules.quotable` — материализация этого на дату активации; калькулятор обязан пересчитать по `today` (просрочка `review_due_at` наступает после активации). Некотируемая единица → калькулятор возвращает `insufficient_data`/`escalate` с `not_quotable_units`, остальные единицы продолжают работать (KB-04, AC-18).

### 3.2 SRC-04 — Молдова

Единица `KG.REG.EXEMPT.MDA`:

```yaml
- unit_id: KG.REG.EXEMPT.MDA
  kind: registration_exemption
  section: "2.10"
  page: "24-25"
  source_ref: "ПР-600 прил.2 — страны нет в Перечне"
  label: none
  confirmation_status: blocked
  value: null                      # CHECK: blocked ⇒ value IS NULL
  blocked_value:
    source_value: {days: 90}
    source_locations: ["Б.5 с.88 visa_free.ninety_180.registration_exempt_days", "2.2 с.20 строка Молдовы"]
    contradicts: "2.10 с.24-25: Молдовы в Перечне нет → 5 р.д. по ЗВМ ст.6"
  conflict_ref: SRC-04
  owner: visa_kb_owner
  review_due_at: null              # до решения — бессрочно заблокировано
```

Следствие для `entry_country_rules` (MDA, ordinary): `regime_kind=visa_free`, `visa_free_days=90`, `window_days=180` (режим 90/180 с 23.09.2026 **не** заблокирован — конфликт только по регистрации), `reg_exempt_unit_id → KG.REG.EXEMPT.MDA`, `reg_exempt_days=NULL`, `reg_exempt_status='blocked'`, `quotable=false`. Калькулятор по Молдове отвечает про безвиз, но по регистрации — только «уточнит менеджер» (AC-18). Когда Гриша подтвердит значение, новая версия базы меняет статус единицы на `confirmed` (или `value: {days: N}`), `conflict_ref` снимается; старая версия остаётся для аудита.

Тот же механизм закрывает SRC-03 (`KG.FEE.SERVICE.SW1` → `decision_pending`, оба источника в `blocked_value.source_locations`) и строки `[ПРОВЕРИТЬ]` блока 2.2 (Таджикистан/Азербайджан/Грузия 60/120, Туркменистан, Куба/КНДР) → `needs_verification`.

### 3.3 SRC-05 — Греция и Чили

Освобождение от регистрации хранится **по странам** из перечня 2.10, а не как «группа + исключения». Греция и Чили — обычные единицы:

```yaml
- {unit_id: KG.REG.EXEMPT.GRC, kind: registration_exemption, value: {days: 90}, section: "2.10", page: "24-25", source_ref: "ПР-600 прил.2", label: none, confirmation_status: confirmed}
- {unit_id: KG.REG.EXEMPT.CHL, kind: registration_exemption, value: {days: 60}, section: "2.10", page: "24-25", source_ref: "ПР-600 прил.2", label: none, confirmation_status: confirmed}
```

Группа Б.5 `annex1_30_60.registration_exempt_days: 30` в импорт **не попадает** — она производная и уже один раз спрятала исключения. Если E5-01 всё же передаёт данные в форме Б.5 (группа + `registration_exempt_days_exceptions`), конвертер раскатывает их в единицы на страну и **падает**, если ключ `registration_exempt_days_exceptions` отсутствует при наличии `registration_exempt_days` у группы с ≥2 странами (нельзя молча принять «у всех одинаково»).

Два правила импорта, чтобы это не повторилось:

1. **Lint комментариев.** Inline-комментарий (`#` после значения на той же строке) в `units.yaml` → отказ импорта `syntax: inline comment carries data? units.yaml:143`. Комментарии разрешены только отдельной строкой. Это грубо, но дешевле, чем ещё один SRC-05.
2. **Полнота перечня.** Для каждой страны из `visa_free_regime.countries` обязана существовать единица `KG.REG.EXEMPT.<ISO3>` (любого статуса) **или** страна явно перечислена в `KG.REG.DEFAULT.value.not_in_list`. Иначе отказ `semantic: no registration rule for TJK`.

### 3.4 SRC-06 — интервалы

См. `stay_intervals` в §1.3. Ключевые решения:

- Интервалы — **факты о человеке** (`contact_id`), не поле квалификации: клиент может прийти второй раз через год, и история нужна та же.
- Слот `previous_visits.intervals[]` — черновик от бота; при сохранении превращается в строки `confirmed=false, evidence=client_statement, entered_by=bot`. Подтверждает менеджер (по штампам/ЕСУВМ) — `confirmed=true, confirmed_by`.
- `history_complete` — отдельный tri-слот: без `true` калькулятор не даёт точного остатка (AC-20), только «не менее N дней использовано».
- Открытый интервал (`exit_date IS NULL`) — «сейчас в КР»; он один. Смена паспорта → новый интервал с другим `passport_country_iso3`/`passport_label`, калькулятор видит смену основания/паспорта и помечает расчёт неполным (AC-20).
- Исправления только через `superseded_by` — цепочка видна в аудите, расчёт прошлой даты воспроизводим по множеству `id`, которые он сохранил.

### 3.5 Формат файла импорта (бандл)

Канонический формат — **плоский список единиц**, а не вложенный YAML Б.5. Б.5 — исходник для E5-01; конвертация в бандл — одноразовый скрипт E5-02 с таблицей соответствия ниже. Бандл — каталог:

```
kg_entry_2026-10-02/
  meta.yaml        # set_code, version_label, source_document, source_hash, prepared_by, prepared_at, effective_from?
  countries.yaml   # алиасы: {"Россия": RUS, "Республика Корея": KOR, "Босния и Герцеговина": BIH, "Гонконг": HKG, ...}
  units.yaml       # список единиц (§3.1); порядок не важен; unit_id уникален
```

Соответствие Б.5 → единицы:

| Ключ Б.5 | Единица |
|---|---|
| `visa_free.eaeu` … `visa_free.cis_bilateral` | `KG.VF.EAEU`, `KG.VF.UZB`, `KG.VF.NINETY_180`, `KG.VF.ANNEX1_30_60`, `KG.VF.GCC`, `KG.VF.CIS_BILATERAL` (последняя — `needs_verification`, метка `[ПРОВЕРИТЬ]` в источнике) |
| `visa_free.other_check_portal` | `KG.VF.MDV` (30, confirmed по порталу), `KG.VF.MYS` (needs_verification), `KG.VF.CUB`, `KG.VF.PRK` (needs_verification, `value.days: null` недопустим → `blocked_value` с `note`) |
| `*.registration_exempt_days` (любой формы) | **не импортируется**; источник — 2.10 построчно → `KG.REG.EXEMPT.<ISO3>` |
| `uzbekistan.registration_term_days` | `KG.REG.TERM.UZB` = 60; аналогично `KG.REG.TERM.MDA` = 90 (п.28 — это **срок регистрации**, не освобождение; не путать с SRC-04) |
| `uzbekistan.watch` | `KG.VF.UZB` поле `watch` → отдельная единица `KG.WATCH.UZB_15DAYS` kind `rule_param`, `needs_verification`, `review_due_at` ежемесячно (Г.3 п.21) |
| `special.*` | `KG.SP.HK_MACAO`, `KG.SP.UN_LP`, `KG.SP.CHN_IND_LONGTERM_VISA`, `KG.SP.CHN_TOUR_GROUP` |
| `visa_required.simplified_annex2_no_gknb.*` | `KG.VR.SIMPLIFIED_ALL`, `KG.VR.SIMPLIFIED_IRN_B_TS`, `KG.VR.SIMPLIFIED_GCC_RESIDENT_TS` |
| `visa_required.general_procedure_with_gknb` | `KG.VR.GENERAL` (`countries: "all_others"`) |
| `rules.*` (10 ключей) | `KG.RULE.VISA_INSIDE_KG_FORBIDDEN`, `KG.RULE.EVISA_ENTRY_POINTS`, `KG.RULE.MULTIPLE_ENTRY_OVER_DAYS`, `KG.RULE.EXTENSION_MIN_WD`, `KG.RULE.EP_MIN_WD_BEFORE_VF_END`, `KG.RULE.RC_MIN_WD_BEFORE_EP_END`, `KG.RULE.NEW_EP_MIN_WD_BEFORE_RC_END`, `KG.RULE.OVERSTAY_BAN`, `KG.RULE.REG_DOES_NOT_EXTEND_VF`, `KG.RULE.NO_REG_LAST_DAYS` |
| 13.2 (22 строки) | `KG.DL.*` по одной на строку, с `anchor` и `unit` из колонки «Значение» |
| 13.1 (10 строк) | `KG.PT.*` |
| 0.5 / 12.6 | `KG.FEE.SERVICE.TS`, `.B`, `.EP` — confirmed; остальные — `decision_pending` (DEC-01, SRC-03) |

Параметры счёта дней, которые **ещё не утверждены** на эталонах (CALC-02): `KG.RULE.COUNT_ENTRY_DAY` (П-541 п.10 — день пересечения считается с 00:01, т.е. включается), `KG.RULE.COUNT_EXIT_DAY`, `KG.RULE.WINDOW_ANCHOR` (окно смотрится назад от каждого дня планируемого пребывания). Импортируются как `decision_pending` до подписи владельца базы — калькулятор без них не считает точный остаток. Это осознанно: лучше «уточнит менеджер», чем уверенный неверный остаток.

### 3.6 Пример единицы с полным набором полей KB-03

```yaml
- unit_id: KG.VF.ANNEX1_30_60
  kind: visa_free_regime
  title: "Безвиз 30/60 для стран приложения 1 П-541"
  section: "2.2, 2.3"
  page: "19-22"
  source_ref: "П-541 п.13 (ред. 07.09.2026), приложение 1"
  source_text: "30 дней в каждом 60-дневном периоде (с 31.12.2025, раньше было 60/120)"
  label: none
  confirmation_status: confirmed
  effective_from: 2025-12-31
  effective_to: null              # неизвестно — не выдумывать (KB-03); Г.1 п.12 — следить с ноября
  verified_at: 2026-10-02
  verified_by: kb_author
  review_due_at: 2026-11-02       # review_period_days набора = 30 (DEC-07 — подтвердить)
  owner: visa_kb_owner
  value_schema_version: 1
  value:
    days: 30
    window_days: 60
    work_needs_unified_permit: true
    countries: [AUS, AUT, ALB, AND, ARG, BEL, BGR, BIH, BRA, BRN, VAT, GBR, HUN, VNM, DEU, GRC, DNK,
                ISR, IRL, ISL, ESP, ITA, CAN, CYP, LVA, LTU, LIE, LUX, MLT, MEX, MCO, NLD, NZL, NOR,
                POL, PRT, KOR, ROU, SMR, MKD, SGP, SVK, SVN, USA, THA, FIN, FRA, HRV, MNE, CZE, CHL,
                CHE, SWE, EST, JPN]
```

---

## 4. Публикация и атомарная активация (KB-04, AC-22)

```
import (bundle) ──► draft ──review──► review ──approve──► approved ──activate──► active ──► retired
                      │                 │
                      └────reject───────┴──► rejected
```

| Операция | Кто (роль, права — E1-02/E6-01) | Что делает | Транзакция |
|---|---|---|---|
| `import_bundle` | admin / kb_owner | §5 | одна; при любом отказе — ничего не вставлено, кроме строки `knowledge_imports` |
| `submit_for_review` | kb_owner | `draft→review`; отчёт сравнения с активной версией: добавлено/изменено/удалено по `unit_id`, список единиц, изменивших `quotable` | одна |
| `approve` | утверждающий (DEC-07; **не тот же**, кто готовил бандл — проверка `approved_by != source_prepared_by`) | `review→approved`, `approved_by/at`; единицы версии становятся неизменяемыми | одна |
| `activate_version(set_id, version_id, expected_active_id)` | admin | `UPDATE knowledge_sets SET active_version_id=:new WHERE id=:set AND active_version_id IS NOT DISTINCT FROM :expected` → если 0 строк — конфликт `active_changed`; затем `old.status='retired', retired_at`, `new.status='active', activated_at`; событие `knowledge_version_activated` с обоими id | **одна транзакция**; читатели берут `active_version_id` один раз на расчёт и записывают его в результат |
| `rollback_to(set_id, version_id)` | admin | это `activate_version` на **прежнюю** версию: `retired→active` разрешён только этой операцией, с причиной; новая версия → `retired`. Ничего не удаляется (AC-22) | одна |
| `list_affected_cases(old, new)` | kb_owner | по `entry_qualifications.knowledge_version_id = old` и единицам с изменившимся `value`/`quotable` — список дел для показа; подтверждённые суммы/даты в делах **не переписываются** (KB-04) | чтение |

Почему `retired→active` допустим: откат — штатный сценарий AC-22. Запрещено только переиспользовать номер версии и менять содержимое утверждённой.

Просрочка без переключения версии: `review_due_at < today` у единицы → `quotable=false` при чтении; ничего не ломается, единица просто уходит в «уточнит менеджер», а в утренний бриф (`morning_brief.py`, флаг) попадает список просроченных — отдельная задача, здесь только поле.

---

## 5. Импорт с отказом на повреждённых данных (AC-23)

Порядок строго такой; **первый** провал останавливает всё, запись в БД — только в `knowledge_imports`:

| Этап | Проверка | Адрес ошибки в отчёте | Пример отказа |
|---|---|---|---|
| 0 `bundle` | каталог содержит ровно `meta.yaml`, `countries.yaml`, `units.yaml`; `source_hash` в meta совпадает с sha256 исходного KB | имя файла | `bundle: units.yaml missing` |
| 1 `syntax` | `yaml.safe_load` каждого файла; JSON (если бандл в JSON) — `json.loads`; lint inline-комментариев (§3.3) | `file:line:col` из `yaml.Mark` | `syntax: units.yaml:143:7 mapping values are not allowed here` |
| 2 `schema` | каждая единица — по JSON Schema «оболочки» (обязательные поля KB-03, enum `kind/label/confirmation_status`) и по схеме `value` своего `kind`; `countries.yaml` — `{str: iso3}`; `meta.yaml` — своя схема | JSON pointer: `/units/17/value/days` | `schema: /units/17/label — 'VERIFY' is not one of [none, verify, practice, decision]` (неизвестная метка) |
| 3 `semantic` | уникальность `unit_id`; все названия стран в `value.countries` есть в `countries.yaml`; ISO3 валидны; `blocked ⇒ value null ∧ blocked_value ∧ conflict_ref`; `effective_to ≥ effective_from`; полнота перечня регистрации (§3.3 п.2); у `tariff` с `decision_pending` нет `value.amount`; каждая `deadline` имеет `anchor` и `unit`; «потерянная колонка» — отсутствие обязательного поля единицы ловится здесь же | `unit_id` + поле | `semantic: KG.REG.EXEMPT.TJK missing; KG.VF.CIS_BILATERAL lists TJK` |
| 4 `db` | одна транзакция: `INSERT knowledge_versions(status=draft)` → `INSERT knowledge_units[*]` → построение `entry_country_rules` → `INSERT knowledge_imports(result=accepted)`; откат при любом исключении | — | нарушение UNIQUE при гонке двух импортов → rollback, `rejected: db` |

Инварианты импорта:

- **Активная версия не читается и не пишется** импортом вообще. Единственное, что он знает об активной — её номер, чтобы дать черновику `version = max+1`.
- Повторный импорт того же `bundle_hash` при живом `draft` → вернуть этот draft (идемпотентность), не плодить версии.
- Отчёт импорта (`knowledge_imports.report`) содержит счётчики по `kind` и по `confirmation_status` — чтобы на ревью видеть «84 confirmed, 9 needs_verification, 2 blocked, 5 decision_pending», а не верить словам.
- Импорт **не исправляет** данные (никаких «автопочинок» формата): сломано — отказ с адресом. Исправление формата ≠ подтверждение смысла (KB-02).

Отказ импорта календаря — тот же конвейер с своими схемами (`calendar-<year>.yaml`: `{jurisdiction, year, week_rest_days, completeness, days: [{day, is_working, kind, title, source_ref}]}`), своя таблица результата не нужна — пишем в `knowledge_imports` с `set_id` NULL и `report.kind='calendar'`.

---

## 6. Миграция `e5_knowledge_0008` и обратимость

**Границы дифа реализации (объявляю заранее):** `alembic/versions/e5_knowledge_0008.py` (новый), `app/domain/models.py` (девять классов рядом с E1-01), `app/domain/knowledge.py` (операции §4) и `app/domain/knowledge_import.py` (§5) — новые, `app/domain/slots_schema.json` (§2.3) — новый, тесты `tests/test_knowledge_*.py`, `tests/test_alembic_domain_migration.py` (расширить). Ничего в `app/core/`, `app/agent/`, `app/admin/` — это E5-03/E5-04.

Правила миграции — те же, что выстраданы в E1-01:

1. **Только `CREATE TABLE`**, ни одного `ALTER` существующей таблицы. `applicant_id` в `stay_intervals` создаётся сразу как nullable `Integer` **без FK** — FK добавит E6-01, когда появится `applicants`.
2. **Без импорта кода приложения.** Enum-значения (`kind`, `status`, `label`, `confirmation_status`, `regime_kind`, `evidence`, `basis`, `day kind`) выписаны литералами в CHECK — снимок на дату ревизии.
3. **Порядок создания** (встречные FK как в E1-01): `knowledge_versions` → `knowledge_sets` (составной FK на версии) → `knowledge_units` → `entry_country_rules` → `knowledge_imports` → `work_calendars` → `work_calendar_days` → `stay_intervals` → `entry_qualifications`. `downgrade` — строго обратный порядок `drop_table`.
4. **Сидера в миграции нет.** Набор `kg_entry`, версии, календарь — только через `import_bundle` отдельным скриптом (`scripts/kb_import.py`, вызов руками, как `sales_reconcile.py`).
5. **Partial unique index** (одна активная версия, один открытый интервал, один активный календарь на год) — `op.create_index(..., postgresql_where=..., sqlite_where=...)`; обе СУБД поддерживают, гейт по PG16 обязателен (как у E1-01).
6. **JSON остаётся `json`.** Поиск по полям `value` не нужен: все выборки идут по `entry_country_rules` (страна × документ × версия) и по `unit_id`. Если позже понадобится ad-hoc поиск внутри `value` — это отдельная миграция с `jsonb` + GIN **только для `knowledge_units.value`**, остальные JSON-колонки payload. Говорю это сейчас, чтобы не всплыло после первой миграции.
7. **Доказательство обратимости**: `upgrade → downgrade → upgrade` на SQLite и на PG16-копии; после `downgrade` в `information_schema.tables` нет ни одной из девяти таблиц, существующие 4 таблицы E1-01 и всё до них — без изменений (`pg_dump --schema-only` до/после побайтно). Тест — расширение `tests/test_alembic_domain_migration.py`.
8. **Поведение для клиента не меняется**: таблицы никем не читаются до E5-03/E5-04, которые придут за флагом (`kg_entry_rules_enabled`, дефолт OFF). Самой миграции флаг не нужен.
9. **Откат на проде** — `rollback_prod.sh` на коммит до миграции + `alembic downgrade e1_services_0007`; данных в таблицах к тому моменту нет (сидер отдельный), потерь нет.

Класс риска реализации: карточка говорит STANDARD; миграция на проде без данных — остаётся STANDARD с гейтом `prod_traps_check --diff-base HEAD` и PG16-прогоном. Первый **импорт реального бандла на прод** и первая **активация** версии — CRITICAL (прод-данные, с которых будет считать калькулятор): `codex-reviewer` + решение Алана.

---

## 7. Что сознательно не делается

- Не хранятся суммы/сроки в промпте — промпт E5-04 получает `decision` калькулятора и `not_quotable_units`.
- Не вводится `visa_inbound` в `products.direction`. Если E6-01 решит привязать `service_cases` к въездным продуктам, это его `direction` и его CHECK.
- Не проектируются калькуляторы (E5-03): здесь только то, что они читают и куда пишут ссылки.
- Не проектируется UI «Знания» (technical-design §4 экран «Знания») — только данные под сравнение черновика с активной (`unit_id` стабилен именно ради этого).
- История правок `slots` не хранится отдельной таблицей: воспроизводимость даёт `Calculation.input_snapshot` (E5-03) + `revision`. Записано как долг на случай, если аудит потребует «кто и когда менял слот».
- `template` (прил. А) — вид единицы предусмотрен, но наполнение и сборка шаблонов по результату правил (SRC-07/08) — E5-04.

---

## 8. Вопросы Алану и Грише до реализации

Без ответа — реализация идёт на синтетике, спорные единицы импортируются как `needs_verification`/`decision_pending` и клиенту не котируются. Ни один вопрос не блокирует миграцию.

| # | Вопрос | Кому | Что зависит | Предложение по умолчанию |
|---|---|---|---|---|
| Q1 | DEC-07: кто `owner` единиц, кто `approved_by`, какой `review_period_days`? Правило «утверждает не тот, кто готовил» — принимаем? | Гриша + Алан | `quotable`, §4 `approve` | owner = визовый отдел (роль `visa_kb_owner`), утверждает Гриша, 30 дней (Г.2 п.19 «ежемесячно») |
| Q2 | Молдова (SRC-04): какое значение верно — «нет в Перечне, 5 р.д.» (2.10) или 90 (Б.5/2.2)? Нужен первоисточник ПР-600 прил.2 в текущей редакции | Гриша | `KG.REG.EXEMPT.MDA` | до ответа — `blocked`, по регистрации Молдовы бот не отвечает точно |
| Q3 | Таджикистан/Азербайджан/Грузия 60/120 — подтверждено по тексту ПКМ № 437/600? (Г.1 п.5) | Гриша | `KG.VF.CIS_BILATERAL` | `needs_verification`: бот говорит «безвиз, срок уточнит менеджер» |
| Q4 | Включение дня въезда/выезда и якорь окна (CALC-02): подписать 5–10 эталонных примеров (США 30/60, РФ 90/180, пересечение интервалов, открытый интервал) | Гриша | `KG.RULE.COUNT_*`, E5-03 | предложу эталоны в E5-03; до подписи — `decision_pending`, точный остаток не выдаётся |
| Q5 | Производственный календарь КР 2026 и 2027: кто источник (постановление кабмина о переносах; даты Орозо/Курман айт — по объявлению ДУМК/правительства)? Кто вносит плавающие даты, когда объявят? | Алан | `work_calendars`, AC-21 | 2026 — из постановления о переносах выходных; 2027 — `provisional` до объявления |
| Q6 | Для госоргана считаем неделю пн–пт (сб–вс нерабочие) — так? (Офис пн–сб — не он.) | Гриша | `week_rest_days` | `[6,7]` |
| Q7 | Хранение `stay_intervals` и слотов с паспортными датами — попадает под DEC-06 (ПДн)? Срок хранения после закрытия дела? | Алан + руководство | ретеншн, экспорт | не хранить номер паспорта вообще (только `passport_label`); ретеншн — отдельным решением DEC-06 |
| Q8 | Бот может **сам** создавать `stay_intervals` со слов клиента (`confirmed=false`) или только менеджер? | Алан | §1.3, E5-04 | может, с `evidence=client_statement`; в расчёт такие интервалы входят как «не менее», не как точный остаток |
| Q9 | Страны вне любого списка (Афганистан, Нигерия…) — бот отвечает «общий порядок, виза + ГКНБ» сам или сразу менеджеру? | Гриша | `KG.VR.GENERAL`, флаг `country_not_listed` | отвечает «виза по общему порядку», детали — менеджер (блок 15: высокий риск отказа) |
| Q10 | Дип/служебные паспорта: заводить строки `entry_country_rules` с `document_type=diplomatic/service` сейчас (данных почти нет, 2.7 — `[ПРОВЕРИТЬ]`) или только `ordinary`? | Гриша | объём импорта | только `ordinary`; дип/служебный — стоп-фактор 4.1, менеджер |
| Q11 | Первый импорт на прод и первая активация — CRITICAL с ревью Codex и твоим словом. Согласен с таким делением (миграция — STANDARD, данные — CRITICAL)? | Алан | §6 | да |

---

## 9. Главный риск схемы

**Две правды о поездках.** Слот `previous_visits.intervals[]` (черновик от бота) и таблица `stay_intervals` (факт) — если реализация хоть где-то посчитает остаток по слоту, минуя таблицу, SRC-06 вернётся в новой обёртке. Защита заложена три раза: `days_in_window` из схемы удалён; `decision` пишет только калькулятор (S7); интервалы со слов клиента всегда `confirmed=false`. Но это защита в домене, не в БД — ревью E5-03 обязано проверить, что калькулятор читает **только** `stay_intervals` и ни одного поля `slots` по датам поездок.

Второй по весу — **ISO3-алиасы**: KB целиком на русских названиях («Республика Корея», «Босния и Герцеговина», «Бруней-Даруссалам» в 2.3 против «Бруней» в Б.5). Ошибка алиаса тихо отправляет страну в «общий порядок». Поэтому неизвестное название — отказ импорта, а не пропуск, и `countries.yaml` ревьюится глазами как часть бандла.

---

## Доказательства по этому документу

- Что сделано: один новый файл `docs/e5-02-slots-schema.md`; код, тесты, миграции, приложение — не тронуты.
- Чем проверено: прочитаны Б.3 (с. 3243–3299), Б.5 (с. 3320–3406), блок 2 (с. 801–1023), блок 13 (с. 2252–2327), 18.4–18.5, 18.11 KB v1.1; ТЗ §8–9, §16, §17, §20; карточка E5-02; `models.py` 440–674, `e1_services_0007.py` целиком; technical-design §2. JSON Schema §2.3 — прогнана валидатором (ниже); профиль `handoff` (§2.4) как отдельная схема не собирался — это делает Sonnet первым шагом.
- Валидатор (jsonschema 4.26, Draft 2020-12, во временном окружении вне проекта): `check_schema` OK; 10 образцов (пустой, `collecting` «за рубежом», `in_kg` без даты, два гражданства без паспорта въезда, `null`, лишний ключ `days_in_window`, запрет без `ban_until`, виза без типа, виза с типом, `was_in_kg=false` с интервалами) — 10/10 ожидаемых вердиктов. Первый прогон дал 9/10: `oneOf` в `opt_str` ломался на `"not_applicable"` (строка подходит под обе ветки) — заменено на `anyOf` по всей схеме.
- Что осталось непроверенным: применимость `postgresql_where`/`sqlite_where` partial-индексов в текущем alembic-окружении (ожидаю PASS по опыту E1-01, но не мерил); совместимость `if/then` с `oneOf`-обёртками `unknown` на реальных документах от LLM — проверится на синтетике в E5-04.
