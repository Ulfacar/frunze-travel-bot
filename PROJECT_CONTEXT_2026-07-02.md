# Frunze Travel Bot — контекст проекта на 2026-07-02

Документ фиксирует текущую обстановку по проекту: что запущено, где живет прод, как устроена система, что сейчас происходит с OpenRouter и какие ближайшие риски/действия.

## Кратко

Проект — AI-бот-продавец для Frunze Travel / GetVisa. Бот принимает клиентов из WhatsApp через Wappi, ведет первичный диалог, квалифицирует по трем направлениям и доводит клиента до офиса или менеджера.

Основные воронки:

- Туры
- Визы
- Билеты

В проде сейчас работает связка:

- FastAPI-приложение: бот + админ-панель
- PostgreSQL 16: диалоги, сообщения, карточки, настройки, FAQ, аудит
- Redis 7: состояние диалогов
- Wappi: WhatsApp-каналы
- OpenRouter: LLM через Claude
- nginx + Let’s Encrypt: внешний HTTPS

## Прод

Прод развернут на VPS:

- Сервер: `62.171.185.155`
- SSH: `root@62.171.185.155`
- Путь проекта: `/root/frunze-travel`
- Домен: `https://frunzetravel.kg`
- Админка: `https://frunzetravel.kg/admin`
- Healthcheck: `https://frunzetravel.kg/health`

Контейнеры на момент проверки 2026-07-02:

- `frunze-travel-app-1` — up, healthy
- `frunze-travel-db-1` — up, healthy
- `frunze-travel-redis-1` — up, healthy

Приложение слушает только локально:

- контейнерный порт: `8000`
- host binding: `127.0.0.1:8077`
- наружу смотрит системный nginx

Основная команда эксплуатации на сервере:

```bash
cd /root/frunze-travel
docker compose -f docker-compose.yml -f docker-compose.vps.yml --env-file prod.env up -d --build
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs app -f
docker compose -f docker-compose.yml -f docker-compose.vps.yml --env-file prod.env restart app
```

## Текущий статус OpenRouter

Проверено 2026-07-02.

OpenRouter credits:

- Total credits: `$41.00`
- Total usage: `$38.975316724`
- Остаток: примерно `$2.02`

В проде включена основная модель:

```env
LLM_MODEL_MAIN=anthropic/claude-sonnet-4.6
LLM_MODEL_CHEAP=anthropic/claude-haiku-4.5
```

Главный риск: сейчас почти все ответы бота идут через дорогую `claude-sonnet-4.6`. При текущей активности остаток около `$2` может закончиться быстро.

Быстрые варианты реакции:

1. Пополнить OpenRouter.
2. Временно переключить `LLM_MODEL_MAIN` на `anthropic/claude-haiku-4.5`.
3. Временно отключить `OPENROUTER_API_KEY`, чтобы бот ушел в детерминированный режим.
4. Добавить/включить лимитер или routing: простые FAQ/прощания/медиа не отправлять в Sonnet.

## Текущая активность диалогов

Срез из PostgreSQL на 2026-07-02 около 16:48 Asia/Almaty:

- Всего диалогов в базе: `477`
- Неархивных активных: `94`
- Диалогов с активностью за 24 часа: `476`
- Диалогов с активностью за 1 час: `12`

Сообщения за последние 24 часа:

- Клиент: `945`
- Бот: `742`
- Менеджер: `5`

Состояние последних активных неархивных диалогов:

- Последний ответ от клиента, ждут реакции: `22`
- Последний ответ от бота: `70`
- Последний ответ от менеджера: `2`

Пики нагрузки за 24 часа:

- До `100` ответов бота в час.
- В текущем часу было `31` сообщение бота и `46` сообщений клиентов.

Топ диалогов по числу ответов бота за 24 часа:

- `getvisa:996555146999` — 40 ответов бота
- `frunze_tours:996557333305` — 35 ответов бота
- `frunze_tours_sezim:996551220009` — 31 ответ бота
- `getvisa:996501498087` — 26 ответов бота
- `frunze_tours:996551220009` — 26 ответов бота

Это подтверждает, что расход OpenRouter вызван реальной высокой нагрузкой в WhatsApp-диалогах, а не только тестами.

