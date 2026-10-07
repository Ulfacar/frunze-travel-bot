# SELF_REVIEW — E5-03A, 07.10.2026

- Reviewer: Codex, тот же builder; не independent review/audit.
- Base 1980b1a → UNCOMMITTED manifest рядом; completion local change.
- Verdict: APPROVE SELF_REVIEW; **PARTIALLY_READY**, independent review/audit UNKNOWN.

## Отдельный проход

Перечитаны task/contract, фактические новые файлы (untracked diff сам их не показывает),
fixtures, тесты и source/counting units. Проверены:

- Каждая дата плана и окно ровно window_days. Union/prefix sums не суммируют дубли;
  test oracle независимо строит множество дней. Изменённый порядок истории не меняет hash/output.
- Explicit proposed policy без defaults; inclusive/exclusive same-day; cutoff открытой поездки
  не превращается в exit. Продолжение использует original entry, не новый въезд в as_of.
- Конфликт открытой/поздней закрытой истории отвергается, но same-day exit/reentry допустимы.
- Unknown/mixed passport/basis и incomplete/unconfirmed history сохраняют flags;
  reported counts не называются гарантированным нижним пределом реальных дней.
- Candidate values берутся только из валидированного typed value, не blocked_value;
  NULL/missing policy дают needs_input. Input approval/готовый counter/PII поля отвергаются.
- Client exact remainder всегда NULL, quote/publication false независимо от input confirmed;
  first_at_limit — факт сценария, не выдуманный escalation threshold.
- Ограничения плана/окна/записей, date extrema, Unicode/cycles/NaN, приватные ошибки,
  read-only CLI и отсутствие config/DB/network imports проверены.

Во время отдельного чтения обнаружено: существующая JSON Schema integer допускает
integral JSON numbers 30.0; date ordinal требует Python int. Добавлена нормализация
после полной bundle validation и отдельный regression test. Правила в источнике не менялись.

## Evidence

- Первичный new module: 61 passed / 3.77s; затем 10 proposed examples и adversarial cases.
- До numeric fix: 299 passed / 25.07s. **Финальный прогон: 300 passed / 25.01s**,
  stay_days/conditions/country_index/entry_validation, включая 80 новых тестов и 200 seeded oracle scenarios.
- Real PDF CLI: computed_scenario, присутствие [31,31,31,31]; three COUNT_* decision_pending,
  exact_remaining_days=NULL/may_quote=false. Bundle/catalog/request SHA+mtime unchanged.
  Machine evidence: `runs/e5-03a-stay-review-20261007.json`; последний numeric fix не меняет этот integer-input результат.
- prod_traps --diff-base 1980b1a --limit 1: прежний **FAIL 1 ERROR / 57 WARN**,
  ANTHROPIC_API_KEY compose forwarding; значений секретов в отчёте нет.
- Full suite не повторялась: только новые pure modules/CLI/fixtures и документы, без
  edits runtime/DB/import/старых knowledge modules. Предыдущие 2917 tests — evidence E5-02F, не этот прогон.
- Committed-copy verification pending; записать фактическую revision/результат после commit.

## Gates / limits

Независимые review/final audit и Q4/CALC-02 owner-approved policies/examples UNKNOWN.
Нет допуска к production, нормативного утверждения/ЕСУВМ, persistence личной истории,
рабочего календаря/сроков/стоимости. Rollback локального кода не требует миграций.
