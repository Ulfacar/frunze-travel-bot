# E5-04A / CRM — анкета въезда из карточки визовой услуги

- Base `46284fbaf05d4596b39d889961b01771ee661cfc`, branch `fix/tours-search-quality`.
- CRITICAL / solo; target local implementation + review packet. Builder Codex;
  independent reviewer/final auditor UNKNOWN.
- User: продолжать требования PDF и CRM параллельно; редизайн позже. Ранее разрешены
  commits/push рабочей ветки. Production/migrations/сообщения клиентам не запрошены.

## Outcome

Из существующей карточки визовой услуги администратор открывает анкету въезда в КР,
заполняет partial profile E5-03D, сохраняет через E5-03E и после обновления страницы
видит сохранённые ответы, следующие вопросы и причины проверки. Старые версии доступны
для чтения. Это общий профиль клиента (не отдельная анкета каждой услуги), что явно
указывается в интерфейсе. Никаких автоматических визовых решений/стоимости/отправок.

## Scope / risk pre-audit

Новый экран + strict form adapter + интеграция карточки; текущие styles и navigation,
без общего редизайна. Только прежний named full-admin. Контакт определяется сервером
по услуге; услуги других направлений отвергаются. Feature flag default OFF; запись
дополнительно под существующим service_cases_enabled. Реальные данные не используются.

CSRF/session-bound HMAC связывает case/contact/base revision/источники/date/request key.
POST ограничен по размеру, полям и повторяющимся параметрам; автор/contact/готовое решение
не принимаются из браузера. GET не создаёт контактов/анкет. Ошибки не раскрывают payload.
Источники берутся из accepted KG import; для существующей анкеты версия закреплена.
История/анкета вне contact scope отвергаются; runtime flag OFF проверяется до БД.
Сохранение использует существующую owned transaction, retry/CAS; UI сохраняет введённое
при validation/conflict/unknown commit и не подменяет ошибку успехом. Изменение прав
менеджеров и retention требуют отдельного решения, не входят в этот этап.

## Acceptance

| ID | Observable scenario |
|---|---|
| A1 | Карточка визовой услуги → форма → сохранение → reload: ответы и отчёт из БД |
| A2 | RU/EN questions, unknown/false/absent, смена паспорта/цели; предыдущая версия read-only |
| A3 | Unauthenticated/non-admin/other direction/foreign ids/CSRF/tampering/oversize rejected; no writes |
| A4 | Duplicate, stale tab, validation, missing knowledge/registry failure/write OFF give recoverable explicit UI |
| A5 | Existing condition facts preserved from signed base, never forged by form; sources integrity enforced |
| A6 | Native browser mobile/desktop/keyboard, no horizontal overflow; no external requests |
| A7 | Related and full regression tests; default OFF / Compose forwarding verified |

## Delivery

Task → implementation → HTTP+domain/browser negative checks → SELF_REVIEW and review
packet/handoff/STATE → authorized commits/push. CRITICAL independent review and final audit
remain UNKNOWN if unavailable; status PARTIALLY_READY, no release certification.
New source requirements are grounded in original PDF §2.1, §3.4 and Б.4; no new law verified
or business access policy invented. Public repo: synthetic fixtures only, no credentials.

## Local evidence

- Code revision `56f84e0db3ba5817f6fa4dad6030e891eaf2b0e4`; final evidence recorded in a follow-up docs-only commit.
- Isolated committed Git copy, no `.env`/`prod.env`: HTTP **42 passed / 1 warning / 53.86s**; 13/13 manifest hashes match Git blobs and copy.
- Related CRM/HTTP/storage: 187 passed / 156.80s; final new HTTP42 passed / 57.58s.
- Browser: 1 passed / 31.82s, mobile390 JS + desktop1365 no JS, native save/reload/history, no overflow.
- Full regression: 3318 passed / 1 known tour-date failure / 8 skipped / 605.66s.
  It started before the final body-buffer bound ordering change; final HTTP42 verifies that change.
- Traps: FAIL, 1 ERROR / 57 WARN (historical ANTHROPIC_API_KEY gap); new flag forwarded.
- Independent reviewer/final auditor/PG runtime UNKNOWN; status PARTIALLY_READY.
