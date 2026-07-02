# СПЕКА для Codex — Фаза 3: дневной лимит расхода LLM (budget guard)

Автор: Claude (ревьюит). Исполнитель: Codex. Ветка: `feature/token-economy-phase1`. Не деплоить/не пушить/не коммитить.

Цель: чтобы расход OpenRouter физически не превышал заданный дневной потолок. При приближении — принудительно дешёвая модель; при достижении — LLM выключается, бот работает детерминированно (FAQ) и чаще передаёт менеджеру. Сброс — на следующий день (по Бишкеку, UTC+6).

## Project gotchas (учесть)
1. `observ.record_usage` (`app/core/observ.py:41`) уже копит дневной cost в памяти `_USAGE_DAILY[day]["cost"]`, НО: (а) только в памяти (теряется при рестарте) — для гарда нужен Redis (переживает рестарт); (б) ключ дня `date.today()` = серверная дата (в контейнере UTC) → съезжает на 6ч от Бишкека. Для гарда считать день по Бишкеку.
2. **Стоимость может не приходить.** OpenRouter отдаёт `cost` в `usage` только если запросить. В payload (`app/agent/llm.py OpenRouterMessages.create`) добавить `"usage": {"include": True}`. И на случай отсутствия — фолбэк-расчёт по цене модели × токены (иначе гард недосчитает и не сработает).
3. `flags.py` — только bool. Числовой бюджет держать в конфиге (env), не в app_flags.
4. `llm_enabled()` (`llm.py:106`) — синхронная, дёргается в 3 воронках (`tours.py:34`, `visa.py:28`, `tickets.py:24`) + admin suggest_reply (`admin/router.py:792`). НЕ менять её сигнатуру. Добавить отдельную async `llm_available()` для hard-cap.
5. Прод: `STATE_BACKEND=redis`, `PANEL_BACKEND=postgres`. Один инстанс.
6. Не сломать роутинг Фазы 1, FAQ, скоуп менеджеров, handoff.

## TASK 1 — надёжная стоимость
- В `app/agent/llm.py` в payload `OpenRouterMessages.create` добавить `"usage": {"include": True}` (чтобы OpenRouter возвращал `cost`).
- Добавить фолбэк-прайс: словарь цен per-1M токенов по подстроке модели (input/output): `haiku` → (1.0, 5.0); `sonnet` → (3.0, 15.0); дефолт → (3.0, 15.0). Функция `estimate_cost(model, prompt_tokens, completion_tokens) -> float`. Использовать её, когда `cost` из ответа отсутствует/0.
- Разместить прайс/estimate в `app/core/budget.py` (см. TASK 2) или рядом; вызывать при формировании cost перед `record_usage`/`add_spend`.

## TASK 2 — модуль budget (`app/core/budget.py`, новый)
Redis-backed дневной аккумулятор с фолбэком в память (когда `settings.state_backend != "redis"`).
- День по Бишкеку: `_bishkek_day() -> str` = `(datetime.now(timezone.utc) + timedelta(hours=6)).date().isoformat()`. (Оффсет 6 — как `followup.py:20 BISHKEK_UTC_OFFSET`; можно импортировать/вынести общий, без дублей.)
- Redis-ключ `llm_spend:<bishkek-day>`, `INCRBYFLOAT` при добавлении, `EXPIRE` ~48ч. Ленивое подключение как в `state.py:84` (`from redis import asyncio as aioredis`).
- Функции:
  - `async def add_spend(cost: float) -> None` — прибавить к дневному счётчику.
  - `async def spend_today() -> float`.
  - `async def status() -> str` — `"off"` если `settings.llm_daily_budget_usd <= 0`; иначе `"ok"` / `"soft"` (spend ≥ soft_ratio*budget) / `"hard"` (spend ≥ budget).
  - `async def soft_capped() -> bool` (status in {soft,hard}); `async def hard_capped() -> bool` (status == hard).
- Guard полностью выключен при `llm_daily_budget_usd <= 0` (дефолт) — поведение не меняется.

## TASK 3 — записывать расход
В двух async-точках, где уже вызывается `record_usage`, сразу после — вызвать `await budget.add_spend(cost)`:
- `app/agent/runner.py` `_record_llm_usage` (async-контекст `run_turn`).
- `app/agent/llm.py` `chat()`.
Cost брать реальный из usage, иначе `estimate_cost(...)` (TASK 1).

## TASK 4 — soft-cap (принудительно Haiku)
В `app/agent/runner.py` `run_turn`, рядом с `model = choose_model(spec.name, escalated)` (строка ~58): если `await budget.soft_capped()` — форсить `model = settings.llm_model_cheap`. (Практически даунгрейдит только tours+escalated в Sonnet.) Один раз залогировать переход в soft.

## TASK 5 — hard-cap (LLM off → детерминированно)
- В `app/agent/llm.py` добавить `async def llm_available() -> bool: return llm_enabled() and not await budget.hard_capped()`. `llm_enabled()` НЕ трогать.
- В воронках заменить `if llm_enabled():` на `if await llm_available():` — `app/funnels/tours.py:34`, `app/funnels/visa.py:28`, `app/funnels/tickets.py:24`. При hard-cap воронка уходит в уже существующий детерминированный путь (FAQ + сбор квалификации + handoff) — как при отсутствии API-ключа.
- Admin `suggest_reply` (`admin/router.py:792`) — оставить на `llm_enabled()` (менеджерский черновик лимитом не резать) ИЛИ тоже `llm_available()` — на твоё усмотрение; по умолчанию оставить `llm_enabled()`.
- Один раз залогировать переход в hard (для алерта/наблюдаемости).

## TASK 6 — конфиг
В `app/config.py` после `llm_temperature` (стр. ~76):
```
llm_daily_budget_usd: float = 0.0        # 0 = гард выключен
llm_daily_budget_soft_ratio: float = 0.8 # мягкий порог = ratio * бюджет
```
(env: `LLM_DAILY_BUDGET_USD`, `LLM_DAILY_BUDGET_SOFT_RATIO`.)

## TASK 7 — видимость в админке
`app/admin/router.py` `system()` (стр. ~328) — добавить в `data`: `"spend_today": await budget.spend_today()`, `"budget_usd": settings.llm_daily_budget_usd`, `"budget_status": await budget.status()`. В `app/admin/templates/system.html` рядом с LLM-статусом — карточка «Расход сегодня: $X / лимит $Y — статус (ok/soft/hard/off)», цвет по статусу (dot ok/warn/bad).

## TASK 8 — тесты (`tests/`)
- `estimate_cost`: haiku дешевле sonnet; расчёт по токенам корректный.
- budget: `add_spend` копит; `status`/`soft_capped`/`hard_capped` переключаются на порогах; `budget=0` → `"off"` и всё разрешено. (Использовать in-memory фолбэк, `state_backend != "redis"`, чтобы тесты не требовали Redis.)
- `llm_available()`: при hard_capped → False; при выключенном гарде → == llm_enabled().
- День по Бишкеку: ключ считается с оффсетом +6 (не `date.today()`).
- Не сломать существующие 187 тестов.

## Verification
`PYTHONPATH=. pytest -q` — всё зелёное. Отчёт: изменённые/новые файлы + как ведёт себя бот при status=hard (детерминированный путь, не молчит).
