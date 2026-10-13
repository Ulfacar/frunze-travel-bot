# E5-02F — сохранённый индекс стран и условия draft-версии

07.10.2026. CRITICAL / solo, **PARTIALLY_READY**: локальная реализация;
независимый review, final audit и PostgreSQL 16 runtime пока UNKNOWN.

Новый импорт сохраняет country index и явно переданный draft-каталог условий
в одной транзакции с версией, единицами знаний и accepted journal. После этого
проверяющий может прочитать их из БД без доступа к исходному PDF/каталогу.
Импорт по-прежнему проверяет реальный исходный файл, права администратора и весь bundle.

## Хранилище и границы

Миграция `e5_projection_0014` после `e5_knowledge_0013` создаёт три таблицы:

| Таблица | Содержимое / ограничения |
|---|---|
| knowledge_projections | Одна запись на version_id; формат /1, хеш проекции, summary country index, необязательный каталог и его canonical hash |
| knowledge_country_links | Все пары version/country/unit с basis; composite FK на unit той же версии и FK на projection |
| knowledge_condition_links | Ссылки version/unit для правил каталога; composite FK на unit той же версии и FK на projection |

Это реализация **проекции кандидатов для проверки**, уточняющая первоначальный проект
`entry_country_rules` в E5-02. Выбранного режима/рассчитанных сроков пока нет. Несколько
кандидатов, evidence-only links, fallback и unmapped units сохраняются; условия проживания
не становятся ссылками гражданства. Исторические units не получают значений из каталога.

Для PDF v1.1: 208 units, 201 country link, 6 condition links; 82 SQL NULL, 0 confirmed,
active_version_id=NULL. Пять исходных unmapped units остаются в summary, их отдельные
условия доступны через каталог. `may_quote=false`, публикация и разрешение въезда не выдаются.

Проекция детерминированно включает формат, country summary/links и полный каталог;
bundle_hash остаётся прежней идентичностью версии. Catalog hash учитывает порядок
массивов, как E5-02E; форматирование JSON/порядок ключей не влияют. Будущие изменения
алгоритма /1 должны сохранять воспроизводимость старого формата либо вводить новый формат.

## Импорт, повторы и восстановление

- `import_bundle(..., catalog=Path(...))` сам читает/валидирует каталог: source_hash,
  bundle_hash, schema, unique rule IDs и ссылки. `catalog=None` явно означает отсутствие
  условий; JSON null в переданном файле отклоняется.
- Вставки выполняются до accepted journal. Ошибка откатывает версию, units, projection
  и обе таблицы ссылок; rejected journal коммитится отдельно. Отмена не выдаётся за отказ.
- Тот же bundle и каталог возвращают существующий draft и новый журнал. При повторе
  сверяются исходные units, metadata, хеши, summary и полный набор обеих таблиц ссылок.
- Пропущенный, добавленный или изменённый каталог того же bundle отклоняется. Старые
  sealed версии без projection также отклоняются: silent backfill отсутствует. Изменение
  каталога требует отдельного workflow ревизии/миграции; менять version_label ради обхода
  этой границы не является предусмотренным workflow этого этапа.
- COMMIT transport failure означает неизвестный исход; повтор **того же** bundle+catalog
  сверяет состояние. Сбой самого журнала выдаёт ImportUnavailable, не ложный успешный отказ.
- ORM запрещает обновление/удаление снимков и добавление после sealing. Privileged raw SQL
  может обойти hooks: hashes — проверка согласованности, не подпись или защита от DB-admin.
- Upgrade только добавляет пустые таблицы. Downgrade сначала проверяет все три таблицы;
  заполненная или offline БД отклоняется до первого DROP. Откат приложения сохраняет таблицы;
  для реальной миграции нужны backup/recovery и отдельное разрешение.

## Локальная проверка

Команды из корня репозитория, **новая отдельная SQLite БД**. CLI не читает .env/DSN.
Существующую БД другой ревизии он не мигрирует. UTF-8 задаётся явно для JSON stdout в Windows.

```powershell
python -X utf8 scripts/import_kg_entry_local.py --db runs/new-projection-demo.sqlite3 --bundle knowledge/kg_entry/draft-v1.1 --source "../Kyrgyzstan-visa-knowledge-base-v1.1.pdf" --catalog knowledge/kg_entry/conditions_v1_1/catalog.json
python -X utf8 scripts/review_kg_projection_local.py --db runs/new-projection-demo.sqlite3 --set-id 1 --version-id 1 --country CHN --facts tests/fixtures/kg_entry/synthetic_condition_facts.json
```

При первом импорте следует использовать возвращённые set/version IDs; `1` выше подходит
только для новой демонстрационной БД. Для повторного импорта передавать тот же каталог.
Lookup страны и факты профиля — два явно отдельных входа отчёта: lookup не выбирает режим,
profile review использует только переданные facts. Полноценная единая анкета ещё не подключена.
Отсутствующий каталог при запросе profile review приводит к отказу, а не пустой успешной оценке.

Reader открывает SQLite в `mode=ro`, проверяет целостность unit snapshot, затем заново
строит ожидаемую проекцию /1 и сравнивает сохранённые строки перед выдачей отчёта. Это
проверка корректности материализации, не оптимизированный запрос для диалогового runtime.
Клиентские facts не сохраняются; CLI не принимает контакты/номера паспортов.
Локальному оператору с доступом к файлу доверяется; серверный API требует trusted full-admin Actor.

## Проверки и дальнейшая работа

`tests/test_knowledge_projection.py` проверяет атомарность, гонки, каталог при повторе,
повреждения, foreign-version FK, sealing, cancellation/commit failure и read-only CLI.
`tests/test_knowledge_projection_migration.py` проверяет additive cycle, schema parity,
исторические версии, guarded downgrade и PostgreSQL DDL (не runtime).

Результаты/ревизия: `ai/STATE.md`, задача `ai/tasks/2026-10-07-e5-02f-projection.md`.
Далее: независимый review/audit и PG16, история поездок/календарь, выбор режима,
утверждение/публикация. Условия и нормы PDF пока не подтверждены владельцем знаний.