## WhatsApp / Wappi

В проде подключены профили Wappi:

- Туры: `FrunzeTravel2`, profile id `02a4708d-ec6c`, номер `+996707660009`
- Визы: `GetVisa`, profile id `2f099bc3-478d`, номер `+996706660009`

Webhook:

```text
https://frunzetravel.kg/webhook/wappi
```

Входящие сообщения приходят в `POST /webhook/wappi`, дальше приложение определяет профиль/бота и маршрутизирует в нужную воронку.

## Архитектура

Упрощенный поток:

```text
Клиент WhatsApp
  -> Wappi
  -> POST /webhook/wappi
  -> FastAPI app
  -> Orchestrator / funnel
  -> OpenRouter Claude при включенном LLM
  -> tools: qualification / tour search / visa scoring / handoff / CRM stage
  -> Postgres + Redis
  -> Wappi send
  -> клиент
```

Админка работает в том же FastAPI-приложении и смотрит в ту же базу.

Важное архитектурное решение: ключ диалога имеет вид:

```text
<bot_id>:<phone>
```

Это нужно, чтобы один и тот же номер клиента в разных ботах не смешивал состояние, перехват и карточку.

## Основные файлы

- `app/main.py` — FastAPI entrypoint, healthcheck, webhooks.
- `app/core/orchestrator.py` — центральная обработка сообщений.
- `app/agent/runner.py` — запуск LLM-агента и tool-use.
- `app/agent/llm.py` — OpenRouter adapter.
- `app/funnels/tours.py` — туровая воронка.
- `app/funnels/visa.py` — визовая воронка.
- `app/funnels/tickets.py` — билетная воронка.
- `app/channels/wappi.py` — WhatsApp через Wappi.
- `app/admin/router.py` — админ-панель.
- `app/integrations/crm/db.py` — SQLAlchemy-модели.
- `app/integrations/panel/store.py` — conversation store.
- `app/core/followup.py` — автодожим.
- `app/core/observ.py` — счетчики сбоев.
- `docker-compose.yml` — основной compose.
- `docker-compose.vps.yml` — VPS overlay с binding на `127.0.0.1:8077`.
- `DEPLOY_STATUS.md` — подробный деплой-статус.
- `HANDOVER.md` — старый handover, частично актуален.
- `TZ_CLIENT_FIXES_2026-07-02.md` — срочное ТЗ по правкам клиента от 2026-07-02: имена менеджеров, GetVisa/Mедина в UI, Bitrix visibility, Египет/прямые рейсы, рабочие визы.
- `docs/visa-faq-questionnaire-filled-draft-2026-07-02.md` — заполненный черновик визового FAQ: известные ответы уже внесены, спорные пункты помечены `[уточнить у клиента]`.

## Админ-панель

Адрес:

```text
https://frunzetravel.kg/admin
```

Возможности:

- Канбан по воронкам.
- Inbox: диалоги, где нужно внимание.
- Полный чат по клиенту.
- Перехват диалога менеджером и возврат боту.
- Ответ менеджера из браузера.
- Статус доставки исходящих сообщений.
- Повторная отправка.
- Быстрые ответы.
- AI-подсказка ответа.
- Архивирование диалогов.
- Архивирование шума/рекламы.
- Ручная смена стадии.
- Исходы: оплатил / дошел / слился и т.п.
- FAQ-правила.
- Аудит действий менеджеров.
- System page: LLM, send failures, webhook secret, followup.
- Analytics.

Ключевые routes:

- `GET /admin`
- `GET /admin/inbox`
- `GET /admin/board/{funnel}`
- `GET /admin/conversation/{user_id}`
- `POST /admin/conversation/{user_id}/send`
- `POST /admin/conversation/{user_id}/takeover`
- `POST /admin/conversation/{user_id}/release`
- `POST /admin/conversation/{user_id}/suggest`
- `GET /admin/system`
- `GET /admin/analytics`
- `GET /admin/faq`

## Интеграции

### OpenRouter

Работает через OpenAI-compatible `/chat/completions`.

Код:

- `app/agent/llm.py`
- `app/agent/runner.py`

Секрет хранится в `prod.env` на сервере. В документах и коммитах ключи не фиксировать.

