# СПЕКА для Codex — Экономия токенов, Фаза 1 (роутинг + кэш + учёт usage)

Автор плана: Claude (ревьюит дифф). Исполнитель: Codex. Ревью: агент `codex-reviewer` (Opus).
Ветка: создать `feature/token-economy-phase1` от `main`. НЕ деплоить — только код + тесты.

## Контекст проекта (обязательно учесть — project gotchas)
- Продовый LLM идёт через **OpenRouter** (OpenAI-совместимый `/chat/completions`), адаптер `app/agent/llm.py`. Модели в проде (prod.env): `LLM_MODEL_MAIN=anthropic/claude-sonnet-4.6`, `LLM_MODEL_CHEAP=anthropic/claude-haiku-4.5`. В коде — поля `settings.llm_model_main` / `settings.llm_model_cheap` (`app/config.py`).
- Диалоги ключуются по `bot_id:phone`. Воронка фиксирована per-bot (`BotConfig.scenario`): tours / visa / tickets.
- Боевой цикл: `app/core/orchestrator.py` → `app/agent/runner.py` (`run_turn`, `run_visa_turn`). Сейчас **везде** используется `settings.llm_model_main` (Sonnet). Cheap-модель в проде НЕ используется нигде.
- FAQ/детерминированный слой уже работает ДО LLM (`orchestrator._maybe_faq_reply`, `app/core/faq.py`, `app/core/visa_pricing.py`). Не ломать.
- Handoff→молчание работает (`state.intercepted`). Не трогать.
- `bots_enabled` — общий рубильник; не задевать его логику.
- Тестов на TourVisor нет; юнит-тесты есть на llm-adapter/panel/state — не сломать, дополнить.

## ЦЕЛЬ ФАЗЫ 1
1. Роутинг моделей по воронкам + эскалация в Sonnet на поиске туров.
2. Prompt caching статического system-промпта (lossless).
3. Захват `usage` из ответа OpenRouter + логирование стоимости.
4. Right-size `max_tokens` + `temperature`.
5. Покрыть тем же кэшем admin `suggest_reply`.
НЕ входит в Фазу 1 (отдельные фазы): сворачивание истории в summary, дашборд расходов в /admin, budget-guard.

---

## TASK 1 — Роутинг моделей
Добавить выбор модели вместо жёсткого `settings.llm_model_main`.

- Хелпер (например в `app/agent/runner.py` или новый `app/agent/routing.py`):
  `def choose_model(scenario: str, escalated: bool) -> str` →
  - `visa` → `settings.llm_model_cheap` (всегда).
  - `tickets` → `settings.llm_model_cheap` (всегда).
  - `tours` → `settings.llm_model_main` если `escalated` иначе `settings.llm_model_cheap`.
- **Эскалация для tours** (`run_turn`):
  - Начинать турн на cheap-модели.
  - Внутри tool-loop: как только ассистент вызвал инструмент **`search_tours`** — переключить модель на `main` для всех последующих LLM-вызовов в этом турне (презентация подбора — денежный момент).
  - Плюс предпроверка входящего сообщения по ключевым словам (цена/бронь/оплата/возражение: `брон`, `оплат`, `цена`, `стоимост`, `дорог`, `скидк`) → сразу `escalated=True`.
- `run_visa_turn` — передавать cheap-модель.
- Модель прокидывать в `client().messages.create(model=...)` (сейчас захардкожено на main в `runner.py:~57`).
- Всё configurable через существующие поля; не хардкодить строки моделей.

## TASK 2 — Prompt caching (OpenRouter/Anthropic)
В `app/agent/llm.py` `OpenRouterMessages.create()`:
- Системный промпт передавать блоком с cache-брейкпоинтом (OpenAI-совместимый формат OpenRouter для Anthropic): content системного сообщения как список частей:
  `[{"type":"text","text":<system>,"cache_control":{"type":"ephemeral"}}]`.
- **Guard:** добавлять `cache_control` ТОЛЬКО если модель Anthropic (`model.startswith("anthropic/")`), иначе оставить прежний строковый `content` (не ломать других провайдеров).
- Порядок рендера `tools → system → messages` — кэш это префикс-матч. tools уже статичны per-funnel — НИЧЕГО в них per-request не менять (иначе кэш инвалидируется). Системный промпт байт-стабилен, кроме `.replace("Адеми", name)` per-bot — это ок.
- НЕ добавлять в system-промпт волатильных данных (дата/uuid/счётчики) — иначе кэш не сработает.

## TASK 3 — Захват usage
- В `_from_openai_response()` (`app/agent/llm.py`) прочитать `data.get("usage")`: `prompt_tokens`, `completion_tokens`, `total_tokens`, и если есть — `usage.cost` / кэш-поля (`cache_read_input_tokens`/`cache_creation_input_tokens` могут прийти в `usage` от OpenRouter для Anthropic — прокинуть если присутствуют).
- Прокинуть usage наверх из `create()` (например вернуть в объекте ответа/структуре, не ломая существующих вызовов — расширить возвращаемый тип аккуратно).
- В `app/core/observ.py` добавить `record_usage(model, prompt_tokens, completion_tokens, cost, bot_id, user_id)` — минимум: структурный лог INFO + агрегатные счётчики в памяти (per-day). Персист в БД (`audit_log` event) — желательно, но если сложно, оставить TODO-хук.
- Вызвать `record_usage` из места, где получаем ответ (orchestrator/runner), с bot_id/user_id из state.

## TASK 4 — max_tokens + temperature
- Новые поля конфига: `llm_max_tokens: int = 512`, `llm_temperature: float = 0.3` (`app/config.py`, env `LLM_MAX_TOKENS`/`LLM_TEMPERATURE`).
- Применить в payload (`llm.py`) и в вызовах (`runner.py`, `llm.chat`). Сейчас `max_tokens=1024` захардкожено в двух местах — заменить на config. `temperature` сейчас не задаётся — задать из config.

## TASK 5 — Покрыть suggest_reply
- Путь `app/admin/router.py` `suggest_reply` → `chat()` (`llm.py`) должен получить тот же cache_control на system-промпте (через тот же create()). Убедиться, что модель для suggest берётся осмысленно (можно cheap по умолчанию — это подсказка менеджеру, не клиенту; сделать через config-флаг или cheap).

## Тесты
- Юнит на `choose_model` (все воронки, escalated/не).
- Юнит: при anthropic-модели в payload system становится списком с `cache_control`; при не-anthropic — строкой.
- Юнит: usage парсится и `record_usage` вызывается.
- Не сломать существующие тесты llm-adapter/state/panel: `PYTHONPATH=. pytest`.

## Definition of done
- `pytest` зелёный.
- Ни один прод-путь не шлёт волатильные данные в system-префикс.
- visa/tickets на cheap, tours на cheap с эскалацией в main на `search_tours`.
- usage логируется на каждый LLM-вызов.
- Обычные вопросы по-прежнему закрываются FAQ до LLM (не регрессить).
