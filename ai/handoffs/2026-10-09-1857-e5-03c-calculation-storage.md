# HANDOFF: 2026-10-09-1857 — E5-03C calculation storage

- STATUS: **PARTIALLY_READY**; CLASS / MODE: **CRITICAL / solo**.
- Task: `ai/tasks/2026-10-09-e5-03c-calculation-storage.md`; project `ai/PROJECT.md`.
- Branch: `fix/tours-search-quality`; base ef77321; target UNCOMMITTED snapshot.
- Completion target: local implementation + authorized commits; production не входит.
- Алан подтвердил продолжение хранения истории/расчётов и сообщил, что вернулся к работе.

## Outcome and files

Миграция e5_calculation_0015 добавляет семь таблиц: immutable StayHistory/StayInterval,
draft WorkCalendar/Day, EntryCalculation и links. Versioned полный снимок истории
с cutoff/полнотой заменяет проектный mutable superseded_by, без перезаписи прошлого.
passport_ref — opaque32hex/null. Только named full-admin через существующий guard.

DB adapter строит историю калькулятора исключительно из БД, сохраняет input/output,
FK источников и runtime identity, проверяет replay. CAS/idempotency, целостность,
rollback и потеря commit ACK покрыты проверками. ORM JSON/rows неизменяемы; privileged
SQL вне границы, обнаруживается несогласованность hashes/projections/links.

Контракт `docs/e5-03c-calculation-storage.md`; реализация `app/domain/entry_storage.py`,
`entry_calculations.py`, models; schema `app/knowledge/storage_schema.py`;
CLI `scripts/rehearse_kg_calculations.py`. Backlog, slots schema и PDF progress обновлены.
Нормативный bundle не изменялся. Бот/HTTP/LLM не подключены.

## Evidence

| Claim | Command/scenario | Environment/revision | Result | Limitation |
|---|---|---|---|---|
| AC1–8 local behavior | pytest test_entry_storage.py test_entry_storage_migration.py, SAWarning=error | Windows/Python3.12, uncommitted final code | PASS, 67 / 48.44s | SQLite, не PG16 |
| Recovery/replay | scripts/rehearse_kg_calculations.py --db runs/e5-03c-calculation-verified-20261009.sqlite3 | новая локальная SQLite, same code | PASS, 1/1/2/6/2/1/2 rows, replay=true | fixtures synthetic |
| Calculator boundary | CLI и service tests | same | PASS, presence6/due08.10, exact=NULL/may_quote=false | не клиентский ответ |
| Shared regression | python -m pytest tests -q --tb=short | same | FAIL: 3161 passed, 2 failed, 8 skipped, 1 warning / 408.80s | один stale migration expectation исправлен, один baseline |
| Migration/services after fix | pytest service_cases + alembic_domain_migration + entry_storage_migration | final snapshot | PASS: 64 passed, 2 skipped / 21.23s | PG tier skips |
| Baseline failure isolation | test_facts_live_errors::test_still_reads_a_plain_request | отдельная Git archive ef77321 без .env | FAIL: 1 / 0.38s | даты зависят от текущего дня |
| PG DDL | targeted migration test | offline PostgreSQL compiler | PASS | runtime/concurrency UNKNOWN |
| Existing release gate | prod_traps --diff-base ef77321 --limit 1 | local | FAIL, 1 ERROR / 57 WARN | прежний compose forwarding, вне этапа |
| Whitespace | git diff --check | local | PASS | не semantic review |
| Independent review/final audit | packet prepared | — | UNKNOWN | SELF_REVIEW не заменяет |

## Review and remaining gates

`ai/reviews/2026-10-09-e5-03c-calculation-storage-self-review.md` — SELF_REVIEW.
Independent packet и snapshot manifest рядом. Проверка нашла утечку соединения при
after_commit exception; исправлена, три сценария подтверждают cleanup и идемпотентность.
Нужны independent review/final audit, PG16 runtime/concurrency, утверждение эталонов,
официального календаря и норм. DEC-06/07 не закрыты. Нет production authorization.

## Baseline failure outside this scope

Старый gate ожидает dates из «с 7 по 14 октября». На исходном ef77321 он тоже падает
09.10; в изолированном процессе clock=06.10 проходит, clock=09.10 не даёт dates.
_parse_dates переносит начало в следующий год, facts._dates отсекает >310 дней.
Парсер и этот gate не изменялись. Отдельно нужно решить контракт прошедших дат и
стабилизировать контрольный тест; полный suite не считается зелёным.

## Next action / resume

1. Независимому reviewer/auditor прочитать packet, task и фактический diff до builder conclusions.
2. Следующий implementation scope: согласовать единый выбор режима/квалификацию и
   trusted manager adapter; scoped access и HTTP/LLM требуют отдельной проверки.
3. По PDF остаётся ориентировочно 70–80%, без измеренного нового процента. Persistence
   добавлен, но публикация знаний, RU/EN диалог, Applicant/Application и сквозная приёмка впереди.

Пользовательские аудио/архивы/выгрузки и pytest-temp сохранены untracked. В Git добавлять
только файлы этого этапа. GitHub public: секреты и клиентские данные не включать.
