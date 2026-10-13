# E5-03E — версии анкеты и результата квалификации

09.10.2026. CRITICAL / solo, **PARTIALLY_READY**. Локальный domain API под прежним
named full-admin guard. Независимые reviewer/auditor и PG16 runtime **UNKNOWN**.

## Назначение

E5-03D возвращал отчёт без сохранения. Теперь частичная анкета и вычисленный отчёт
сохраняются вместе; можно восстановить последнюю версию после перезапуска,
посмотреть предыдущую и воспроизвести результат по тем же источникам.
Смена цели/паспорта или удаление ответа создают новую версию и новый отчёт.

Это **не** вся `EntryQualification` из проектной схемы E5-02: пока хранится строгий
поднабор `kg-qualification-review-input/1`, отсутствуют dialog/service_case bindings,
collecting/handoff lifecycle, документы и автоматическое сохранение поездок из слотов.
`entry_qualifications` — неизменяемые полные снимки вместо первоначально предложенной
изменяемой JSON-строки; `revision` и `previous_id` сохраняют историю исправлений.

## API

`app/domain/qualification_storage.py`:

```python
saved = await save_qualification(
    engine, actor=authenticated_admin, contact_id=contact_id,
    knowledge_version_id=version_id, history_id=history_id,  # optional history
    expected_revision=0, request_key="opaque-request-id", request=review_request,
)
latest = await read_qualification(engine, actor=authenticated_admin, contact_id=contact_id)
old = await read_qualification(engine, actor=authenticated_admin, contact_id=contact_id,
                               qualification_id=saved["qualification_id"])
verified = await replay_qualification(engine, actor=authenticated_admin, contact_id=contact_id,
                                      qualification_id=saved["qualification_id"])
```

- `actor` только из доверенной серверной аутентификации. Обычный manager/bot/system
  отклоняется до чтения payload и открытия сессии. Новая модель прав не вводится.
- Запрос — схема E5-03D: partial profile, RU/EN, явная `as_of`, optional condition facts.
  Имена, контакты, номера паспортов, свободный текст и готовые решения запрещены.
  Гражданство/нарушения/даты всё равно являются чувствительными фактами.
- Каждое сохранение полностью заменяет вход следующей версии: отсутствующий ключ
  удаляет старый ответ. Слияния PATCH нет. `unknown`, `false`, отсутствующий ключ различимы.
- CAS: `expected_revision=0` для первой записи, затем номер прочитанной версии.
  Контакт блокируется в транзакции, уникальность `(contact_id, revision)` страхует гонки.
- Идемпотентность `(contact_id, request_key)` включает ожидаемую ревизию, вход,
  knowledge version и history id. Повтор возвращает **исходную** версию, даже когда
  появились новые. Изменённая нагрузка под тем же ключом вызывает конфликт.
- Последняя версия читается только внутри contact scope; отсутствие анкеты возвращает
  `None`, неизвестный контакт/id — bounded error. У разных контактов независимые ревизии.
- Request/result/provenance, автор/UTC, связи с предыдущим снимком, KB и историей
  защищены проверками хешей. История проверяется по тому же contact_id.
- Read проверяет integrity, accepted import, DB projection и историю. Он не пересчитывает
  старый результат. Replay дополнительно сверяет algorithm/code/dependency fingerprint
  и повторно вычисленный результат; drift блокирует replay. Совместимость старой схемы
  входа и проверки источников всё равно необходима для чтения после обновления кода.
- Один транзакционный контекст охватывает чтение источников, расчёт и вставку. Ошибка
  до commit откатывает запись. Потеря подтверждения commit возвращает специальную
  bounded ошибку: повторить **тот же** request key/payload, не создавать новый ключ.

Результат остаётся review-only: `may_quote=false`, `selected_regime`, `visa_required`,
точный остаток и срок — NULL. Сохранённый статус `manager_review` не является фактом
передачи менеджеру. Калькуляторы автоматически не запускаются.

## Хранилище и восстановление

Модель `EntryQualification`, migration `e5_qualification_0016` после
`e5_calculation_0015`: одна новая таблица, scoped FK к предыдущей версии и истории,
FK к контактам/знаниям, уникальные ключи ревизии и повтора. Никакого seed/backfill.
Существующий read-only adapter E5-03D использует те же функции загрузки источников;
его публичный контракт сохранён.

ORM запрещает update/delete/bulk mutations, JSON глубоко заморожен. Привилегированный
SQL может обойти ORM: проверки обнаруживают порчу, но хеши не являются цифровой подписью
против администратора БД, который заменил данные и все хеши согласованно.

Downgrade разрешён только для пустой новой таблицы, проверка выполняется **до** drop.
Offline downgrade запрещён. Для заполненной базы требуется отдельный план восстановления;
удаление снимков/retention не реализовано и не подразумевается этим этапом.
Нет production migration, HTTP, LLM integration или расширения менеджерского доступа.

## Проверка

```text
python -m pytest tests/test_qualification_storage.py tests/test_qualification_migration.py tests/test_kg_qualification.py tests/test_entry_storage.py tests/test_entry_storage_migration.py tests/test_service_cases.py tests/test_alembic_domain_migration.py -q
python -m pytest tests -q
```

Покрыты восстановление, старые версии, смена цели/паспорта, unknown/false, чужая история,
scoped FK на уровне БД, запрещённые входы, CAS/concurrency, retry, partial failure,
lost commit acknowledgement, immutable ORM, SQL-порча источников/снимков и replay drift.
Migration проверена на SQLite включая действующий domain API, PG DDL — offline.
Точные результаты и ревизия: task/handoff `2026-10-09-e5-03e-qualification-storage`.

Следующий этап: интеграция сохранённой анкеты в RU/EN flow и handoff с определённым
server-side scope. Публикация правил и реальные данные требуют отдельных business/release gates.
