# Independent review packet — E5-03B

Вход для независимого reviewer/auditor, не verdict. Сначала требования и фактические
файлы; builder SELF_REVIEW/handoff читать после собственного первого прохода.

- Task: `ai/tasks/2026-10-07-e5-03b-deadlines.md`, AC1–AC7.
- CRITICAL / solo; completion target local implementation + authorized commits.
- Base: `fix/tours-search-quality` @ 2f71d8e; target UNCOMMITTED snapshot до code commit.
- Manifest: `ai/reviews/2026-10-07-e5-03b-deadlines-snapshot.json`.
- Independent reviewer / final auditor: UNKNOWN.
- Read-only review + isolated local tests; без production/публикации/отправки private
  repository внешнему сервису. Builder не делегировал проверку другому агенту.

## Требования и файлы

1. CALC-03/05, AC-21: `docs/spec-crm-frunze-getvisa-2026-10-03.md`; PDF блок 13,
   физические страницы 61–62; §3.4 `docs/e5-02-slots-schema.md`.
2. `docs/e5-03b-deadlines.md`: observable contract и границы предложенной политики.
3. `app/knowledge/deadline_schema.py`, `work_calendar.py`, `deadlines.py`;
   соседние bundle validation, canonical hashing и review_findings.
4. `scripts/review_kg_deadline.py`, `tests/test_kg_deadlines.py`, fixtures
   `synthetic_work_calendars.json`, `synthetic_deadline_review.json`.

Проверить before/after/inclusive, рабочую субботу, переносы обоих направлений, смену
года и fail-closed coverage (включая исключённый anchor), отсутствие office fallback.
Проверить month anniversary/clamp/reject без итеративного накопления округления,
elapsed UTC hours, explicit offset/unknown -00:00, отсутствие tzdata и overflow.
Проверить RFC3339 без optional dependency: схема не должна принимать date как timestamp,
а datetime.fromisoformat не должен нормализовать неправильные минуты смещения.

Calendar complete — заявление входа, не official approval. Не должно появиться client
date или quote permission, включая synthetic confirmed unit; реальные 22 NULL values
не подменяются числами из evidence. Raw source boundary_inclusive не утверждает
proposed count_anchor_day. Request не выбирает amount/shift вне source rule.
Проверить owned copies, стабильность хешей при перестановках, изменение identity при
смене версии/дня, discard partial result, limits и независимость oracle от алгоритма.

Команды из contract; проверить read-only CLI с synthetic source и original PDF через
явно указанный путь. Реальный KG.DL.REGISTRATION_OUTSIDE_LIST должен вернуть
rule_value_missing/NULL scenario. Exit 0 означает валидный отчёт, не готовую дату.
No DB/runtime/import-source mutations. Approval, calendar persistence и production
не входят в этот diff; итоговый аудит обязан сохранить соответствующие UNKNOWNs.

Фиксировать реально проверенную revision, команды, findings и evidence. Manifest не
равен review approval; self-review и historical full-suite не заменяют независимость.
