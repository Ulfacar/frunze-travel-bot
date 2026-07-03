# СПЕКА для Codex — «Покупатели сегодня»: авто-триаж лидов + экран владельца/менеджера

Автор: Claude (планирует + ревьюит, свёл BMAD party mode). Исполнитель: Codex. Режим Веном.

## Зачем (боль владельца)
~100 обращений/день, менеджеры (Адеми/Сезим/Медина/Элиза) тянут ~10-15, платить готовы единицы.
Задача: бот сам делит поток на тиры и подаёт менеджеру **только готовых платить**, остальных ведёт/
отсеивает сам. Владелец видит деньги и «сколько шума бот съел», а не 100 чатов.

**Принцип (Dr. Quinn):** это фильтр ДО очереди менеджера, а не сортировка 100 штук. Менеджер по
умолчанию видит только 🟢. **Принцип (Winston):** score — приоритизация, НЕ отсечка; система никогда
не прячет реального покупателя (асимметрия в пользу false-positive). Первую неделю — **не режем**,
показываем тир всем, калибруем пороги по реальным исходам.

Стек: FastAPI + Jinja + HTMX (поллинг, без вебсокетов), Postgres, inline SVG/CSS (без внешних CDN/JS-либ),
Claude LLM. Расширяем СУЩЕСТВУЮЩИЙ qualification-вызов (не новый) → маржинальная стоимость ≈ $0.

---

# ФАЗА 1 — Мотор готовности (backend, ~полдня)

## 1.1 Контракт полей (namespace `readiness` в существующем qualification JSON)
LLM эмитит ТОЛЬКО булевы факты + `readiness_reason`. **Тир считает КОД** (детерминированно, юнит-тестируемо).

**Общие (shared):** `explicit_payment_intent`, `explicit_booking_request`, `deadline_mentioned`,
`budget_stated`, `contact_shared`, `manager_requested` (позитив); `price_objection_only`,
`info_only_browsing`, `repeated_generic_questions`, `single_word_replies_only`,
`comparing_multiple_agencies` (негатив); `message_count_client` (int).

**Туры:** `destination_confirmed`, `travel_dates_narrowed`, `pax_count_stated` (+).
**Визы:** `country_in_scope`, `travel_purpose_stated`, `document_readiness_mentioned` (+); `visa_history_negative` (−).

Все bool, default False. Добавить в pydantic-модель ответа квалификации (переиспользовать существующий
structured-output парсер) + инструкцию в промпт. Схему зафиксировать как контракт — один и тот же набор
ключей на каждый вызов (иначе данные несопоставимы).

## 1.2 Поля, считаемые КОДОМ (не LLM)
- `ghost_hours: float` — часы с последнего сообщения клиента до now (или до последнего сообщения бота,
  если диалог завис после ответа бота). Арифметика по таймстемпам `messages`.
- `unresponsive_after_offer: bool` — код сверяет время сообщения-предложения бота (цена/тур/условия) с
  наличием/временем следующего сообщения клиента.
- `keyword_safety_trigger_matched: bool` — regex по последнему сообщению клиента:
  оплат|реквизит|бронир|забронир|когда вылет|готов оплат|куда плат. Независим от LLM (работает даже если
  квалификация деградировала).

## 1.3 Функция тира (код, первое совпадение побеждает)
```
def compute_tier(f) -> str:   # "green" | "warm" | "noise" | "insufficient"
    if f.keyword_safety_trigger_matched:            return "green"   # safety, до всего
    if f.message_count_client < 2 or (pos(f)==0 and neg(f)==0): return "insufficient"
    if f.explicit_payment_intent or f.explicit_booking_request or f.manager_requested: return "green"
    if f.deadline_mentioned and f.budget_stated and (f.destination_confirmed or f.country_in_scope): return "green"
    if neg(f) >= 2 and pos(f) == 0:                 return "noise"
    return "warm"
```
где `pos(f)` = count позитивных сигналов, `neg(f)` = count негативных. Пороги (`neg>=2` и т.п.) вынести
в конфиг-константу `READINESS_THRESHOLDS`, чтобы калибровать без деплоя.

