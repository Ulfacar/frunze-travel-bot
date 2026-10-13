# HANDOFF: 2026-10-13 — отдельная CRM и контекст для Claude

- STATUS: PARTIALLY_READY — серверная техническая проверка завершена;
  публичный release ждёт точного hostname и проверки реального HTTPS.
- CLASS / MODE: CRITICAL / solo. Независимые reviewer и auditor привлечены
  по обязательному правилу AGENTS.md; это не SELF_REVIEW.
- Task: `ai/tasks/2026-10-13-standalone-crm-release.md`.
- Branch/base: `fix/tours-search-quality`, `5200ac1bdec2faab82840e01e6372b33851b9a1d`.
- Revision: UNCOMMITTED frozen `runs/crm-standalone-r9`, 30 overlays.
- Target: отдельный публичный release; этот target пока не DONE.

## Результат

Создан отдельный вход CRM с ручным обращением, предварительным делом, нативной
анкетой/заявителями/заявками и внутренними задачами. Сохранены запрошенные правки
дизайна, шрифтов и контраста. В новом процессе нет bot lifespan, scheduler,
webhooks и backend/provider sending. В календаре остаются ссылки, открываемые
самим пользователем (`tel:`/`wa.me`); тесты по ним не переходили.

Добавлены текущая проверка аккаунта/прав, закрытая сессия и Origin, ограничения
запросов, точная международная идентичность и идемпотентность ручного ввода.
Исправлены независимые находки: потеря формы после неопределённого commit ACK,
подмена человека через receipt, недоступные задачи, ложный успех сохранения,
внешний CDN, незавершённый bootstrap, рост памяти и неполный manifest пакета.

У сервиса свои PostgreSQL, роль, секреты, volume и закрытая сеть. Полный образ
содержит справочники и исходный PDF; bootstrap создаёт только инертный продукт
обращения и208 draft источников. Никаких реальных клиентов или бизнес-политик
из бота не копировали. Старые контейнеры bot/db/redis сохранили ID/start time
и healthy; основной nginx не менялся.

Для Claude написан `ai/CLAUDE_HANDOFF.md`, подключён через `@` в `CLAUDE.md`.
Runbook: `docs/standalone-crm-operations.md`. Новый пятистраничный PDF:
`docs/reports/frunze-crm-server-check-2026-10-13.pdf`. Предыдущий PDF сохранён.

## Точная серверная версия

- Manifest: `10dc6b02b0909c3042b07b229f87429e983d82b909f3445bb8b387c039ebe89b`.
- Release: `10dc6b02b0909c3042b0`.
- Image: `sha256:4f4afd16d8ef3198fb72ccfaae84b44394ec8d1cd3e6e65f6b85ca97e1df43bb`.
- Server: `/root/frunze-crm-review/r9`, project `frunze-crm-check`.
- App:172.30.78.10:8000; внутренняя сеть172.30.78.0/24, без published ports.
- Отдельный тестовый nginx:127.0.0.1:8443, hostname `crm.invalid`, self-signed
  test certificate. Это не публичный URL; доступ использовал временный SSH tunnel.
- UID/GID10001, все5 capability sets0, NoNewPrivs1, Seccomp2,
  `docker-default` enforcing. NNP включается абсолютным setpriv ENTRYPOINT
  после Snap/AppArmor transition, не отключением защиты хоста.

## Evidence

