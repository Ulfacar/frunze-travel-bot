# Тестовые Telegram-боты (песочница «черновик»)

Зачем: на двух WhatsApp-номерах сидят реальные клиенты («чистовик») — экспериментировать там
нельзя. Два Telegram-бота = точные копии воронок (туры/визы) для обкатки правок перед боевым
WhatsApp. Поведение 1:1 с продакшн-ботами (тот же код, жёсткий сценарий через `bot.scenario`).

## Как поднять

1. **Создать 2 бота** в Telegram у **@BotFather**: `/newbot` дважды
   (напр. `FrunzeTours_test_bot` и `GetVisa_test_bot`). Сохранить 2 токена.

2. **Прописать в `.env`** сервера (JSON одной строкой):
   ```
   TELEGRAM_BOTS=[{"id":"frunze_tours_tg","scenario":"tours","token":"<токен1>"},{"id":"getvisa_tg","scenario":"visa","token":"<токен2>"}]
   ```
   Перезапустить приложение (`docker compose ... up -d`).

   **Включить тест-ботов, не будя WhatsApp** — персональным флагом (глобальный
   `bots_enabled` оставляем OFF, см. раздел про рубильник ниже):
   ```
   docker compose exec <app> python -c "import asyncio; from app.core import flags; \
     asyncio.run(flags.set_flag('bots_enabled:frunze_tours_tg', True)); \
     asyncio.run(flags.set_flag('bots_enabled:getvisa_tg', True))"
   ```

3. **Зарегистрировать вебхук** каждого бота у Telegram (один раз):
   ```
   curl "https://api.telegram.org/bot<токен1>/setWebhook?url=https://<домен>/webhook/telegram/frunze_tours_tg"
   curl "https://api.telegram.org/bot<токен2>/setWebhook?url=https://<домен>/webhook/telegram/getvisa_tg"
   ```
   (если задан `WEBHOOK_SECRET` — добавить `&secret_token=<секрет>`).

4. **Тестировать:** написать боту в Telegram как клиент — поведение идентично WhatsApp.
   Диалоги видны в той же админ-панели (ключ `bot_id:user_id`, туры и визы не пересекаются).

## Что в коде
- `app/config.py` — модель `TelegramBotConfig` + настройка `telegram_bots`.
- `app/main.py` — по оркестратору на бота (`_telegram_test`) + маршрут `POST /webhook/telegram/{bot_id}`.
- Старый одиночный `/webhook/telegram` (keyword-детект) оставлен для обратной совместимости.
- Тесты: `tests/test_telegram_routing.py`.

> **Рубильник `bots_enabled` — per-bot.** `_bots_on()` сначала смотрит персональный ключ
> `bots_enabled:<bot_id>`, при его отсутствии наследует глобальный `bots_enabled`. Это и есть
> механизм изоляции: глобальный держим **OFF** (боевой WhatsApp молчит — его боты персональный
> ключ не задают), а тест-ботам выставляем `bots_enabled:frunze_tours_tg=true` /
> `bots_enabled:getvisa_tg=true` (команда в шаге 2). Отдельный staging-контейнер не нужен.
