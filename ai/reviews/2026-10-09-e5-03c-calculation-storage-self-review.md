# SELF_REVIEW — E5-03C

- Builder/reviewer: Codex, тот же контекст, **не независимая проверка**.
- Mode/risk: solo / CRITICAL. Base ef77321; target UNCOMMITTED snapshot.
- Локальный результат PARTIALLY_READY; independent review/final audit UNKNOWN.
- Проверены task AC1–8, все новые файлы и diff общих models/calendar, adjacent
  knowledge import/review/projection, pure CALC-02/03 и существующие migration checks.

## Findings и исправления

1. Потеря подтверждения уже выполненного commit: combined sessionmaker.begin context
   мог оставить соединение незакрытым при исключении after_commit. Исправлено отдельными
   session и transaction context managers. Три injected-ACK теста проверяют сохранённую
   запись, отсутствие checkout без checkin и повтор с прежним ключом без дубля.
   Первый тестовый probe использовал QueuePool.checkedout(), но SQLite здесь NullPool;
   заменён наблюдением реальных checkout/checkin events, без ослабления требования.
2. Audit timestamps: created_at истории/расчёта включены в snapshot hash;
   confirmed_at сверяется с временем записи истории. Прямая SQL-подмена обнаруживается.
3. Запрос расчёта не принимает историю/подтверждение/полноту. Их извлекает DB adapter;
   cross-contact и cross-history FK проверены дополнительно прямым SQL с FK=ON.
4. Прежняя версия истории/календаря сохраняется целиком, replay сверяет источники,
   runtime identity, вычисленный input/output. Старый report читается и после изменения
   runtime, но не выдаётся за успешно повторённый расчёт.
5. Локальная CLI создаёт файл эксклюзивно и получает SQLite URL через -x dburl;
   ambient DSN не может перенаправить миграцию. Повтор существующего файла проверен
   на байтовую неизменность. Вывод только synthetic summary.

## Evidence

- Targeted storage/migration: **67 passed / 48.44s**, с SAWarning=error после исправлений.
  Первоначально 67 passed с 3 предупреждениями об утечках; затем 3 test-probe failures,
  64 passed; итоговый прогон без предупреждений. Исходная sandbox попытка соседних
  тестов получила PermissionError в pytest temp/cache; запуск вне sandbox восстановил проверки.
- SQLite CLI: PASS, revision e5_calculation_0015, счётчики 1/1/2/6/2/1/2,
  replay_verified=true, synthetic presence 6, synthetic due 2026-10-08;
  exact values NULL, may_quote=false.
- Full suite: **3161 passed / 2 failed / 8 skipped / 1 warning, 408.80s**. Из двух
  failures список таблиц в старом migration test обновлён (+7 таблиц, проверка не ослаблена).
  Повтор service_cases + alembic_domain_migration + entry_storage_migration:
  **64 passed / 2 skipped, 21.23s**. Приложение после полного прогона не менялось.
- Второй failure `test_facts_live_errors.py::test_still_reads_a_plain_request` подтверждён
  на isolated ef77321: **1 failed / 0.38s**. В базовой копии clock=06.10 даёт dates,
  clock=09.10 — нет: вход «7–14 октября» сдвигается на следующий год и отсекается >310 днями.
  Это прежний time-dependent gate, не регрессия E5-03C; файл/парсер не менялись.
  Полностью зелёного full-suite не заявляем. Warning — прежний Starlette/httpx deprecation.
- prod_traps: FAIL baseline **1 ERROR / 57 WARN**, существующий ANTHROPIC_API_KEY
  compose forwarding. Конфигурация запуска этим этапом не менялась.
- git diff --check: PASS. Snapshot includes untracked implementation files.

## Остаточные границы

Нет независимого reviewer/auditor и runtime проверки PostgreSQL 16. Нет утверждённых
норм, официального календаря, manager scope/HTTP/LLM интеграции и retention/DEC-06.
Привилегированный SQL способен переписать и данные, и hash; это не цифровая подпись.
Opaque ref/request_key нельзя заполнять персональными данными, проверка формата не DLP.
Replay требует прежнего runtime; этот этап не поставляет архив Docker/зависимостей.
Production/клиентские отправки N/A: bounded local target, таких операций не выполнялось.
Это SELF_REVIEW, не разрешение на critical release.
