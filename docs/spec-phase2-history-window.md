# СПЕКА для Codex — Фаза 2: окно истории для LLM

Автор: Claude (ревьюит). Исполнитель: Codex. Ветка: `feature/token-economy-phase1`. Не деплоить/не пушить/не коммитить.

Цель: перестать слать в LLM всю растущую историю каждый ход (главный тур-жор токенов на длинных диалогах). Слать только последние N сообщений (окно), не теряя собранные параметры.

## Project gotchas (обязательно)
1. **Резать историю можно ТОЛЬКО на границе `{"role":"user", "content": <str>}`** (начало реплики клиента). Между `tool_use` (assistant, content=список блоков) и `tool_result` (user, content=список блоков) рвать НЕЛЬЗЯ — OpenRouter/Anthropic отклонит запрос (осиротевший tool_result → 400). Формы записей истории (`runner.py`): user-строка (53), assistant-блоки/tool_use (72), user-блоки/tool_result (80), assistant-строка (90).
2. **Окно делать read-only на отправке — НЕ мутировать `state.history`** (в хранилище оставить полную; так безопаснее и панель/manager_brief не трогаем; Redis-рост вторичен, ограничен 7-дн TTL).
3. `state.qualification` (структурные факты) НЕ инжектится в контекст LLM (`runner.py`/промпты) — только история. Значит окно БЕЗ инжекта параметров = бот забудет направление/даты. Инжектить **отдельным сообщением**, НЕ в `system` (system+tools — кэшируемый префикс Фазы 1; менять его каждый ход = убить кэш).
4. Панель истории — из Postgres (`panel/store.py`), не из `state.history`. Обрезка окна её не затрагивает.

## TASK 1 — конфиг (`app/config.py`)
После `llm_temperature` (~стр.76): `llm_history_max_messages: int = 40  # 0 = без окна (слать всё)`.

## TASK 2 — хелперы окна (в `app/agent/runner.py` или новый `app/agent/history.py`)
```python
def _windowed_history(history: list[dict], max_n: int) -> list[dict]:
    """Вернуть безопасный хвост истории (<= ~max_n сообщений), начинающийся на границе
    реплики клиента (user-строка), чтобы не осиротить tool_result."""
    if max_n <= 0 or len(history) <= max_n:
        return history
    bounds = [i for i, m in enumerate(history)
              if m.get("role") == "user" and isinstance(m.get("content"), str)]
    if not bounds:
        return history  # нет безопасной границы — шлём всё (редко)
    target = len(history) - max_n
    later = [i for i in bounds if i >= target]
    start = later[0] if later else bounds[-1]  # <=max_n и чисто; иначе — начало последней реплики
    return history[start:]


def _qual_context_message(qual: dict) -> dict | None:
    """Компактный контекст собранных параметров — отдельным user-сообщением (не в system)."""
    parts = [f"{k}={v}" for k, v in (qual or {}).items() if v]
    if not parts:
        return None
    return {"role": "user", "content": "[Уже известно от клиента: " + ", ".join(parts) + "]"}
```

## TASK 3 — применить в `run_turn` (`app/agent/runner.py`)
Заменить `messages=state.history` (стр.~61) на собранное окно, вычисляемое НА КАЖДОЙ итерации tool-loop (история растёт внутри хода):
```python
        window = _windowed_history(state.history, settings.llm_history_max_messages)
        qual_msg = _qual_context_message(state.qualification)
        messages = ([qual_msg] + window) if qual_msg else window
        resp = await client().messages.create(
            model=model, max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature, system=spec.system,
            tools=spec.tools, messages=messages,
        )
```
- НЕ мутировать `state.history` — окно только для отправки. `state.history.append(...)` в цикле остаётся как есть (полная история хранится).
- Убедиться, что окно пересчитывается каждую итерацию (внутри `for _ in range(MAX_TOOL_ITERATIONS)`), чтобы текущие tool_use/tool_result всегда были в хвосте и не осиротели.

## TASK 4 — тесты (`tests/`, напр. `test_history_window.py`)
`_windowed_history`:
- history короче/равно max_n → без изменений.
- длинная история → результат начинается с `{"role":"user","content":<str>}` (никогда с tool_result), длина <= max_n (или ровно с начала последней реплики, если последняя реплика длиннее max_n).
- смоделировать последовательность user-строка → assistant/tool_use → user/tool_result → assistant-строка (несколько циклов) и проверить, что окно НЕ начинается на tool_result-сообщении ни при каких max_n.
- max_n=0 → возвращает всё.
`_qual_context_message`:
- пустой qual → None; непустой → user-сообщение со всеми непустыми параметрами.
Интеграция (по образцу существующих `tests/test_agent_loop.py`): при длинной истории в `messages.create` уходит окно + qual-сообщение, tool-loop не ломается; при короткой — как раньше. Не сломать существующие 212 тестов.

## TASK 5 — прогон
`PYTHONPATH=. pytest -q` — зелёное. Отчёт: файлы + pytest + пример окна (что начинается на user-строке, tool_result не осиротел, qual-сообщение добавлено).
