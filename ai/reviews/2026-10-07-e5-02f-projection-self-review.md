# SELF_REVIEW — E5-02F, 07.10.2026

- Reviewer: Codex, тот же builder; **не независимый review/audit**.
- Scope: task AC1–AC7, bd1a84e → **cf7fb0dbdf12144c3483e54c3d1ac3478bf0f582**, manifest рядом.
- Verdict: APPROVE SELF_REVIEW для локальной реализации; общий статус PARTIALLY_READY.
  Полный прогон и committed copy PASS. Это не независимое одобрение.

## Отдельный проход по фактическому коду

Прочитаны final diff (models/import/index/local CLI), новые projection/build/migration,
tests и задача; проверены rollback/reuse/sealing и границы публикации.

- Корректность идентичности: bundle hash не меняется; projection hash включает country
  summary/links и каталог; retry сравнивает полный source snapshot и обе таблицы ссылок.
  Другой/пропущенный/добавленный каталог отклоняется, версия не меняется.
- Foreign unit links запрещены composite FK; ORM update/delete/insert-after-seal защищены.
  SQL checks не заменяют schema; reader перепроверяет содержимое и набор строк.
- Транзакция: save_projection flush до accepted journal; исключения/отмена откатывают всё;
  rejection — отдельно. COMMIT неизвестного исхода не превращается в rejected.
- Исторические версии: upgrade без backfill, retry отсутствующей projection отклоняется;
  CLI не мигрирует existing 0013. Populated/offline downgrade отказывает до DROP.
- Полномочия/данные: trusted Actor до I/O; отдельный local operator, без HTTP/LLM пути;
  facts не сохраняются. Клиентский JSON и SQL/DSN не попадают в ошибки.
- Reader: mode=ro в CLI, snapshot/integrity до выдачи; отсутствующий catalog + facts
  отклоняются. Country lookup и профиль — отдельные review-входы, не единое решение.
- Формат /1 обязан остаться воспроизводимым при будущих изменениях алгоритма/summary.
  Сейчас reader восстанавливает индекс и сверяет строки, без обещаний runtime latency.

Первый новый прогон выявил перехват собственных DomainError общим ValueError-handler:
отказ сохранялся, но сообщение о missing projection/catalog терялось. Добавлен отдельный
`except DomainError: raise`; профильный повтор прошёл. Это исправление диагностики,
не ослабление тестов или обработки повреждённых данных.

## Проверки

- Final full suite: `python -m pytest tests -q` — **2917 passed, 8 skipped, 1 warning,
  414.81s**. Warning: existing Starlette/httpx deprecation. Revision: manifest snapshot.
- Committed copy cf7fb0d: пять knowledge storage/review/migration modules — **126 passed,
  2 skipped, 49.07s** (PDF вне Git). Отдельно real PDF import/retry + read-only CLI PASS,
  208 units/201 country links/6 conditions, SHA БД неизменён; manifest **19/19** matches.
- Import/review/старые migrations: **74 passed / 31.70s** до расширения новых тестов.
- Projection + новые migrations + domain migrations + service cases:
  **111 passed / 2 skipped / 40.87s**; затем добавлены три негативных сценария к полному прогону.
- Реальный PDF в новой `runs/e5-02f-projection-verified-20261007.sqlite3`: PASS
  1 version / 208 units / 2 accepted journals / 1 projection / 201 country links / 6 conditions;
  82 SQL NULL / 0 confirmed / NULL active; чтение не меняет SHA файла БД.
- Первый rehearsal runner завершился ошибкой декодирования Windows subprocess output;
  свежая репетиция с явным UTF-8 прошла. Первую runs DB сохранили, не выдаём её runner за PASS.
- `prod_traps_check --diff-base bd1a84e --limit 1`: прежний FAIL **1 ERROR / 57 WARN**,
  ANTHROPIC_API_KEY compose forwarding, вне scope. Значения секретов не выводились.

## Ограничения

Independent review / final audit / PG16 runtime — UNKNOWN. Нет production GO, публикации,
проверки актуальности норм или решения DEC-07. Все правила draft. Откат приложения
сохраняет новые таблицы; смена каталога/исторический backfill требуют отдельного workflow.
