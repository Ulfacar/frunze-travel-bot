# Independent review packet — E5-03C

Не verdict. Сначала прочитать требования и фактический diff; builder SELF_REVIEW и
handoff — после своего первого прохода. Доступ только read-only + изолированные тесты.

- Task: `ai/tasks/2026-10-09-e5-03c-calculation-storage.md`, AC1–8.
- CRITICAL / solo; target local implementation + commits, не release.
- Base `ef77321241319974fa392f212f8e6933b8e92e66`, branch `fix/tours-search-quality`.
- Target: UNCOMMITTED snapshot; `2026-10-09-e5-03c-calculation-storage-snapshot.json`.
- Independent reviewer/final auditor: UNKNOWN. Builder не делегировал работу.

## Requirement → implementation → scenario

| Требование | Файлы | Проверить |
|---|---|---|
| AC1 migration/recovery | models.py, e5_calculation_0015.py, test_entry_storage_migration.py | 7 новых таблиц, parity, scoped FK, partial index, отсутствие backfill, заполненный downgrade |
| AC2/3 история | storage_schema.py, entry_storage.py, test_entry_storage.py | cutoff/полнота/подтверждение в одном snapshot; CAS, дубли запросов, потерянный commit ACK, конкуренция |
| AC4 календарь | work_calendar.py, entry_storage.py | атомарность коллекции, конфликт версии, draft/provisional/нет года |
| AC5 trusted adapter | entry_calculations.py | запрет history/confirmed во входе калькулятора, DB source verification, иной contact/history |
| AC6 сохранение/replay | entry_calculations.py, models.py | pinned версии и FK, старый результат после правки истории/календаря, changed runtime/result, повреждения/удаление links |
| AC7 auth | entry_storage.py, entry_calculations.py, knowledge_import.py | named full-admin до DB; manager/bot/system/forged actor; отсутствие HTTP/LLM wiring |
| AC8 isolated proof | scripts/rehearse_kg_calculations.py, новые тесты | ambient DSN не используется, существующая БД не открывается; синтетические результаты и отсутствие клиентских точных значений |

Источники требований: `docs/e5-02-slots-schema.md` §3, CALC-02/03/05 и AC-19..22
в `docs/spec-crm-frunze-getvisa-2026-10-03.md`; исполненный контракт
`docs/e5-03c-calculation-storage.md`. Прочитать соседние knowledge import/review/projection
и pure CALC-02/03, а не только добавленные файлы.

Особое внимание: новый полный history revision вместо изменения superseded_by;
confirmation timestamps; отсутствие raw паспортных данных; privacy/retention решения
не подменяются immutable storage; Actor создаётся только trusted caller. Scoped FK
не дают самостоятельной policy доступа manager. Проверить реальный PG16 rollback,
commit failure и concurrency, прежде чем считать SQLite evidence достаточным для release.

```powershell
python -m pytest tests/test_entry_storage.py tests/test_entry_storage_migration.py -q -W error::sqlalchemy.exc.SAWarning
python -m pytest tests -q
python scripts/rehearse_kg_calculations.py --db runs/e5-03c-independent.sqlite3
```

Для CLI выбрать новый локальный filename. Не использовать production DSN, не импортировать
реальные истории, не выполнять deployment. Записать фактическую revision, команды,
findings и независимый verdict. Manifest и builder tests не заменяют review/audit.
