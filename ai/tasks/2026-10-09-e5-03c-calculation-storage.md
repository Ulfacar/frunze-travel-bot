# TASK: E5-03C — история поездок, календарь и сохранённые расчёты

- CLASS / mode: CRITICAL / solo. Base: fix/tours-search-quality @ ef77321.
- Authorization: Алан «да давайте так и сделаем», продолжение хранения истории/расчётов по PDF.
- Target: local implementation, relevant checks, commits/handoff. No production DB/deploy.
- Builder: Codex. Independent reviewer/final auditor: UNKNOWN; completion PARTIALLY_READY
  до обязательных критических проверок. Самопроверка не заменяет независимость.

## Acceptance

1. Additive migration после e5_projection_0014: versioned StayHistory + StayInterval,
   draft WorkCalendar + WorkCalendarDay, EntryCalculation + FK links на использованные
   интервалы/календари. Никаких ALTER/seed/backfill. Populated downgrade запрещён.
2. История — полный именованный снимок одного contact: даты, основание, страна и opaque
   passport_ref, evidence/confirmation. Номер паспорта, имя/телефон и свободные notes
   не принимаются. history_complete tri-state; cutoff as_of явный. Client statement
   не подтверждается автоматически. Дубликаты/пересечения сохраняются для калькулятора.
3. Исправление — новая immutable history revision с expected_revision/CAS; предыдущая
   версия и её интервалы остаются доступными. Retry с тем же request_key/payload даёт
   прежнюю запись; другой payload не принимается как успех. Конфликт/частичный сбой
   откатывает всю операцию. Чужой contact/history/calculation нельзя смешать.
4. Календари сохраняются atomically вместе с overrides; одинаковая (год, версия)
   переиспользуется только при идентичном содержимом. Draft/provisional и отсутствие
   нужного года сохраняют существующее fail-closed поведение. Никакого official seed.
5. Trusted DB adapter строит history только из сохранённой версии; request не может
   передать history/confirmed/history_complete. Читает конкретные DB knowledge/calendar
   versions, проверяет hashes/projections. Сохранённый результат всегда review_only.
6. Сохранить input/output, immutable FK sources, hashes и environment/algorithm identity.
   Replay после новой версии истории/календаря даёт старый результат; повреждение источника,
   результата или несовпадение алгоритма/окружения не выдаются за успешный replay.
7. Auth до DB/данных: существующий named full-admin guard knowledge_import. Manager,
   bot, SYSTEM_ACTOR и поддельные объекты отклоняются. HTTP/LLM/runtime wiring отсутствует.
8. Negative/transactional/migration tests + SQLite rehearsal на synthetic данных;
   PG DDL compile отдельно от runtime. Shared models => full tests после targeted.

## Design / pre-audit

- Версионируем весь снимок истории: history_complete/cutoff и интервалы меняются атомарно.
  Это уточнение проекта superseded_by: replacement — parent revision, без мутации старых
  строк. Нельзя потерять дату/подтверждённость, использованную прошлым расчётом.
- passport_ref — opaque UUID, не произвольный passport_label/номер. Continuity вычисляется
  относительно переданного opaque reference будущей поездки; неизвестный ref => unknown.
- Calc request выбирает конкретную историю; неверная/устаревшая history revision не
  подменяется latest. Historical review не является расчётом текущего права въезда.
- Read/write service использует собственные engine sessions, не commits caller transaction.
  PostgreSQL locks + unique keys; SQLite CAS/constraints/retry. Commit uncertainty явно
  возвращается как unavailable с безопасным повтором. Ошибки без SQL/PII/DSN.
- Immutable ORM/JSON guards + DB constraints/FK + verify on reads. Привилегированный SQL
  может подделать и данные, и hash; hash не цифровая подпись. Retention/delete/DEC-06 не
  придумываем: нет real-data import или удаления; production activation требует решения.
- Replay окружения не гарантирован одним hash: сохраняем identity алгоритма и tzdata;
  при изменении runtime возвращаем явный отказ, исходный сохранённый отчёт доступен.
- Recovery: только новые таблицы; populated downgrade запрещён до отдельного решения.
  Ранее существующие структуры/active pointers/production остаются без изменений.

## Evidence plan

Targeted new domain+migration tests, adjacent knowledge tests, full `pytest tests -q`,
isolated SQLite migration and end-to-end synthetic replay; no external APIs/production.
SELF_REVIEW + independent packet/manifest, updated schema/backlog/STATE/handoff.
Independent review/final audit, PG16 runtime/concurrency, manager/LLM wiring, normative
policies/official calendar/retention remain UNKNOWN or outside this bounded local stage.

## Result / evidence index

Локальная реализация AC1–8 выполнена, **PARTIALLY_READY** по independent gates.
Targeted 67 passed (SAWarning=error); SQLite rehearsal PASS. Full suite 3161 passed,
2 failed, 8 skipped; migration test expectation исправлен, соответствующий повтор
64 passed / 2 skipped. Датозависимый facts gate воспроизведён на base ef77321,
оставлен как отдельный baseline дефект. Точные результаты/ограничения:
`ai/handoffs/2026-10-09-1857-e5-03c-calculation-storage.md`.