### Wappi

Основной боевой канал.

Код:

- `app/channels/wappi.py`
- `app/main.py`, route `/webhook/wappi`

### TourVisor

Предназначен для поиска туров. По старому статусу была проблема `Authorisation Error`, нужна проверка/активация XML API у клиента.

### Bitrix24

Код интеграции есть, но продовая роль Bitrix сейчас не является основным источником правды. Основная рабочая база — Postgres + админка. Bitrix планировался/готовился как зеркало сделок и фазовая интеграция.

Файлы:

- `app/integrations/crm/bitrix24.py`
- `app/channels/bitrix_openlines.py`
- `docs/bitrix-integration-spec.md`

## База данных

Основные таблицы:

- `conversations`
- `messages`
- `deals`
- `audit_log`
- `app_flags`
- `faq_entries`

Ключевые поля `conversations`:

- `user_id` — ключ вида `<bot_id>:<phone>`
- `phone`
- `channel`
- `chat_id`
- `bot_id`
- `funnel`
- `stage`
- `intercepted`
- `archived`
- `qualification`
- `ai_summary`
- `manager_next_step`
- `escalation_reason`
- `lead_temperature`
- `assigned_to`
- `outcome`
- `last_text`
- `last_sender`
- `followup_sent`
- `last_message_at`

Ключевые поля `messages`:

- `conversation_id`
- `sender`: `client`, `bot`, `manager`
- `text`
- `status`
- `provider_msg_id`
- `idempotency_key`
- `created_at`

## Команды диагностики

Проверить контейнеры:

```bash
ssh root@62.171.185.155 "cd /root/frunze-travel && docker compose -f docker-compose.yml -f docker-compose.vps.yml ps"
```

Проверить health:

```bash
ssh root@62.171.185.155 "curl -fsS https://frunzetravel.kg/health"
```

Логи приложения:

```bash
ssh root@62.171.185.155 "cd /root/frunze-travel && docker compose -f docker-compose.yml -f docker-compose.vps.yml logs --since=1h app"
```

Зайти в Postgres:

```bash
ssh root@62.171.185.155 "cd /root/frunze-travel && docker compose -f docker-compose.yml -f docker-compose.vps.yml exec -T db psql -U postgres -d frunze"
```

Сводка по диалогам:

```sql
SELECT count(*) AS conversations_total,
       count(*) FILTER (WHERE archived=false) AS active,
       count(*) FILTER (WHERE last_message_at > now() - interval '24 hours') AS active_24h,
       count(*) FILTER (WHERE last_message_at > now() - interval '1 hour') AS active_1h
FROM conversations;

SELECT sender, count(*) AS messages_24h
FROM messages
WHERE created_at > now() - interval '24 hours'
GROUP BY sender
ORDER BY sender;
```

Почасовая нагрузка:

```sql
SELECT date_trunc('hour', created_at) AS hour_utc, sender, count(*)
FROM messages
WHERE created_at > now() - interval '24 hours'
GROUP BY 1,2
ORDER BY 1 DESC,2;
```

## Срочные риски

1. OpenRouter почти исчерпан: остаток около `$2.02`.
2. Основная модель дорогая: `claude-sonnet-4.6`.
3. Нагрузка высокая: сотни сообщений за сутки и пики до 100 ответов бота в час.
4. Некоторые диалоги имеют очень много ходов, что быстро сжигает токены.
5. Менеджеры почти не отвечают из панели: за 24 часа только 5 сообщений менеджеров против 742 сообщений бота.

## Рекомендуемые ближайшие действия

1. Срочно решить по OpenRouter: пополнить или переключить main model на Haiku.
2. Добавить экономный режим:
   - FAQ и короткие закрывающие ответы без Sonnet.
   - Медиа/голос обрабатывать шаблоном без LLM.
   - После handoff/office не продолжать длинные LLM-диалоги.
   - Ограничить число LLM-ответов на один диалог за час/сутки.
3. Сделать отдельную метрику расхода:
   - логировать `usage` из OpenRouter response;
   - сохранять модель, prompt tokens, completion tokens, estimated cost;
   - выводить в `/admin/system` и `/admin/analytics`.
