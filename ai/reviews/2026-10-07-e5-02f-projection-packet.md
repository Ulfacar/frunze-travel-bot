# Independent review packet — E5-02F

Это задание для независимого reviewer/auditor, **не заключение**. Сначала читать
требования и фактический код, затем сверять с builder handoff/SELF_REVIEW.

- Task: `ai/tasks/2026-10-07-e5-02f-projection.md`, AC1–AC7.
- Protocol: AGENTS.md / ai/protocol.json (solo) / ai/ROLES.md.
- Base: `fix/tours-search-quality` @ bd1a84e; target UNCOMMITTED snapshot manifest
  `ai/reviews/2026-10-07-e5-02f-projection-snapshot.json` (после commit — точная ревизия в STATE).
- Reviewer / final auditor: UNKNOWN. Builder review не независим.
- Scope: локальный draft import + materialization + review; release не входит.
- Разрешено: read-only анализ, изолированные локальные тесты. Не обращаться к production
  DSN/данным, не посылать код/данные внешним сервисам, не запускать backfill/deploy.

## Файлы и вопросы для первого прохода

1. Контракт `docs/e5-02f-projection.md`; сопоставить с проектом `docs/e5-02-slots-schema.md`.
2. Новые KnowledgeProjection/CountryLink/ConditionLink и hooks в `app/domain/models.py`;
   миграция `alembic/versions/e5_projection_0014.py` и predecessor 0013.
3. `app/knowledge/projection.py`, `country_index.py`, соседние conditions/schema/bundle:
   что именно хешируется, не превращает ли materialization evidence в eligibility?
4. `app/domain/knowledge_import.py`, `knowledge_projection.py`, `_snapshot` в knowledge_review:
   atomic flush/commit; разные каталоги с одним bundle; гонки; отмена; lost COMMIT acknowledgement;
   отказ и журнал; read/reuse целостность; scope версии/набора; trusted Actor до I/O.
5. Новые projection tests и изменения migration allowlists; local import/review CLI:
   ambient DSN, старая revision, read-only mode, private input/error leakage, отсутствие facts persistence.

Проверить, что пропущенная/лишняя/изменённая ссылка вызывает отказ; composite FK не даёт
сослаться на unit другой версии; ORM не позволяет вставлять строки в sealed версию;
старые sealed snapshots не дополняются повторным импортом. Raw SQL — отдельная
привилегированная граница, не обещать защиту от DB-admin или криптографическую подпись.

```powershell
python -m pytest tests/test_knowledge_projection.py tests/test_knowledge_projection_migration.py tests/test_knowledge_import.py tests/test_knowledge_review.py tests/test_knowledge_migration.py -q
python -m pytest tests -q
```

PG16: отдельная согласованная тестовая БД, fresh upgrade / schema parity / composite FK,
same/different catalog races, rollback после country/condition flush, retry reconciliation,
populated downgrade без потери таблиц. SQL compilation не доказывает runtime.
Если среда недоступна, записать UNKNOWN, не использовать production как эксперимент.

После первого независимого заключения выполнить отдельный финальный аудит требований,
evidence/revision/recovery. Вердикт с конкретными findings и собственными командами;
не наследовать PASS исполнителя. Выпуск требует отдельного разрешения Алана.
