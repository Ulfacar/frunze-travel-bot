# E5-02B-IMPORT — локальное хранение и импорт draft

07.10.2026. CRITICAL / solo, **PARTIALLY_READY** до независимых review/audit и PostgreSQL-проверки.
Это отдельный этап после [source bundle](e5-02b-source-bundle.md), а не готовый E5-02.
Бот, HTTP и прод не подключены; правовые нормы и цены этим импортом не утверждаются.

## Реализация

`alembic/versions/e5_knowledge_0013.py` после **e2_taskclaim_0012** создаёт четыре таблицы:

- `knowledge_sets`: реестр, nullable active_version_id и review_period_days. DEC-07 не решён,
  поэтому предложенные 30 дней не становятся дефолтом.
- `knowledge_versions`: draft, порядковый номер, уникальный normalized bundle_hash,
  отдельный source_hash исходного PDF, полные meta/aliases и отчёт.
- `knowledge_units`: поля оболочки, типизированное value, исходное blocked_value,
  полный source_record с сохранением отсутствующих optional-полей. JSON — обычный json.
- `knowledge_imports`: журнал завершённых попыток, accepted/rejected, автор, время,
  версия только для accepted, обезличенные адрес/причина отказа.

Миграция не сидирует набор/правила, не импортирует код приложения и не изменяет старые таблицы.
Встречный FK `KnowledgeVersion.set_id` проверяется ORM, как WorkflowVersion.product_id.
Составные физические FK запрещают активную версию и accepted import чужого набора.
CHECK/UNIQUE защищают результат журнала, SQL NULL спорных значений, даты, номер/hash и
единственность active. JSON Schema и семантика проверяются сервисом до записи.

## Сервис и граница доверия

`app/domain/knowledge_import.py`:

```python
set_id = await create_kg_entry_set(engine, actor=trusted_actor)
result = await import_bundle(
    engine, actor=trusted_actor, set_id=set_id,
    directory=bundle_directory, source=original_pdf,
)
```

`trusted_actor` обязан быть получен сервером из аутентифицированной сессии, как в существующих
доменных операциях. Это не логин-пароль и не доверенный параметр HTTP-запроса. Пока допускается
только существующий full-admin с непустым логином, не system/bot. Роль kb_owner и её полномочия
не вводятся до DEC-07. Ни endpoint, ни путь LLM к этому сервису не добавлены.

Сервис получает **AsyncEngine**, создаёт собственные сессии и владеет COMMIT/ROLLBACK;
общую внешнюю транзакцию/Connection передавать нельзя. preflight файлов выполняется внутри
операции: вызывающий код не может передать поддельный BundleReport с `ok=true`.

1. Авторизация до чтения файлов/БД; неизвестный/чужой набор отвергается без записи.
2. Синтаксис → схема → семантика → hash исходного файла. Отказ пишет только rejected journal
   в ранее явно зарегистрированном наборе, без версии/единиц.
3. PG блокирует строку набора; версия/единицы/accepted journal — одна транзакция.
4. UNIQUE(set_id, bundle_hash) и UNIQUE(set_id, version) защищают гонки. До трёх попыток
   после rollback для IntegrityError/OperationalError во время записи; SQLite SELECT FOR UPDATE
   не поддерживает, поэтому использует UNIQUE/retry. Не любой долгий lock обязан завершиться accepted.
5. Повтор того же normalized hash возвращает **тот же draft**, добавляя отдельный accepted журнал.
   Если существующая версия уже другого статуса, результат rejected; новая копия не создаётся.
6. Ошибка до COMMIT откатывает снимок; rejected журнал пишется отдельной транзакцией.
   При недоступном журнале — `ImportUnavailable`, наличие записи не обещается.
7. Сбой на COMMIT — `ImportUnavailable` с **неизвестным исходом**: БД могла записать данные,
   а подтверждение потерялось. Следует повторить тот же пакет и сверить hash/журнал.
   Отмена asyncio не превращается в completed/rejected; прерванную попытку сверяют так же.

`source_hash` проверяет совпадение PDF, но не юридическую достоверность. bundle_hash — SHA-256
нормализованной структуры E5-02A, включает provenance и metadata, а не только числовые value.
При syntax/schema/semantic отказе hash может быть NULL, поскольку валидного normalized bundle нет.
`filename` журнала — логическое `kg-entry-bundle/1`, локальные пути пользователя не сохраняются.

