# E5-02C — сравнение импортированных версий

07.10.2026, STANDARD / solo. Сравнение помогает подготовить проверку базы: какие единицы
добавлены, удалены или изменены, какие именно поля поменялись, где остались неизвестные
значения, источники с конфликтами и незаполненная информация о проверке.
Это read-only инструмент, не процедура утверждения и не калькулятор права въезда.

## Использование

```powershell
python -X utf8 scripts/review_kg_entry_local.py --db runs/e5-02b-import-20261007.sqlite3 --set-id 1 --candidate 1
# Явное сравнение двух уже импортированных версий:
python -X utf8 scripts/review_kg_entry_local.py --db runs/example.sqlite3 --set-id 1 --candidate 2 --baseline 1
```

Без `--baseline` выбирается active_version_id набора. Если его нет, `baseline=null`,
`baseline_present=false`, все единицы candidate отмечаются added. Это начальный пакет для
проверки, а не утверждение, что в Кыргызстане прежде не было действующих правил.
Явный baseline позволяет сравнить два draft или версию с самой собой.

CLI открывает **существующий** SQLite-файл через URI `mode=ro`. Нет миграций, импорта,
создания файла, чтения .env или использования ALEMBIC_DATABASE_URL. Ошибка → exit 2 и
обезличенный `review_unavailable`; JSON отчёт → exit 0. Exit 0 означает только успешное
чтение/сравнение, даже если все правила не подтверждены. Отчёт идёт в stdout.

Доменный API: `app.domain.knowledge_review.review_versions(engine, actor=trusted_actor,
set_id=..., candidate_id=..., baseline_id=None)`. Actor приходит из серверной аутентификации,
как в импорте: named full-admin, не system/bot. Новых ролей и HTTP endpoint нет.
Все выбранные версии обязаны относиться к одному набору `kg_entry/KG/entry`.

## Что проверяется и выводится

Перед сравнением обе версии проходят проверку согласованности:

1. Сохранённые meta/aliases/source_record снова валидируются preflight-схемой и семантикой.
2. Нормализованный bundle_hash совпадает с сохранённым; поля версии совпадают с meta.
3. Каждое типизированное поле KnowledgeUnit совпадает с source_record. Сравнение JSON
   различает true и 1; даты учитывают представление DateTime в SQLite и PostgreSQL.
4. Если выбран active pointer, версия действительно имеет status=active.

Неисправный снимок выдаёт `SnapshotInvalid`, а не список будто бы обычных изменений.
Это контроль согласованности, не криптографическая подпись: privileged SQL может переписать
сразу и снимок, и его hash. PDF заново не читается: `source_reverified=false`.

Порядок единиц/JSON-ключей не влияет на diff. Отсутствие optional-поля отличается от explicit
null: для изменённых полей есть `before_present`/`after_present` и исходные значения. Metadata
и country aliases сравниваются отдельно: смена version_label не делает все правила изменёнными.
У добавленных/удалённых единиц показаны unit_id, kind, title, status, source_ref и page.

Finding codes фиксируют наблюдаемые факты: not_confirmed, value_missing, unresolved_evidence,
source_conflict, owner_unassigned, verification_missing, effective_from_unknown, review_due_unknown.
Это не окончательный список бизнес-условий публикации. Даже пустой список **не** означает
одобрение; `publication_approved=false`, `activation_supported=false` всегда.

На реальном draft v1: **208 added**, 0 confirmed; 183 needs_verification, 22 decision_pending,
3 blocked; 82 value_missing; 6 единиц с conflict_ref; owner/verified/effective_from/review_due
не определены у всех 208. Счётчик 6 source_conflict не равен числу blocked: conflict_ref есть
также у спорных тарифов. Полный отчёт репетиции — ignored `runs/e5-02c-real-review.json`.
SHA-256 SQLite-файла до/после CLI совпал.

## Коммиты и переносимость

Предыдущие этапы сохранены по задачам:

- `ebf4ee5` — CONTRACT-UI, форма договора и её проверки.
- `c8228e5` — E5-02A, pure preflight и JSON Schema, LF policy.
- `41064f7` — E5-02B-SOURCE, воспроизводимый пакет 208 неутверждённых единиц.
- `653a20a` — E5-02B-IMPORT, модели/миграция/импорт и журнал.

`.gitattributes` фиксирует LF только для `knowledge/kg_entry/**` и synthetic_source.txt,
поскольку их raw bytes защищены source-lock/source_hash. Проверка рабочей копии, извлечённой
через `git -c core.autocrlf=true checkout-index`, дала builder --check PASS и прежний hash
`bf9faa537ae600c433a064ab21b8d5969aa63ba99fc39ead224dc6fa5256dea5`.

Исторические handoff/manifest описывают тогдашний UNCOMMITTED snapshot, не текущий Git status.
Для raw-хешей остальных code/docs возможна разница LF/CRLF после fresh checkout; ориентируйтесь
на коммиты. Новый review manifest дополнительно содержит SHA-256 текста с нормализованным LF.
Аудио, экспорты, временные БД, .env и unrelated пользовательские файлы в коммиты не включались.

## Ограничения и дальнейшая работа

В этом этапе нет миграции, изменения импортера, публикации, присвоения прав менеджерам
или обращения к production. Независимые CRITICAL review/audit и PG16 для IMPORT/CONTRACT
остаются UNKNOWN; коммит не заменяет эти проверки и не разрешает выкатку.

Далее: независимая проверка по packet IMPORT; PG16 стенд; country index с явной обработкой
условных правил, поля/процедура review и approval после DEC-07, CAS activation/rollback,
календарь/квалификация, калькулятор E5-03 и диалог E5-04. Не использовать draft как approved.

Проверки: `python -m pytest tests/test_knowledge_review.py -q` и общий `python -m pytest tests -q`.
Актуальные результаты и ревизии — в handoff/STATE этой задачи.