## 1.4 `readiness_reason` (str, обязателен, ≤150 симв)
1 предложение, обязана содержать цитату/пересказ реплики клиента + какое поле сработало
(«сработал explicit_payment_intent — спросил про оплату»). Запрет домысливать намерение без опоры на текст.

## 1.5 Модель данных (миграция, 15 мин)
Колонки в `conversations`: `readiness_tier` VARCHAR(16) (green|warm|noise|insufficient|NULL),
`readiness_reason` TEXT, `readiness_signals` JSON (сырые булевы — для аудита/калибровки),
`readiness_scored_at` TIMESTAMP, `estimated_value` NUMERIC null, `estimated_value_currency` VARCHAR(8).
Историю тира пока НЕ храним (добьём `conversation_readiness_history` позже, если нужен тренд).

`estimated_value`: из `qualification` (бюджет/направление+пакс). Нормализатор строки→число, валюта→базовая
(сом/USD фикс-курс в конфиг). Если не извлекается → NULL (показываем «$?», не прячем, не выдумываем).

## 1.6 Пересчёт
Обновлять readiness при каждом re-run квалификации (на каждое новое сообщение, как сейчас). `ghost_hours`
и safety-trigger — дёшево, можно и на чтении. Safety-trigger при срабатывании → тир green немедленно,
вне ожидания LLM-прогона.

## 1.7 Тесты Фазы 1 (обязательно)
- `compute_tier`: по одному кейсу на каждую ветку (safety→green; <2 msg→insufficient; payment_intent→green;
  комбо deadline+budget+dest→green; 2 негатива 0 позитива→noise; иначе→warm). Порядок приоритета.
- safety-trigger перебивает insufficient (клиент 1 сообщением «реквизиты?» → green).
- нормализатор `estimated_value`: «$800»→800, «800-1000»→900|800 (реши и зафиксируй), «до 100 тыс сом»→
  число+currency, пусто→None.
- контракт: qualification-ответ без readiness-полей (старые данные) → tier NULL/insufficient, не падает.

---

# ФАЗА 2 — Экран «Покупатели сегодня» (frontend, ~1-1.5 дня)

Эндпоинты (все под `require_admin`; owner-hero — под `require_full_admin`? нет — менеджеру тоже нужен свой
срез: менеджер видит СВОЮ воронку 🟢 через существующий scope-фильтр; владелец видит всё):
- `GET /admin/buyers` — страница (owner hero + manager feed).
- `GET /admin/buyers/feed` — HTMX-partial ленты 🟢 (для поллинга `every 30s`), scope-фильтрован.
- `POST /admin/leads/{user_id}/claim` — «Взять в работу»: takeover (переиспользовать существующий
  `set_intercept`/assign) + пинг менеджеру; возвращает пустоту (карточка исчезает) или «уже взял X» при гонке.

## 2.1 OWNER hero (мобайл, glance-value за 3 сек), сверху вниз
1. Заголовок «Покупатели сегодня · DD.MM» (мелко, серо).
2. **🟢 N готовы купить** — гигант 48-56px; ниже **~ $X потенциал** (28px, Fira Code, `tabular-nums`).
3. **⏱ K ждут ответа >15 мин 🔴** — красный чип ТОЛЬКО если есть просрочка (иначе не рендерить).
4. **Шум отфильтрован: ⚫ из 100** + progress-bar (два `<div>`, ширина inline).
5. Ряд чипов-счётчиков: 🟢 N · 🟡 N · ⚫ N · ❔ N — каждый `<a href="?tier=...">` фильтрует.
6. Один CTA `[ Смотреть готовых → ]` → manager feed.

## 2.2 MANAGER feed — только 🟢
- Сортировка: срочность (SLA-ожидание) desc primary, `estimated_value` desc tie-breaker.
- Кап топ-15, «Показать ещё N» если больше.
- **НЕ рендерить в DOM** ⚫ и ❔ (не сворачивать — их нет); 🟡 — отдельная секция ниже.
- Карточка (верт. стек): `🟢 Имя(или «Без имени·хвост тел») · Направление(бренд-бот)` / `$value(или «$?» серым)` /
  `readiness_reason` (обрезка ~80 симв, `title=` полный) / `⏱ ждёт M мин` (цветной) + `[Взять в работу]`.