Снимки и журнал неизменяемы через ORM уже с момента импорта, в том числе draft. Вложенный JSON
заморожен; добавлять единицы в завершённый draft тоже нельзя. Исправление — новый пакет/версия.
Смена статусов и active pointer через ORM пока запрещена: контролируемую публикацию предстоит
реализовать отдельно. **Raw SQL / bulk DML обходят ORM hooks** (как в существующем E1): это
привилегированная граница, а не предлагаемый API публикации. DB CHECK/FK/UNIQUE остаются активны.

## Локальная репетиция

CLI принимает только явный локальный файл SQLite, не DSN; не читает .env. Новую БД мигрирует
до e5_knowledge_0013; существующий файл принимает только на этой ревизии. Произвольный файл
или другую ревизию не перезаписывает. `-x dburl` исключает подмену через ALEMBIC_DATABASE_URL.
Локальный оператор с правом записи файла записан как `local-operator`; это не модель web-auth.

```powershell
python -X utf8 scripts/import_kg_entry_local.py --db runs/e5-02b-import-20261007.sqlite3 --bundle knowledge/kg_entry/draft-v1.1 --source '..\Kyrgyzstan-visa-knowledge-base-v1.1.pdf'
```

Выполнено дважды: version_id=1 в обоих случаях, import_id=1/2, второй `reused=true`.
В локальной БД 208 единиц: 183 needs_verification, 22 decision_pending, 3 blocked; **0 confirmed**,
82 SQL NULL value, active_version_id=NULL. Полный source_record сверяется с normalized bundle.
БД в ignored `runs/` — воспроизводимый локальный артефакт, не источник истины и не файл для Git.

Повтор команды безопасен для этой БД. Если создание новой БД прервано до миграционной ревизии,
CLI остановится при повторе; осмотрите файл и используйте новый путь для новой репетиции.
Ничего автоматически не удаляется и не «чинится» поверх неизвестного состояния.

## Проверки и восстановление

```powershell
python -m pytest tests/test_knowledge_import.py tests/test_knowledge_migration.py tests/test_alembic_domain_migration.py tests/test_kg_entry_validation.py tests/test_kg_entry_source_bundle.py -q
python -m pytest tests -q
python scripts/prod_traps_check.py --diff-base HEAD
```

Тесты охватывают real PDF round trip, повтор/гонки, несовпадение источника, невалидный пакет,
полномочия, чужой набор, сохранение активной версии, отказ после записи version/units,
недоступный журнал, неопределённый COMMIT, отмену, ORM immutability, DB constraints,
additive upgrade/downgrade/upgrade с сохранением старой схемы и контрольной строки.
Дрейф моделей четырёх таблиц против миграции проверяется Alembic compare_metadata.

Downgrade **запрещён**, если любая из четырёх таблиц заполнена — даже только набор/журнал.
Проверка идёт до первого DROP; offline downgrade запрещён, поскольку не может проверить
пустоту. Код приложения откатывают с сохранением этих таблиц; удаление реальных данных
потребовало бы отдельного решения и backup/recovery. Устаревший downgrade до e1_services_0007
из архитектурного проекта применять нельзя: между ним и текущим head уже есть миграции E2.

PG DDL компилируется с JSON, composite FK, partial UNIQUE, без ALTER старых таблиц.
Это **не** runtime-доказательство PostgreSQL 16. Локальный Docker daemon недоступен;
PG16 upgrade/downgrade/concurrency до релиза остаются UNKNOWN. prod_traps сохраняет прежний
FAIL 1 ERROR / 57 WARN (ANTHROPIC_API_KEY не передан compose).

## Оставшийся E5-02

Этот этап сознательно хранит draft до любого использования в ответах. `entry_country_rules`
ещё не строится: условные/нетипизированные 82 единицы нельзя превратить в однозначные
права стран. В ответе сервиса явно `country_index_built=false`, `activated=false`.
Для дальнейшего этапа нужны правила индекса/условий и проверка provenance, даты review/approval,
CAS activation/rollback, календарь и квалификация; затем E5-03 калькулятор и E5-04 диалог.
Некоторые будущие поля KnowledgeVersion из проекта (reviewed_by/approved_at и т.п.) добавит
этап публикации. Нельзя считать текущие таблицы реализацией всей архитектурной схемы.

Независимые ревью/финальный аудит не получены. Перед продолжением читать task, review packet,
manifest и handoff E5-02B-IMPORT; старые вердикты соседних задач не являются одобрением этого кода.