4. Проверить TourVisor XML API, если подбор туров должен быть живым.
5. Уточнить, как менеджеры реально должны подключаться: сейчас бот закрывает почти все сам.
6. Проверить и при необходимости отозвать старые засвеченные токены, упомянутые в `DEPLOY_STATUS.md`.

## Что уже реализовано

### Продовая инфраструктура

- VPS с Docker-стеком.
- `app` + `PostgreSQL` + `Redis`.
- Системный nginx перед приложением.
- HTTPS через Let's Encrypt.
- Домен `frunzetravel.kg`.
- Healthcheck `/health`.
- Админка `/admin`.
- Продовая конфигурация через `prod.env` на сервере.

### WhatsApp-канал

- Прием входящих webhook-событий Wappi на `/webhook/wappi`.
- Отправка сообщений обратно клиенту через Wappi.
- Поддержка нескольких Wappi-профилей/ботов.
- Разделение диалогов по ключу `<bot_id>:<phone>`.
- Фильтрация групп, реакций и echo-сообщений.
- Статусы исходящих сообщений и `provider_msg_id`.

### AI-диалоги

- OpenRouter adapter в `app/agent/llm.py`.
- OpenAI-compatible chat completions.
- Tool-use через существующий Anthropic-like интерфейс.
- Основной LLM-runner.
- Воронки `tours`, `visa`, `tickets`.
- Инструменты агента:
  - qualification;
  - tour search;
  - visa scoring;
  - handoff to manager;
  - escalation to office;
  - CRM stage update.
- Детерминированный fallback, если LLM выключен.

### Админ-панель

- Login/logout.
- Менеджеры через env.
- Канбан по воронкам.
- Inbox для диалогов, требующих внимания.
- Поиск.
- Карточка диалога с полной историей.
- Ответ менеджера из браузера.
- Перехват диалога менеджером.
- Возврат диалога боту.
- Архивирование одного диалога.
- Массовое архивирование.
- Архивирование шума.
- Ручная смена стадии.
- Исходы диалога.
- Повторная отправка сообщения.
- AI-подсказка ответа.
- FAQ-правила.
- Аудит действий менеджеров.
- System page.
- Analytics page.
- HTMX-обновления доски/чата/статистики.

### Хранилище и состояние

- PostgreSQL-модели:
  - `conversations`;
  - `messages`;
  - `deals`;
  - `audit_log`;
  - `app_flags`;
  - `faq_entries`.
- Redis state backend для состояния диалогов.
- Postgres conversation store для панели.
- Разделение одного телефона по разным ботам.
- Архивация без удаления.
- Идемпотентность исходящих сообщений через `idempotency_key`.

### Автоматизация и наблюдаемость

- Scheduler для фоновых задач.
- Follow-up job.
- Runtime flags через `app_flags`.
- Bot toggles.
- Счетчики `llm_failures` и `send_failures`.
- Watchdog/alerts в коде.
- `/admin/system` с базовым статусом.

### Тесты

- Есть покрытие по Wappi contract.
- Есть тесты роутинга ботов.
- Есть тесты панели.
- Есть тесты OpenRouter adapter.
- Есть тесты state store.
- Есть smoke-сценарии.
- В старом handover указано: `PYTHONPATH=. pytest` проходил с 86 зелеными тестами на момент 2026-06-24.

## Что не реализовано или не доведено

### Экономика OpenRouter

- Нет сохранения `usage` из ответа OpenRouter в базу.
- Нет расчета стоимости по каждому LLM-вызову.
- Нет лимитов на число LLM-вызовов по диалогу/боту/часу.
- Нет автоматического budget guard, который отключит Sonnet при низком балансе.
- Нет routing по сложности: все боевые LLM-ответы сейчас в основном идут через `LLM_MODEL_MAIN`.
- Нет отдельной аналитики затрат в `/admin/system` или `/admin/analytics`.

### Локальная ИИ

- Локальная модель не подключена.
- GPU endpoint не протестирован.
- Нет OpenAI-compatible fallback endpoint для локальной/дешевой модели.
- Нет бенчмарка качества локальной модели на реальных диалогах Frunze.

### TourVisor

