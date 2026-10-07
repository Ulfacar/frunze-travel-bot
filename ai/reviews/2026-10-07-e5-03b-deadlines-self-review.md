# SELF_REVIEW — E5-03B

- Reviewer: Codex builder, **SELF_REVIEW**, не независимый reviewer/auditor.
- Base 2f71d8e; scope final uncommitted snapshot в manifest, включая новые файлы.
- Verdict: **APPROVE SELF_REVIEW** для локального этапа; общий PARTIALLY_READY.
- Independent review/final audit/owner-approved rules/calendars: UNKNOWN.

Отдельно перечитаны CALC-03/05/AC-21, task AC1–AC7, фактические модули, fixtures,
CLI, тесты и контракт. Проверены границы, ошибки и provenance, без runtime integration.

## Исправленные findings

1. При первом прогоне date-time FormatChecker оказался необязательным: без зависимости
   он принимал дату YYYY-MM-DD как timestamp, а oneOf отвергал корректные day inputs.
   Исправлено disjoint timestamp pattern + semantic stdlib datetime validation;
   отрицательные тесты удаляют optional checker и проверяют неверные дату/время/offset.
2. datetime.fromisoformat нормализует offset +06:60. Явные пределы часов/минут/секунд
   в timestamp pattern исключают такое изменение входного смысла.
3. Обработка часов сохраняет специальные причины ошибки до generic ValueError;
   неизвестный offset/нет tzdata/overflow не дают частичного результата.
4. JSON Schema допускает integral float. Calendar year/version/weekdays и rule duration
   нормализуются в int только после schema validation; bool не становится integer.

Все замечания текущего diff исправлены. Общий старый STAMP schema также опирается на
optional FormatChecker; глобальное изменение соседних форматов вне этого этапа.
Новый deadline input валидируется независимо от optional RFC3339 пакета.

## Evidence / acceptance

| Criteria | Evidence | Result |
|---|---|---|
| AC1 | duplicate/calendar semantics, order-independent hashes, owned snapshots | PASS targeted tests |
| AC2–3 | synthetic holidays/Saturday/year crossing; missing/provisional/excluded-anchor; 120 independent oracle cases | PASS targeted tests |
| AC4–5 | months/leap/bounds, 72 elapsed hours, malformed timestamps, shift and no tzdata | PASS targeted tests |
| AC6 | NULL/policy/anchor mismatch, 22 actual draft deadlines, no client exact date | PASS tests + actual PDF CLI |
| AC7 | readonly repeated CLI, hashes/mtime unchanged, strict errors | PASS tests + actual PDF CLI |
| Adjacent regressions | five knowledge modules, Windows/Python3.12 | PASS 399 / 20.39s |
| prod_traps | --diff-base 2f71d8e --limit 1 | FAIL baseline 1 ERROR / 57 WARN |
| Full suite | pure additions only, no shared runtime/DB edits | N/A for bounded diff |
| Committed copy | pending code commit | UNKNOWN until checkpoint verification |

prod_traps прежний ANTHROPIC_API_KEY forwarding; env/compose не менялись. Проверка
не открывает значения секретов. Real PDF unchanged; bundle hash прежний
bf9faa537ae600c433a064ab21b8d5969aa63ba99fc39ead224dc6fa5256dea5.

## Limits and recovery

Официальных holiday/transfers нет, fixtures явно synthetic. Source rule boundary
не интерпретируется юридически; count_anchor_day/month_end/elapsed — proposed policy.
Hashes не заменяют сохранение request/calendar/code/tzdata. Сквозной CALC-05 persistence,
runtime, DB adapter и processing-time mapping впереди. Нет схемы/данных для отката;
этот pure этап можно снять обычным последующим commit без destructive reset.
No push/deploy/production writes/real messaging. Независимый review packet подготовлен.
