# Independent review packet — E5-03A

Это вход для независимого reviewer/auditor, не verdict. Сначала читать требования,
фактический код и примеры; builder SELF_REVIEW/handoff — после собственного первого прохода.

- Task: `ai/tasks/2026-10-07-e5-03a-stay-days.md`, AC1–AC7.
- Protocol: AGENTS.md / ai/protocol.json / ai/ROLES.md; CRITICAL / solo.
- Base: `fix/tours-search-quality` @ 1980b1a;
  target **abad74f69430f6a54ba6fd514df54ef7b54167e7**, manifest
  `ai/reviews/2026-10-07-e5-03a-stay-days-snapshot.json`.
- Independent reviewer / final auditor: UNKNOWN.
- Scope: local pure review arithmetic, без release/DB/runtime. Только read-only анализ
  и isolated tests; без production, внешней отправки кода, изменения исходных норм/approval.

## Требования и фактические файлы

1. `docs/spec-crm-frunze-getvisa-2026-10-03.md`: CALC-02/05, AC-19/20;
   `docs/e5-02-slots-schema.md`: §3.4, §3.5/Q4; PDF physical p24 / derived §2.9.
2. `docs/e5-03a-stay-days.md`: observable scope, interpretation proposed policy, границы.
3. `app/knowledge/stay_schema.py`, `stay_days.py`, adjacent bundle validation/review.
4. `scripts/review_kg_stay_days.py`, `tests/test_kg_stay_days.py`, fixtures
   `synthetic_stay_review.json` и `stay_review_examples.json`.

Проверить каждый день окна, объединение интервалов, включительность, открытый cutoff
vs выезд, продолжение vs новый въезд, same-day edges, Gregorian leap/year/ordinal bounds.
Проверить независимость randomized oracle от prefix sums реализации, а также вручную
предлагаемые примеры. Флаги/даты/подтверждённость предоставлены вызывающим кодом;
они не должны открыть права публикации. Исчезающий на последней дате excess должен
оставаться в first_exceeded_date. Headroom не должно называться разрешённым сроком.

Не допустить потери неизвестной истории, смены паспорта/основания, использования
blocked evidence вместо value или утверждения proposed policy клиентским входом.
Убедиться, что прежние COUNT_* остаются NULL, старые файлы знаний неизменны и код
не подключён к slots, DB, LLM, HTTP endpoint. CALC-03/04 и история в БД не входят в scope.

```powershell
python -m pytest tests/test_kg_stay_days.py tests/test_kg_conditions.py tests/test_kg_country_index.py tests/test_kg_entry_validation.py -q
python -X utf8 scripts/review_kg_stay_days.py knowledge/kg_entry/draft-v1.1 --source "../Kyrgyzstan-visa-knowledge-base-v1.1.pdf" --request tests/fixtures/kg_entry/synthetic_stay_review.json
```

Результаты фиксировать с фактической revision/командой. Hash файла/примеров не заменяет
подпись владельца знаний или юридическую проверку. Отдельный final audit проверяет
требования, review findings, recovery/no runtime changes и остающиеся gates.