- Интеграция предусмотрена, но по старому статусу XML API давал `Authorisation Error`.
- Нужно подтвердить у клиента/поддержки TourVisor, активирован ли XML API.
- Нужно отдельно прогнать реальный поиск туров на проде.

### Bitrix24

- Код интеграции есть, но не подтверждено, что Bitrix является рабочим продовым источником.
- Нужны актуальные webhook URL, CATEGORY_ID, STAGE_ID и ответственные.
- Нужно решить: Bitrix только зеркало или менеджеры должны работать в Bitrix вместо нашей панели.

### Менеджерский процесс

- По факту за последние 24 часа бот отправил `742` сообщения, менеджеры только `5`.
- Нужно уточнить, это ожидаемая стратегия или менеджеры не пользуются панелью.
- Нужно договориться, когда бот обязан глушиться и отдавать диалог человеку.
- Нужны правила для рекламных/мусорных/нецелевых диалогов.

### Контроль качества

- Нет ежедневного отчета по плохим диалогам.
- Нет отдельной разметки "бот ответил неправильно".
- Нет процесса регулярной калибровки промптов по реальным кейсам.
- Нет явного A/B сравнения Sonnet vs Haiku vs локальная модель.

## Что сейчас под вопросом или потенциально сломано

1. OpenRouter баланс почти закончился. Если не пополнить или не переключить модель, бот может перестать отвечать через LLM.
2. Текущая модель `claude-sonnet-4.6` слишком дорогая для текущего объема.
3. TourVisor может быть не полностью рабочим из-за XML authorization.
4. Bitrix24 не выглядит завершенным как продовый контур.
5. Менеджеры почти не участвуют в переписке через панель, хотя панель для этого сделана.
6. Диалоги с большим числом ходов могут неконтролируемо сжигать токены.
7. Медиа/голосовые сообщения сейчас могут создавать лишние LLM-ходы, если не отсечены шаблоном.
8. Старые токены, упомянутые в документах как засвеченные, нужно считать скомпрометированными и отозвать.

## Что делать завтра

Приоритет 0 — не дать боту остановиться:

1. Пополнить OpenRouter или переключить `LLM_MODEL_MAIN=anthropic/claude-haiku-4.5`.
2. Перезапустить `app`.
3. Проверить `/health`.
4. Отправить тестовое сообщение в WhatsApp.
5. Проверить, что новая переписка появилась в `/admin`.

Приоритет 1 — резко снизить расход:

1. Добавить routing: простые случаи без Sonnet.
2. Убрать LLM для `[медиа/голос]`: отвечать шаблоном.
3. После `handoff_to_manager` и `office` не продолжать болтать моделью без необходимости.
4. Ввести лимит LLM-ответов на диалог, например:
   - мягкое предупреждение после 10 ответов;
   - автопередача менеджеру после 15-20 ответов;
   - отдельный override для горячих лидов.
5. Логировать модель и usage каждого OpenRouter-вызова.

Приоритет 2 — понять реальную воронку:

1. Выгрузить топ 30 диалогов по числу ответов бота.
2. Руками посмотреть 10 самых дорогих диалогов.
3. Отметить:
   - где бот тянет диалог слишком долго;
   - где надо было передать менеджеру;
   - где клиент нецелевой;
   - где FAQ хватило бы без LLM.
4. На основе этого поправить промпт/правила handoff.

Приоритет 3 — интеграции:

1. Проверить TourVisor XML API.
2. Проверить, создаются ли/должны ли создаваться сделки в Bitrix24.
3. Уточнить у клиента фактический workflow менеджеров.
4. Проверить Wappi оплаты/сроки профилей.

Приоритет 4 — локальная ИИ:

1. Не покупать CPU VPS под LLM.
2. Взять временный GPU endpoint для теста.
3. Поднять OpenAI-compatible inference.
4. Прогнать реальные диалоги на локальной модели.
5. Сравнить качество/скорость/цену с Haiku и Sonnet.

## Минимальный план исправления OpenRouter-расхода в коде

1. В `app/agent/llm.py` сохранить `usage` из OpenRouter response.
2. Добавить таблицу или audit event для LLM-вызовов:
   - timestamp;
   - conversation/user_id;
   - bot_id;
   - model;
   - prompt_tokens;
   - completion_tokens;
   - total_tokens;
   - estimated_cost;
   - status/error.
