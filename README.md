# Frunze Travel Bot

AI-агент-продавец для турагентства Frunze Travel: квалифицирует клиентов в трёх воронках
(**Туры**, **Визы**, **Билеты**), подбирает туры через **TourVisor**, оценивает визовые
шансы и передаёт «тёплого» клиента в офис или менеджеру, фиксируя стадию в CRM (Bitrix24).

## Статус
MVP-скелет. CRM — заглушка (`CrmStub`), канал — Telegram. Реальный Bitrix24 — фаза 2.

## Документы
- Продуктовый бриф: `design-artifacts/A-Product-Brief/product-brief.md`
- Триггер-карта: `design-artifacts/B-Trigger-Map/trigger-map.md`
- Админ-панель и канбан диалогов: `docs/admin-panel-frunze.md`
- Чеклист запуска: `docs/launch-checklist-frunze.md`
- Coolify deploy: `docs/coolify-deploy-frunze.md`
- Правила общения бота: `docs/bot-dialog-playbook.md`
- PRD: `_bmad-output/planning-artifacts/PRD.md`
- Архитектура: `_bmad-output/planning-artifacts/architecture.md`

## Запуск (dev)

### Вариант A — демо в Telegram (проще всего, без публичного URL)
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # TELEGRAM_BOT_TOKEN (от @BotFather) + OPENROUTER_API_KEY
python run_polling.py         # бот отвечает в Telegram через long-polling
```
Напиши боту «хочу тур» — воронка «Туры» поведёт живой AI-диалог (если задан
`OPENROUTER_API_KEY`; иначе — детерминированный режим). TourVisor в демо-режиме.

### Вариант B — webhook-сервер (прод-режим)
```bash
uvicorn app.main:app --reload   # вебхук Telegram: POST /webhook/telegram
```

## Структура
См. `_bmad-output/planning-artifacts/architecture.md` (раздел «Компоненты»).

## Открытые вопросы к заказчику
См. конец PRD — билеты, критерии «проблемного клиента», методика визовых %,
доступы TourVisor/Bitrix24, языки общения.
