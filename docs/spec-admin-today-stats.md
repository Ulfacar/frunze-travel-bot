# СПЕКА для Codex — статистика «за сегодня» в /admin/analytics

Автор: Claude (ревьюит). Исполнитель: Codex. Ветка: `feature/token-economy-phase1`. Не деплоить/не пушить/не коммитить.

Цель: добавить на страницу аналитики блок «Сегодня» — сколько за сегодня диалогов, сообщений (клиент/бот/менеджер), по воронкам, и (для админа) расход $ и статус лимита. Read-only, поведение бота не меняется.

## Факты (разведка)
- Страница уже есть: `GET /admin/analytics` (`app/admin/router.py:316-327`) → `compute_analytics(convs, period, now)` (`app/integrations/panel/analytics.py:53-119`), рендер `app/admin/templates/analytics.html` (`.cards`/`.kpi` тайлы). `convs` уже отфильтрованы по скоупу менеджера (`_filter_conversations`).
- `ConversationView.messages` доступны (eager-load), у сообщений есть `sender` (client/bot/manager) и `created_at`.
- «Сегодня» сейчас = UTC-полночь (`_period_start("today")` в `analytics.py:29-37`) — сдвиг на 6ч от Бишкека. Надо по Бишкеку (UTC+6), как `budget._bishkek_day`/`followup.BISHKEK_UTC_OFFSET=6`.
- Расход: `await budget.spend_today()` (float $), `await budget.status()` (off/ok/soft/hard) — глобальные, не по воронкам. `observ.snapshot()["usage_daily"][<UTC-date>]` → `{calls, total_tokens, cost, ...}`. Уже используются в `/admin/system`.
- Скоуп: `_manager_bot_scope(manager) is None` = админ (видит всё). Не-админ видит только свои диалоги (уже отфильтровано). Расход глобальный → показывать только админу.
- Стиль тайлов: `.cards`/`.kpi` (`analytics.html:20-24`), тайл = `.kpi` с `.n` (число) и `.l` (подпись), варианты `.kpi.good`/`.kpi.warm`.

## TASK 1 — helper начала дня по Бишкеку
В `app/core/budget.py` (рядом с `_bishkek_day`) добавить публичную:
```python
def bishkek_day_start_utc(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    local = base.astimezone(timezone.utc) + timedelta(hours=6)
    local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight - timedelta(hours=6)  # UTC-инстант бишкекской полуночи
```
Опционально: `analytics._period_start("today")` привести к этому же (чтобы существующий фильтр «Сегодня» тоже был по Бишкеку). Не ломать 7d/30d/all.

## TASK 2 — расчёт статистики за сегодня (`app/integrations/panel/analytics.py`)
Новая чистая функция `compute_today_stats(convs, now) -> dict`, работает на уже загруженных/отфильтрованных `convs`:
- `start = bishkek_day_start_utc(now)`.
- `dialogs_active`: число диалогов, у которых есть хоть одно сообщение с `created_at >= start` (или `last_message_at >= start`).
- `dialogs_new`: число диалогов с `created_at >= start`.
- `messages`: {"client": N, "bot": N, "manager": N} — перебрать `c.messages`, отфильтровать `created_at >= start`, сгруппировать по `sender`.
- `by_funnel`: {funnel: dialogs_active_count} по `tours/visa/tickets` (диалоги с активностью сегодня, сгруппировать по `c.funnel`).
- `waiting`: число диалогов, где клиент ждёт ответа (`c.last_sender == "client"` и не архив).
Аккуратно с tz: сравнивать tz-aware; если у сообщения `created_at` naive — считать UTC.

## TASK 3 — роутер (`app/admin/router.py` `analytics`)
После `compute_analytics(...)`:
- `today = compute_today_stats(convs, _now())`.
- Если админ (`_manager_bot_scope(manager) is None`): добавить в `today` (или отдельным dict) `spend_today = await budget.spend_today()`, `budget_status = await budget.status()`, `budget_usd = settings.llm_daily_budget_usd`, и `llm_calls`/`llm_cost` из `observ.snapshot()["usage_daily"].get(date.today().isoformat(), {})`. Для не-админа эти поля НЕ передавать (или None) — не показывать глобальный расход не-админу.
- Передать `today` в контекст шаблона.

## TASK 4 — шаблон (`app/admin/templates/analytics.html`)
Вверху страницы добавить панель «Сегодня» с `.cards`/`.kpi` тайлами:
- Диалоги сегодня (`today.dialogs_active`), из них новых (`today.dialogs_new`).
- Сообщения: Клиент / Бот / Менеджер (`today.messages.client/bot/manager`).
- По воронкам: Туры / Визы / Билеты (`today.by_funnel`).
- Клиент ждёт (`today.waiting`) — вариант `.kpi.warm` если > 0.
- ТОЛЬКО если переданы поля расхода (админ): тайл «Расход сегодня $spend / $budget (status)» с цветом по статусу (ok/soft/hard/off), и «Вызовов LLM сегодня» (`llm_calls`).
Стиль — как существующие `.kpi` на этой странице.

## TASK 5 — тесты (`tests/`)
- `bishkek_day_start_utc`: для заданного UTC-времени возвращает корректный UTC-инстант бишкекской полуночи (напр. 2026-07-02T05:00Z → это уже 11:00 Бишкека 02.07 → старт = 2026-07-01T18:00Z).
- `compute_today_stats`: на наборе диалогов/сообщений с разными `created_at` (вчера/сегодня по Бишкеку) правильно считает dialogs_active/new, messages по sender, by_funnel, waiting; сообщения «вчера» не попадают.
- Не сломать существующие тесты аналитики/панели.

## TASK 6 — прогон
`PYTHONPATH=. pytest -q` — зелёное. Отчёт: файлы + pytest + что показывает блок «Сегодня».
