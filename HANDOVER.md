# Frunze Travel Bot — сводный документ (handover)

> Один документ для быстрого старта и передачи. Подробности — в отдельных файлах
> (ссылки внизу). Пункты **[?]** ждут ответа заказчика.

---

## 1. Что строим (в двух абзацах)

AI-агент-продавец для турагентства **Frunze Travel**. Встречает входящего клиента в
мессенджере, квалифицирует (задаёт вопросы), подбирает актуальные туры через **TourVisor**
или оценивает визовые шансы, и **доводит клиента до офиса или до менеджера на оплату**.
Всё фиксируется в CRM **Bitrix24** (движение по канбану).

Три воронки: **Туры**, **Визы**, **Билеты**. Цель ИИ — продавать и приводить в офис,
снимая рутину первичного контакта с менеджеров.

## 2. Потоки (из ТЗ заказчика, 18.06.2026)

**Туры:** приветствие → блок вопросов → поиск в TourVisor → если клиент «проблемный» →
зовём в офис; иначе → менеджер дожимает до оплаты → стадия в канбане.

**Визы:** приветствие → вопросы по визе → оценка шансов в % → приглашение в офис/созвон →
движение по канбану.

**Билеты:** **[?]** в ТЗ не детализировано — каркас (вопросы → передача менеджеру).

## 3. Решения по реализации

| Тема | Решение |
|------|---------|
| Стек | **Python 3.12** — FastAPI, Anthropic Claude (tool-use), aiogram, httpx, Postgres/Redis |
| Каналы | Telegram (MVP), далее **Bitrix24 Открытые линии** (сами агрегируют WhatsApp/Instagram/Telegram) |
| CRM в MVP | **Заглушка** `CrmStub` (локальный «канбан»); реальный Bitrix24 — фаза 2 |
| Архитектура | Гексагональная (ports & adapters) — Bitrix/каналы вставляются без переписывания ядра |
| Воронка | Детерминированный state-machine + LLM ведёт диалог и вызывает инструменты |

## 4. Скелет проекта (уже создан, тесты зелёные)

```
app/
  api → main.py            # FastAPI: вебхук Telegram + /health
  channels/                # ChannelAdapter: telegram.py (MVP), bitrix_openlines.py (ф.2)
  core/                    # orchestrator.py, router.py, state.py
  funnels/                 # tours.py, visa.py, tickets.py
  agent/                   # llm.py (Claude), tools.py (контракты инструментов)
  integrations/
    tourvisor/client.py    # поиск туров (демо-режим без доступов)
    crm/                   # port.py, stub.py (MVP), bitrix24.py (ф.2)
  config.py                # .env через pydantic-settings
tests/                     # 4 смоук-теста (зелёные)
```

**Инструменты AI (tool-use):** `ask_qualification`, `search_tours`, `score_visa`,
`escalate_to_office`, `handoff_to_manager`, `crm_update_stage`.

**Запуск:**
```bash
pip install -r requirements.txt
cp .env.example .env        # заполнить ключи
uvicorn app.main:app --reload
pytest -q                   # 4 passed
```

## 5. Этапность

- **MVP:** Telegram + Туры (TourVisor) + Визы + CRM-заглушка + память диалога.
- **Фаза 2:** Bitrix24 (Открытые линии как канал + REST для лидов/канбана), WhatsApp/Instagram.
- **Фаза 3:** Билеты, аналитика, A/B промптов.

## 6. Открытые вопросы к заказчику (перенаправить)

1. **Билеты** — структура воронки и источник цен (TourVisor / отдельный GDS-API)?
2. **«Проблемный клиент»** — по каким признакам бот определяет?
3. **Виза %** — правила/таблица или оценка ИИ? Факторы (страна, отказы, документы)?
4. **TourVisor** — доступы к API, список туроператоров, регион вылета.
5. **Bitrix24** — портал, воронки и стадии канбана, вебхук (фаза 2).
6. **LLM** — согласован ли Claude + бюджет на токены?
7. **Языки** общения (рус/кыр/др.) и поддержка медиа/файлов.

## 7. Где что лежит

- Бриф: `design-artifacts/A-Product-Brief/product-brief.md`
- Триггер-карта: `design-artifacts/B-Trigger-Map/trigger-map.md`
- PRD: `_bmad-output/planning-artifacts/PRD.md`
- Архитектура: `_bmad-output/planning-artifacts/architecture.md`
- Журнал решений: `design-artifacts/_progress/00-design-log.md`
- Аналоги на рынке: `docs/market-analogues.md`
