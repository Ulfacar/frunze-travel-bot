# СПЕКА для Codex — детерминированное приветствие персоны (без LLM)

Автор: Claude (ревьюит). Исполнитель: Codex. Ветка: `feature/token-economy-phase1`. Не деплоить/не пушить/не коммитить.

Цель: когда ПЕРВОЕ сообщение клиента — это голое приветствие (без сути), бот отвечает готовым персона-шаблоном (Адеми/Сезим — туры, Медина — визы) + первый вопрос, БЕЗ вызова LLM. Экономит самый частый опенер (~34/4дня на проде) и делает приветствие идентичным.

## Факты (разведка)
- Приветствие сейчас генерит LLM (инструкция в `app/agent/prompts/common.py:37`), детерминированного шаблона НЕТ.
- Хук: `app/core/orchestrator.py` `_run_turn`, МЕЖДУ резолвом воронки (после ~L208) и `_maybe_faq_reply` (~L210). До этого места уже отработали guards `intercepted` (L193) и `_bots_on` (L185), и заданы `state.manager_name` (L183, = Адеми/Сезим/Медина) и `state.funnel` (L201).
- Первое сообщение = `not state.history` (пустой список) — надёжный флаг (проверять ДО добавления в history).
- Персона: `state.manager_name`. Воронка: `state.funnel` (tours/visa). Тур-ботов два (Адеми/Сезим) — различаются только manager_name.
- Утилита нормализации есть: `app/core/faq.py normalize_text` (ниж.регистр, ё→е, убрать пунктуацию, схлопнуть пробелы).
- В `_ask_for` первых полей (`tours.py`/`visa.py`) уже вшито «Здравствуйте! 😊» — НЕ переиспользовать целиком (двойное приветствие), брать чистый вопрос.

## TASK 1 — детектор голого приветствия (`app/core/faq.py` или новый util)
`is_bare_greeting(text: str) -> bool`: матч по `normalize_text(text)` ПОЛНОЙ строкой (якоря ^...$), только приветствие (+ опционально безобидный «можно узнать подробнее»):
```python
_GREETING_ONLY_RE = re.compile(
    r"^(?:здравствуйте|здравствуй|привет|приветствую|салам|ассалам(?:у алейкум)?|"
    r"assalam(?:u alaikum)?|hi|hello|добрый день|доброе утро|добрый вечер|"
    r"саламатсызбы|/start)"
    r"(?:\s+(?:можно узнать(?: об этом)? подробнее|можно подробнее|подробнее))?$",
    re.IGNORECASE,
)
def is_bare_greeting(text: str) -> bool:
    return bool(_GREETING_ONLY_RE.match(normalize_text(text)))
```
Требование: «здравствуйте» / «привет» / «салам алейкум» / «здравствуйте можно узнать подробнее» → True; «здравствуйте хочу тур в турцию», «здравствуйте расскажите про визу сша», «когда рейсы» → False (есть суть).

## TASK 2 — персона-приветствие (`app/core/branding.py`)
Чистая функция:
```python
def persona_greeting(funnel: str | None, manager_name: str) -> str | None:
    name = (manager_name or "").strip() or ("Медина" if funnel == "visa" else "Адеми")
    if funnel == "tours":
        return (f"Здравствуйте! 😊 Я {name}, менеджер Frunze Travel по турам. "
                f"Какое направление рассматриваете? (страна или «помогите выбрать»)")
    if funnel == "visa":
        return (f"Здравствуйте! 😊 Меня зовут {name}, я ваш визовый эксперт Frunze Travel. "
                f"Как могу к вам обращаться?")
    return None  # прочие воронки — не перехватываем
```

## TASK 3 — хендлер в оркестраторе (`app/core/orchestrator.py`)
Добавить метод `_maybe_persona_greeting(self, msg, state, store) -> bool` и вызвать его в `_run_turn` СРАЗУ после резолва воронки и ДО `_maybe_faq_reply`:
```python
        if await self._maybe_persona_greeting(msg, state, store):
            return
        faq_reply = await self._maybe_faq_reply(msg, state, store)
```
Логика метода (fail-open — обернуть в try/except, при любой ошибке вернуть False и идти обычным путём):
1. Guard: `if state.history: return False` (только первое сообщение). `if state.pending_field: return False`.
2. `if not is_bare_greeting(msg.text): return False`.
3. `greeting = persona_greeting(state.funnel, state.manager_name)`; `if not greeting: return False`.
4. Записать в историю (как делает `_maybe_faq_reply`): `state.history.append({"role":"user","content":msg.text})` и `{"role":"assistant","content":greeting}` — чтобы LLM на 2-м ходу не повторял приветствие (правило `common.py:17`).
5. `await store.save(state)`, `await self._sync_card(msg, state)` (как в FAQ-пути, если метод так называется — свериться), `await self._reply(msg, greeting)`, вернуть `True`.
6. Пометить в observ как детерминированный ответ, если есть аналогичный механизм (не обязательно).
НЕ вызывать `funnel.handle`/LLM для этого хода.

## TASK 4 — тесты (`tests/`)
- Первое «здравствуйте» на tours-боте (manager_name="Адеми") → ответ содержит «Адеми» и «направление», LLM НЕ вызывается, в `state.history` 2 записи, метод вернул True.
- Первое «здравствуйте» на визовом (Медина) → «Медина» + «как могу к вам обращаться».
- Sezim-бот (manager_name="Сезим") → в приветствии «Сезим».
- «здравствуйте, хочу тур в турцию» (первое) → `_maybe_persona_greeting` вернул False (идёт в обычный путь).
- Второе сообщение (history не пустой) с «привет» → False.
- `is_bare_greeting`: юнит на True/False кейсы из TASK 1.
- Не сломать существующие тесты оркестратора/faq.

## TASK 5 — прогон
`PYTHONPATH=. pytest -q` — зелёное. Отчёт: файлы + pytest + пример приветствия для Адеми/Сезим/Медина и что «здравствуйте+суть» не перехватывается.
