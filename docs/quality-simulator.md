# Quality Scenario Simulator

Автопрогон сценариев качества для Frunze Travel/GetVisa. Симулятор гоняет
реплики клиента через настоящий `Orchestrator` и фейковый канал, без Telegram,
Wappi, Postgres и CRM.

## Запуск

Быстрый локальный smoke без LLM-судьи:

```bash
python scripts/run_scenarios.py --only visa_guarantee_trap --repeats 1 --no-llm-judge
```

Полный scripted-прогон v1:

```bash
python scripts/run_scenarios.py
```

Полный прогон без расходов на судью:

```bash
python scripts/run_scenarios.py --no-llm-judge
```

Фильтры:

```bash
python scripts/run_scenarios.py --bot tours
python scripts/run_scenarios.py --bot visa
python scripts/run_scenarios.py --only tour_sea_dirty_request
python scripts/run_scenarios.py --repeats 5
```

## Важно

- Каждый сценарий по умолчанию гоняется 3 раза.
- Метрика: `STABLE_GREEN` = все повторы прошли, `FLAKY` = часть прошла, `FAILED` = ни один повтор не прошел.
- Скрипт принудительно ставит `CRM_BACKEND=stub`, `STATE_BACKEND=memory`, `PANEL_BACKEND=memory`, `DEBOUNCE_SECONDS=0` до импорта `app.*`.
- Для настоящего AI-прогона нужен `OPENROUTER_API_KEY`.
- Для tour-сценариев с живым поиском нужны `TOURVISOR_LOGIN` и `TOURVISOR_PASS`.
- Отчёты пишутся в `runs/<timestamp>/` и игнорируются git.

## Где что лежит

- `scenarios/frunze_v1.json` - стартовые 20 сценариев.
- `scripts/run_scenarios.py` - прогонщик, rule-based judge, LLM judge, отчёт.
- `runs/<timestamp>/report.md` - итоговый отчёт.
- `runs/<timestamp>/<scenario>.run<N>.txt` - полный транскрипт.
- `runs/<timestamp>/<scenario>.run<N>.judge.json` - сырой результат судей.