3. В `app/core/orchestrator.py` или вокруг runner добавить budget/rate guard.
4. В funnel-логике добавить cheap path:
   - FAQ;
   - media placeholder;
   - goodbye;
   - duplicate/short acknowledgement;
   - already handed off.
5. В `/admin/system` вывести:
   - LLM calls today;
   - estimated spend today;
   - top costly dialogs;
   - current model;
   - last LLM error.
6. В env добавить переключатель:
   - `LLM_ECONOMY_MODE=true`;
   - `LLM_MAX_TURNS_PER_DIALOG=15`;
   - `LLM_MAIN_MODEL=...`;
   - `LLM_CHEAP_MODEL=...`.

## Идея: купить отдельный сервер и поставить локальную ИИ

Обсуждался вариант купить недорогой Cloud VPS, например тарифы уровня:

- 6 vCPU / 12 GB RAM
- 8 vCPU / 24 GB RAM
- 12 vCPU / 48 GB RAM
- 16 vCPU / 64 GB RAM

Вывод: такой VPS можно использовать для обычной инфраструктуры проекта, но не как полноценную замену OpenRouter/Sonnet.

CPU VPS подходит для:

- FastAPI-приложения
- админ-панели
- PostgreSQL
- Redis
- nginx
- фоновых задач
- легких deterministic/FAQ-ответов

CPU VPS плохо подходит для локальной LLM:

- нет GPU;
- маленькая модель запустится, но будет медленно;
- качество будет заметно хуже Claude Sonnet;
- tool-use и длинные диалоги будут тормозить;
- при нескольких клиентах одновременно ответы начнут задерживаться;
- экономия на токенах может ухудшить продажи.

Для локальной ИИ нужен GPU-сервер.

Минимально разумные классы GPU:

- 24 GB VRAM: L4 / RTX 3090 / RTX 4090 / RTX A5000 — небольшие и средние модели.
- 48 GB VRAM: A40 / A6000 / L40S / RTX 6000 Ada — более уверенный вариант для продового inference.
- 80 GB VRAM: A100 / H100 — крупные модели, дорого.

Ориентиры по публичным ценам RunPod на 2026-07-02:

- L4: около `$0.39/hr`
- RTX 4090: около `$0.69/hr`
- A40: около `$0.44/hr`
- A6000: около `$0.49/hr`
- L40S: около `$0.99/hr`

Если держать GPU 24/7, порядок бюджета получается примерно `$280-$720+/month` без учета диска, резерва и администрирования. Это дороже, чем просто переключить OpenRouter на более дешевую модель, если нагрузка умеренная.

Практичный вывод:

1. Не покупать CPU VPS ради локальной ИИ.
2. Срочно снизить расход OpenRouter: переключить `LLM_MODEL_MAIN` с `anthropic/claude-sonnet-4.6` на `anthropic/claude-haiku-4.5` или добавить routing.
3. Добавить экономный режим:
   - FAQ без LLM;
   - короткие прощания без LLM;
   - медиа/голос обрабатывать шаблоном;
   - после handoff/office не продолжать длинный LLM-диалог;
   - лимитировать количество LLM-ответов на диалог за час/сутки.
4. Если все равно нужен локальный ИИ, сначала тестировать не покупку VPS, а аренду GPU endpoint:
   - RunPod / Vast.ai / аналог;
   - `vLLM`, `Ollama` или OpenAI-compatible inference server;
   - отдельный endpoint, который можно подключить как дешевую модель.
5. Целевая архитектура — гибридная:
   - локальная/дешевая модель для простых ответов;
   - Claude Sonnet только для сложных продажных моментов, подбора, спорных кейсов и manager-facing подсказок.

Такой подход дает экономию быстрее и безопаснее, чем немедленная покупка отдельного CPU-сервера под локальную ИИ.

## Что не хранить в документах

Не добавлять в markdown, git и чат:

- `OPENROUTER_API_KEY`
- `WAPPI_TOKEN`
- `ADMIN_PASSWORD`
- `POSTGRES_PASSWORD`
- webhook tokens
- Bitrix webhook URL с токеном
- Cloudflare/Coolify tokens

В этом документе секреты намеренно не указаны.