## 2.3 Live countdown (HTMX, без JS)
- `wait = now - last_customer_message_at`. `hx-trigger="every 30s"` на `#ready-list` →
  `hx-get="/admin/buyers/feed" hx-swap="innerHTML"`. Сервер владеет цветом и сортировкой.
- Пороги (конфиг-константы, не в шаблоне): <5 мин зелёный, 5-15 янтарный, >15 красный + `animation: pulse`
  (чистый CSS). Каждая карточка `<div class="lead-card" id="lead-{{id}}">`; клик по claim → `hx-swap="outerHTML"`
  точечно убирает карточку, не дожидаясь поллинга.

## 2.4 Компоненты (Jinja-макросы, inline SVG/CSS)
`wait_chip(minutes)` (3 класса ok/warn/late), тир-чип (4 цвета, `<a>`-фильтр), money-hero (`tabular-nums`),
noise-bar (2 div). Все цвета — из существующих CSS-переменных панели.

## 2.5 Wow-микродеталь (опц., дёшево)
При пересечении круглого порога доли ⚫ (50/60/70%) заливка noise-bar на 400мс вспыхивает (CSS keyframe по
смене `data-pct`) + «+N отфильтровано» всплывает на 3с и гаснет.

## 2.6 Тесты Фазы 2
- `/admin/buyers` 200 для менеджера и владельца; менеджер видит только свою воронку (scope), владелец — всё.
- feed отдаёт только green, не содержит noise/insufficient в HTML.
- claim делает takeover + убирает карточку; повторный claim другим менеджером → «уже взял».
- сортировка: дольше ждёт — выше; при равном ожидании дороже — выше.

---

# Безопасность / калибровка / зависимости
- **Первая неделя — не режем:** тир показываем, но менеджеру доступны все воронки как сейчас; собираем
  `readiness_signals` + реальные исходы для калибровки `READINESS_THRESHOLDS`. Потом включаем «менеджер видит только 🟢».
- **False-negative дороже:** если `lead_temperature=hot` ИЛИ (budget+dates) но тир не green — предохранитель
  всё равно поднимает в очередь с пометкой «проверить». Score не прячет диалог целиком.
- **Проверить перед стартом:** проставляется ли `assigned_to` при takeover (иначе SLA-таймер соврёт
  «никто не отвечает»). Свериться с хендофф-логикой в коде.
- **Автодожим 🟡** — отдельная итерация (инфра followup уже есть, gated): Haiku, лимит ~20/день, dry-run
  (черновик в панели, не улетает) первую неделю. НЕ в этом MVP, отдельной спекой.
- **НЕ строим** AI-прогноз выручки/вероятности — нет истории outcome, будет красивая ложь.

# LLM-стоимость
Фаза 1 — +30-50 токенов на выходе к существующему вызову (≈$0 в $2.5/день бюджете). Фаза 2 — ноль LLM
(чистый SQL + таймстемпы). Автодожим (позже) — единственное место с плюсом к счёту, на Haiku + лимит.

# Метрика успеха (Dr. Quinn)
- conversion внутри 🟢 (сколько готовых реально дошли до оплаты/офиса).
- % из 100, долетевших до менеджера (цель — заметно <100; 80 = фильтр не работает, 3 = слишком жёстко).

# Порядок реализации
1. Фаза 1 (мотор) → 2. calibration-неделя (показ без резки) → 3. Фаза 2 экран → 4. включить фильтр 🟢 →
5. (отдельно) автодожим 🟡 с dry-run.

# Деплой (прод не в git — файлами, см. [[frunze-prod-deploy-runbook]])
Миграция колонок (idempotent), затем файлами + `docker compose -f docker-compose.yml -f docker-compose.vps.yml
--env-file prod.env up -d --build app`. Claude ревьюит (codex-reviewer) перед деплоем.
