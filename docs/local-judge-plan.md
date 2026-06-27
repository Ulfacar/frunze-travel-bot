# План: локальный LLM-судья (Ollama) для симулятора

## Зачем
Перестать жечь OpenRouter на LLM-судью. **Боевой бот остаётся Claude** (Sonnet через
OpenRouter) — его не трогаем. Меняем ТОЛЬКО оценку качества в тест-инструменте: судья едет
через локальную LLM (Ollama). Это для тестов, не для клиентов.

Подтверждено практикой: Haiku-судья шумит (тот же хороший ответ — то 9, то 4), а полные платные
прогоны на тонком бюджете = деньги впустую. Локальный судья даёт **бесплатный triage**.

Схема:
```
сценарий → Claude-бот (OpenRouter, платно) → локальный Ollama-судья (бесплатно) → report
```
И отдельно (самое ценное при нуле бюджета) — пересудить УЖЕ сохранённые транскрипты без бота:
```
готовые transcripts → Ollama-судья → новый report   (полностью бесплатно)
```

## Текущее состояние кода
`scripts/run_scenarios.py` уже умеет:
- `--judge-model` (дефолт `settings.llm_model_cheap`) — строка 372;
- `--no-llm-judge` — строка 371;
- судья `llm_judge(scn, run, judge_model)` — строка 181, ходит в OpenRouter через `client()`;
- вызов в main — строка 399.

Менять надо ТОЛЬКО этот файл.

## Задача (только `scripts/run_scenarios.py`)

### 1. Новые CLI-флаги
```
--judge-provider  openrouter | ollama | none   (дефолт openrouter)
--ollama-url      http://localhost:11434        (дефолт)
# --judge-model уже есть; --no-llm-judge оставить как алиас для --judge-provider none
```

### 2. Развести судью по провайдеру
Вынести сборку запроса (system + user-content) в общий код, а вызов — по провайдеру:
- **openrouter** — как сейчас (`client().messages.create`, модель из `--judge-model`).
- **ollama** — новый `httpx.AsyncClient` POST на `{ollama_url}/api/chat`:
  ```json
  {
    "model": "<--judge-model, напр. qwen2.5:7b>",
    "messages": [{"role":"system","content":"<judge system>"},
                 {"role":"user","content":"<json сценария+транскрипта>"}],
    "stream": false,
    "format": "json"
  }
  ```
  Ответ: `resp["message"]["content"]` — это строка JSON. Парсить через существующий
  `parse_json_object()`.
- **none** — то же, что текущий `--no-llm-judge` (только rule-судья, soft-правила гейтят).

### 3. Формат ответа судьи — одинаковый для обоих провайдеров
```json
{ "passed": true, "score": 8, "failures": [], "recommendation": "..." }
```
Невалидный JSON от локального судьи: НЕ ронять прогон — `passed=false`, `error_type="judge_error"`,
сохранить `raw`. (Логика уже есть в текущем `llm_judge`, переиспользовать.)

### 4. Чуть усилить judge-промпт (важно из-за scripted-десинхрона)
Добавить в system судьи:
- верни ТОЛЬКО JSON, без markdown;
- НЕ снижай оценку из-за рассинхрона скриптового клиента (клиент в тесте иногда отвечает не на
  тот вопрос — это артефакт теста, не вина бота);
- если бот извлёк данные и двигается дальше — это ПЛЮС;
- не штрафуй за «неидеально добитую анкету», если есть явный следующий шаг к
  менеджеру/консультации;
- сомневаешься — опиши в `failures`, но не выдумывай нарушения.

## Модель и установка (Ollama)
- 16 GB RAM → `qwen2.5:7b` · 32 GB → `qwen2.5:14b` (для русского лучше qwen; альтернативы:
  `llama3.1:8b`, `mistral-nemo`).
```
ollama pull qwen2.5:7b
ollama serve            # поднимает http://localhost:11434
```
Запуск симулятора с локальным судьёй:
```
python scripts/run_scenarios.py --only visa_guarantee_trap --repeats 1 \
  --judge-provider ollama --judge-model qwen2.5:7b
```

## (v2, опционально — но при нуле бюджета это золото) Режим «пересудить готовое»
Добавить подкоманду, которая берёт УЖЕ сохранённые транскрипты и судит их заново БЕЗ вызова бота:
```
python scripts/run_scenarios.py judge-existing --runs runs/<ts> \
  --judge-provider ollama --judge-model qwen2.5:7b
```
Источник транскриптов: оплаченные прогоны заархивированы на VPS `/root/sim_archive`
(базлайн 12/20 + прогон после фикса #1). Их можно стянуть локально и пересудить бесплатно.
Если делать долго — СНАЧАЛА только `--judge-provider ollama` для новых прогонов, это потом.

## Проверка (без денег)
```
python -m py_compile scripts/run_scenarios.py
python scripts/run_scenarios.py --help
python -m pytest -q
# если Ollama поднят:
python scripts/run_scenarios.py --only visa_guarantee_trap --repeats 1 \
  --judge-provider ollama --judge-model qwen2.5:7b
```

## Что НЕ делать
- НЕ трогать промпты бота, TourVisor, CRM/Bitrix, orchestrator.
- НЕ запускать платные OpenRouter-прогоны без команды.
- НЕ делать локальную LLM основным клиентским ботом (для живых клиентов — только Claude:
  лучше рус/кыргызский, tool-use, меньше галлюцинаций, продажный тон, визовые риски).

## Политика замеров (итог)
- **Часто / дёшево:** `--judge-provider ollama` (или `none` + ручной разбор).
- **Спорные кейсы:** читать транскрипт глазами.
- **Финальный контроль перед демо/релизом:** `--judge-provider openrouter --judge-model
  anthropic/claude-sonnet-4.6` (когда есть бюджет).

Локальный судья — дешёвый triage, НЕ финальная истина. Критичные выводы — глазами или Sonnet.
