# Independent review packet — E5-02B-IMPORT

Это вход для независимого reviewer/auditor, не вердикт.
Сначала прочитать требования и фактический код, **не** handoff/SELF_REVIEW исполнителя.

- Task: `ai/tasks/2026-10-07-e5-02b-import.md`; протокол: AGENTS.md, ai/protocol.json (solo), ai/ROLES.md.
- Base: `fix/tours-search-quality` @ `4a22ecb8823585387f90bbdc6321506743989132`.
- Target: **UNCOMMITTED**, включая новые файлы из `ai/reviews/2026-10-07-e5-02b-import-snapshot.json`.
- Scope: локальный draft import; production/release не входят. Source bundle предыдущего этапа:
  `knowledge/kg_entry/draft-v1.1/`, source hash `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.
- Reviewer / auditor: UNKNOWN. Чужие review формы договора к этому импорту не относятся.
- Разрешённый review: read-only, локальные изолированные тесты. Никакого prod DSN, миграций
  на существующей реальной БД, правки .env, внешней отправки данных, commit/push/deploy.

## Файлы для первого прохода

1. Task AC1–AC8, текущий контракт `docs/e5-02b-import.md` и исходный проект `docs/e5-02-slots-schema.md`.
2. `app/domain/models.py`: только новые Knowledge* классы/hooks, остальной код для паттернов.
3. `alembic/versions/e5_knowledge_0013.py`, predecessor `e2_taskclaim_0012.py`, `alembic/env.py`.
4. `app/domain/knowledge_import.py`; adjacent `permissions.py`, `service_authz.py`,
   `app/knowledge/{bundle,validation,bundle_schema}.py` (preflight).
5. `scripts/import_kg_entry_local.py`; `tests/test_knowledge_import.py`,
   `tests/test_knowledge_migration.py`, изменение DOMAIN_TABLES в общем migration test
   и точного allowlist head-таблиц в `tests/test_service_cases.py`.

`git diff` не содержит untracked файлы: сверить SHA-256 manifest и открыть их отдельно.
Source-этап и CONTRACT-UI сохраняются в рабочем дереве; не включать их в новый verdict молча.

## Вопросы reviewer

- Пройдёт ли non-admin/system/bot или клиентский dict вместо trusted Actor? Не раскрываются ли
  данные при ошибке до авторизации? Не выдаёт ли локальный CLI свою модель доверия за web-auth?
- Может ли файл после preflight, повторный запрос, гонка или partial flush создать неполный
  accepted draft? Где проходит граница COMMIT и что означает потеря его подтверждения?
- Сохраняются ли отказ/журнал/активная версия при syntax, schema, semantic, DB failure,
  cancellation и unavailable journal? Не выдумана ли гарантия при недоступной БД?
- Совпадает ли полный normalized snapshot с восстановимыми полями/исходными записями?
  Становится ли None именно SQL NULL, а не JSON null? Не теряется ли provenance Молдовы/тарифов?
- Обеспечены ли cross-set FK, uniqueness version/hash/active, blocked checks и даты в самой БД?
  Какие ограничения обходятся raw SQL, и соответствует ли это текущему доверенному сервису?
- Не может ли ORM изменять sealed draft, журнал или active pointer, в т.ч. вложенный JSON?
- Нет ли исполнения правил/подключения к боту/самовольного решения DEC-07?
- Миграция additive? Downgrade проверяет пустоту до любого DROP? Сохраняет ли прежнюю схему
  и данные? CLI может ли прочитать .env/ALEMBIC_DATABASE_URL и обратиться к другой БД?
- Явно ли оставлены за рамками индекс стран, календарь, публикация/CAS/rollback и согласование фактов?

## Воспроизведение

```powershell
python -m pytest tests/test_knowledge_import.py tests/test_knowledge_migration.py tests/test_alembic_domain_migration.py tests/test_kg_entry_validation.py tests/test_kg_entry_source_bundle.py -q
python -m pytest tests -q
python scripts/prod_traps_check.py --diff-base HEAD
```

Нужен также отдельный PostgreSQL 16 стенд с одноразовой БД: upgrade/downgrade/upgrade,
сравнение старой схемы/контрольных строк, SQL NULL/FK/UNIQUE, параллельный одинаковый и разный
импорт, отказ после вставки units. Одна компиляция PG DDL не покрывает это требование.
Не использовать случайный TEST_POSTGRES_DSN без проверки назначения и разрешённого окружения.

После первого независимого заключения сопоставить его с SELF_REVIEW/handoff и свежими
результатами, затем отдельно финальный аудит. Записать actual commands, ревизию, findings
(место/триггер/последствие/доказательство), PASS/FAIL/UNKNOWN; не наследовать числа исполнителя.
