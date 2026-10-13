# TASK: E5-02F — атомарное сохранение индекса и условий

- CLASS / mode: CRITICAL / solo; расширение хранилища и транзакционного импорта.
- Completion target: local change; PARTIALLY_READY до независимого review/final audit.
- Base: fix/tours-search-quality @ bd1a84e. Builder: Codex; reviewer/auditor: UNKNOWN.
- Authorization: Алан «дальше», ранее «сделайте комиты»; локальная реализация, проверки и commits. Без push/deploy/production DB.

## Scope and acceptance

Новый импорт сохраняет неизменяемую проекцию country index и необязательный явно
переданный каталог условий вместе с draft/units/accepted journal. Индекс содержит
ссылки на кандидатов, не выбранное право въезда. Условия остаются отдельными:
постоянное проживание нельзя записывать как гражданство.

| ID | Scenario | Expected evidence |
|---|---|---|
| AC1 | Migration 0013 → 0014 → 0013 → 0014 | Additive, старые данные неизменны; populated downgrade запрещён; ORM/schema parity |
| AC2 | PDF bundle + catalog | 208 units, 201 country links, 6 condition links; SQL NULL/статусы/active pointer сохранены |
| AC3 | Repeat/race | Один draft/projection; отдельные журналы; иной/пропущенный каталог отклоняется |
| AC4 | Fault at each insert boundary | Полный rollback; только rejected journal; retry recoverable |
| AC5 | Invalid catalog, foreign version/set, corrupted projection | Отказ без утечки payload; FK/immutable guards; integrity verified before read/reuse |
| AC6 | Read-only local review | Country lookup и profile review из DB без PDF/catalog файлов, без записи/публикации |
| AC7 | Historic sealed version | Нет автоматического backfill/смены каталога; явный отказ при повторе без проекции |

## Risk pre-audit — builder, NOT independent

- Только новые таблицы и новая отдельная SQLite rehearsal DB. Не мигрировать прежнюю runs БД или production.
- Хеш bundle остаётся идентичностью версии; projection hash связывает формат, индекс и каталог. Изменённый каталог того же bundle нельзя молча принять или потерять; требуется будущий явный workflow ревизии.
- Composite FK (version_id, unit_id) запрещает ссылки на чужую версию. Full-admin Actor проверяется до файлов/DB; клиентские facts не сохраняются.
- Новые строки вставляются до accepted journal в одной транзакции; ORM запрещает update/delete и добавления после sealing. Raw SQL остаётся привилегированной границей, hash не цифровая подпись.
- Проверка сохранённых строк против детерминированной проекции ловит пропуски/лишние строки/искажения. Старая версия без проекции требует отдельного рассмотренного backfill; этот этап его не делает.
- Recovery: rollback незавершённого импорта, повтор того же bundle+catalog. Потеря связи на COMMIT = UNKNOWN, сверка повтором. Downgrade заполненных новых таблиц запрещён; при откате приложения сохранять данные и backup.
- Publication, поездки/сроки, клиентские документы, подтверждение правовых норм и DEC-07 вне scope.

## Completion requirements

Targeted negative tests, migrations/PG DDL compilation, full tests suite, реальный PDF
в отдельной локальной БД, self-review + independent review packet, handoff/STATE, commits.
PG16 runtime/concurrency, independent review и final audit остаются UNKNOWN, если не
получены. SELF_REVIEW их не заменяет. CI/deploy/production acceptance N/A: local scope.