| Claim | Проверка / среда | Результат и ограничение |
|---|---|---|
| Совместимость | R4 env-free pytest / `runs/crm-standalone-r4` | PASS144 за110.41s; не полный suite проекта |
| Приём/идемпотентность/задачи | R8 env-free standalone + перенесённые оригинальные reviewer probes | PASS20 за59.69s; XML `runs/crm-standalone-r8/runs/standalone-r8.xml` |
| UI/calendar/card | R9 env-free pytest | PASS27 за29.96s; `runs/crm-standalone-r9/runs/standalone-ui-r9.xml` |
| Новый нативный путь | R7 реальный контейнер/PostgreSQL, браузер390 dark JS/1365 light noJS | PASS ручной ввод → дело → анкета → заявитель → заявка → задача; `runs/crm-browser-r7/evidence.json` |
| Сохранность/читаемость R9 | 12 authenticated GET после замены app; оба размера/темы; 6 calendar elements normal/hover | PASS, contrast4.95–12.77, login4.95–14.16, нет overflow/external requests/JS errors; `runs/crm-browser-r9/evidence.json` |
| Пакет/фактический образ | Независимое восстановление30 overlays,420 bundle/417 installed assets, kernel/role/schema/network/loaders | PASS; `runs/crm-standalone-audit-r9/runs/audit-image-verified.json` |
| Backup/restore/replay/concurrency | Собственный Linux pg_dump/pg_restore аудитора, отдельная сеть/volume | PASS78 таблиц,61 sequences,160FK; прежние подписанные повторы неизменны, конкурентный ввод один, новая задача сохранена |
| Старый bot сохранён | Read-only Docker inspect до/после | PASS IDs/start times/healthy; `runs/crm-final-server-observation.json` |
| Фиксированный объём PDF | `python scripts/check_pdf_engineering_progress.py` | PASS99/100, J05 UNKNOWN, определения50 критериев не менялись |
| Публичный release | Настоящий hostname/DNS/TLS/proxy/новая рабочая база | UNKNOWN, hostname не получен |
| Реальная приёмка | Источники/цены/доступ/хранение/пилот сотрудником | UNKNOWN; `docs/pdf-owner-acceptance.md` |
| Telegram completion | Только после фактического завершения запуска | UNKNOWN, сообщение пока не отправлялось |

Разные прогоны и mapped evidence не складывать в один suite. Полный перечень
артефактов и хэшей: `ai/reviews/2026-10-13-standalone-crm-evidence.json`.
Доказательства синтетические; реальные юридические/ценовые правила не утверждены.
Все208 единиц источника draft;22 исходных правила сроков с NULL сохранены.
99/100 — инженерный счёт, не99% готовности к production или сроков работ.

## Review и ошибки

Reviewer publication_review: R5/R6 APPROVE + R9 source mapping APPROVE,
`ai/reviews/2026-10-13-standalone-crm-independent-review.md`.
Separate auditor e622_audit: bootstrap/body/bundle/kernel/actual image/restore,
финальный **GO для точного R9 и закрытой технической проверки** в
`ai/reviews/2026-10-13-standalone-crm-final-audit.md`; **public-release GO отсутствует**.
Ни один scoped verdict не подтверждает ещё не выполненную публичную выкладку.

Исходные FAIL сохранены в reviewer/auditor reports. Отдельно исправлены
тестовые fixture bindings, восстановление после IPAM.Config=null и SSH tunnel
connection reset; они не представлены как новые бизнес-дефекты. При первой
проверке R9 браузер получил connection refused из-за закрытого tunnel. После
повторного tunnel с keepalive тот же образ прошёл проверку.

## Продолжение

1. Получить ответ на уже заданный вопрос о домене: предложен `crm.frunzetravel.kg`.
   `app.frunzetravel.kg` занят. Молчание не считать выбором адреса.
2. По runbook создать новый project `frunze-crm`, свежие секреты и volume.
   Не превращать синтетический review volume в рабочую базу. Для освобождения
   подсети выполнить только review `compose down` без `-v`, проверить удаление
   его сети; сохранить volumes/dumps. Не затрагивать `frunze-travel-*`.
3. Проверить отдельный nginx route, действительный TLS, HTTPS/login/Origin,
   доверие forwarded headers/лимиты/таймауты, сохранность и здоровье старого бота.
   Пакет уже reviewable; текущее разрешение пользователя покрывает этот release.
4. Обновить отчёт/STATE/Claude document и отправить Алану одно личное уведомление
   через его существующего Telegram-бота. Сначала проверить bot/private recipient;
   секреты и destination IDs в Git/вывод не помещать.

Серверный recovery dump/volume сохранён в `/root/frunze-crm-review/audit-recovery-r8`;
оба clone-контейнера остановлены. Тестовый app/db оставлены закрытыми для
продолжения. Root `.env` не читали; локальный PG55971 остановлен; старый preview8765
сохранён. Нового commit/push нет. Unrelated untracked файлы не включены в пакет.
