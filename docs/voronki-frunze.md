# Воронки бота Frunze Travel

Три воронки: **Туры**, **Визы**, **Билеты**. Каждый бот привязан к своей воронке
жёстко (через `scenario` в конфиге) — тур-бот не угадывает воронку по словам.
Боевой режим — живой AI-диалог (OpenRouter, tool-use, `app/agent/runner.py`); без
LLM-ключа работает детерминированный fallback-опросник (тесты/офлайн-демо).

Источник: `app/funnels/*.py`, `app/agent/runner.py`. Стиль — `docs/frunze-dialog-style.md`.

---

## Общая механика

- **Состояние диалога** копится в `DialogState.qualification` (собранные поля),
  `stage` (этап), `deal_id` (сделка в CRM). Ключ — `<bot_id>:<phone>` (раздельно на бота).
- **Лид в CRM** создаётся при первом значимом действии (`create_lead`), дальше
  сделка двигается по канбану (`update_stage`).
- **Передача менеджеру = бот замолкает** (`stage=manager`, `intercepted=true`).
  Прощальную реплику бот ещё шлёт, дальше отвечает человек. Вернуть боту — из админки.
- **Цены бот не называет** — `PRICE_DISCLAIMER`, везде ведём к менеджеру/консультации.

Внутренние стадии → передаются в `crm.update_stage(...)`:
`visa_scoring`, `office_consultation`, `manager_handoff`.

---

## 1. Туры (бренд Frunze Travel)

**Цель:** собрать параметры тура → подбор через TourVisor → довести до брони/менеджера.

**Этапы:** `greeting → qualification → search (TourVisor) → branch (office | manager)`

**Собираемые поля** (`REQUIRED_FIELDS`, порядок как у живых менеджеров):

| Поле | Вопрос |
|---|---|
| `destination` | Какое направление рассматриваете? (страна или «помогите выбрать») |
| `tourists` | Сколько человек едет — взрослые/дети? |
| `dates` | На какие даты ориентируетесь? |
| `budget` | На какой бюджет рассчитываете? |
| `departure_city` | Откуда вылет — Бишкек или Алматы? |
| `hotel_stars` | Звёздность отеля? (3*, 4*, 5*) |
| `meal` | Питание? (завтраки, всё включено…) |

**AI-инструменты:** `search_tours`, `handoff_to_manager`, `escalate_to_office`
- `search_tours` → дёргает TourVisor; если недоступен — запрос записан, ведём к менеджеру.
- `escalate_to_office` → `stage=office`, CRM `office_consultation` (приглашение в офис).
- `handoff_to_manager` → `stage=manager`, CRM `manager_handoff` (передача человеку).

---

## 2. Визы (бренд GetVisa, менеджер «Медина»)

**Цель:** довести клиента до **консультации эксперта**. БЕЗ обещаний по визе,
БЕЗ озвучивания процента и цен.

**Этапы:** `приветствие → опросник → мягкая честная подача → приглашение в офис/онлайн → CRM`

**Собираемые поля** (`REQUIRED_FIELDS`, опросник Медины):

| Поле | Вопрос |
|---|---|
| `name` | Как могу к вам обращаться? (Медина представляется) |
| `country` | Виза в какую страну? |
| `age` | Сколько вам лет? |
| `marital_status` | Семейное положение (брак, дети)? |
| `occupation` | Кем работаете / где учитесь? |
| `prior_countries` | Какие страны посещали ранее? |
| `companions` | Один(одна) или с семьёй? |
| `english_level` | Английский — свободно / базово / нет? |
| `dates` | Даты поездки? |
| `prior_refusal` | Были ли отказы в визе? (страна, год) |

**AI-инструменты:** `score_visa`, `escalate_to_office`, `handoff_to_manager`
- `score_visa` → внутренняя оценка силы кейса (высокие/средние/низкие). **Это только
  ориентир для ТОНА** ответа — клиенту процент НЕ показываем, визу НЕ обещаем.
  CRM `visa_scoring`.
- `escalate_to_office` → приглашение на консультацию (офис `GETVISA_OFFICE_ADDRESS`
  или онлайн; документы на `GETVISA_EMAIL`). CRM `office_consultation`.
- `handoff_to_manager` → передача человеку. CRM `manager_handoff`.

> Эвристика `score_visa` (0–100): база 50; +15 за историю поездок; +15 если не было
> отказов (иначе −15); +5 за занятость. → ≥70 «высокие», ≥45 «средние», иначе «низкие».
> Методика заказчиком не утверждена — это внутренняя эвристика, не обещание.

---

## 3. Билеты (бренд Frunze Travel, авиабилеты)

**Цель:** собрать заявку на перелёт и передать менеджеру на подбор рейса и оплату.
Живые тарифы бот НЕ тянет (нет GDS) — цену называет менеджер.

**Этапы:** `qualification → submit_request → manager`

**Собираемые поля** (`REQUIRED_FIELDS`):

| Поле | Вопрос |
|---|---|
| `route` | Откуда и куда летим? |
| `dates` | На какие числа — туда и обратно? |
| `passengers` | Сколько пассажиров? |
| `direct_pref` | Прямой рейс или можно с пересадкой? |

**AI-инструмент:** `submit_request` → создаёт лид, CRM `manager_handoff`,
`stage=manager`. Менеджер подбирает рейс (прямой/пересадка, багаж, питание) и шлёт цену.

---

## Сводка стадий CRM по воронкам

| Воронка | Инструменты | Стадии CRM (`update_stage`) |
|---|---|---|
| Туры | search_tours, escalate_to_office, handoff_to_manager | office_consultation, manager_handoff |
| Визы | score_visa, escalate_to_office, handoff_to_manager | visa_scoring, office_consultation, manager_handoff |
| Билеты | submit_request | manager_handoff |

Эти строки-стадии маппятся на реальные `STAGE_ID` канбана Bitrix через
`BITRIX_STAGE_MAP` (заполняется ID от заказчика — см. `docs/debug-session-bot-molchit-2026-06-23.md`).
