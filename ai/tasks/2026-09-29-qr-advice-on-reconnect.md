# TASK: сторож тишины не советует QR, когда профиль просто переподключается

- ID / date: 2026-09-29-qr-advice-on-reconnect
- Project/scope: Frunze Travel Bot — `app/core/wappi_health.py`, `app/core/channel_heartbeat.py`
- CLASS: **CRITICAL** — детектор, который сам пишет людям. Ложный совет уводит владельца
  чинить то, что работает; ровно это уже случилось 01.09.2026 и стоило доверия к алертам.
- Mode: solo (`ai/protocol.json`)
- Completion target: **reviewed change** (релиз — отдельный гейт, авторизации на деплой нет)
- Base: `fix/tours-search-quality` @ `8feec27`
- Builder: Claude Code · Reviewer: `codex-reviewer` (Opus) + `codex review` (GPT) — класс C
  требует обоих · Auditor: Claude Code перед handoff

## Goal and current behavior

**Цель:** когда Wappi отвечает `authorized=true`, но `app_status` не `open`, сторож тишины не
должен советовать сканировать QR — авторизация жива, QR тут ни при чём.

**Сейчас:** `profile_health()` (`wappi_health.py:253-263`) считает здоровьем ровно
`authorized and app_status == "open"`. Любое переподключение даёт `False`, и
`channel_heartbeat._advice()` (`channel_heartbeat.py:166-167`) выдаёт
«Wappi показывает профиль нездоровым — проверь авторизацию (QR) в кабинете».

**Почему это ложь, замер 27.09.2026:** серия `app_status=connecting` держалась 11:56–13:00
(64 минуты) синхронно по трём профилям при `authorized=true` во всех записях, а канал
`frunze_tours_sezim` в эти же минуты принимал от клиентов голосовые и документы. Канал был
жив. Вчера из-за этого же в `decide()` ушли три ложные тревоги «сканируйте QR» — там уже
введена грация 90 минут (флаг `wappi_connecting_grace_enabled`, включён на проде).
`profile_health()` тем же лечением не покрыт, поэтому дефект остался во второй двери:
совпадёт тишина канала с переподключением — и владелец снова пойдёт сканировать QR.

**Базовый факт, который нельзя сломать:** гейт `tests/test_silence_advice_respects_profile_health.py`
написан до реализации и исполнителем не редактируется. Он требует: `healthy=True` — без QR,
`healthy=False` — QR сохраняется, `healthy=None` — прежний нейтральный текст.

## Scope and boundaries

- In scope: чистая функция состояния профиля в `wappi_health.py`; передача этого состояния в
  `channel_heartbeat._advice()`; новый текст совета для переподключения; флаг и настройка;
  тесты в отдельном файле.
- Non-goals / protected areas: гейт-тест не редактирую. `decide()` и грацию не трогаю —
  они уже исправлены и работают на проде. Логику диагноза трафика (`webhook`/`no_traffic`)
  не меняю. Тексты для `diagnosis` остаются как есть.
- Authorization already granted: локальные правки и проверки — да (Алан: «работайте по долгам»).
- Remaining human gate: **деплой на прод и включение флага** — только по прямому слову Алана.

## Acceptance and evidence

| ID | Preconditions and action | Expected behavior | Verification |
|---|---|---|---|
| AC1 | `authorized=true`, `app_status=connecting`, флаг ON, диагноз неизвестен | В совете нет слова «QR»; сказано, что профиль авторизован и приложение переподключается | новый тест |
| AC2 | `authorized=false`, флаг ON | Совет про QR сохраняется — это настоящий разлогин | новый тест |
| AC3 | Флаг OFF | Поведение ровно прежнее: `connecting` → совет про QR | новый тест |
| AC4 | `healthy=True` / `False` / `None` напрямую в `_advice` | Гейт 01.09 проходит без правок | `pytest tests/test_silence_advice_respects_profile_health.py` |
| AC5 | Весь проект | Нет регрессий | `pytest tests -q` |
| AC6 | Новая настройка | Проброшена в `docker-compose.yml` | `prod_traps_check --diff-base HEAD` |

## Credible negative cases

- Wappi не ответил (`status=None`) → состояние неизвестно, текст остаётся нейтральным; врать
  про здоровье в другую сторону нельзя (требование гейта).
- Мусор в ответе (`app_status` отсутствует, `authorized` не bool) → не падать, вести себя как
  «неизвестно», а не как «здоров».
- Подписка истекла при живой авторизации → повод `payment` не относится к этому совету и не
  должен быть затронут.
- Флаг выключен → ни одна строка текста не меняется (проверяется отдельным тестом).
- Concurrency/duplicates: N/A — чистые функции без состояния, вызываются из одной джобы.

## Plan and risk

1. `wappi_health.profile_condition(status) -> str | None`: `"ok"` / `"reconnecting"` /
   `"logged_out"` / `None`. Чистая, тестируется без сети.
2. `diagnoses_and_health()` при включённом флаге кладёт в `health` значение `"reconnecting"`
   вместо `False`, когда авторизация жива. При выключенном — прежний `bool`.
3. `channel_heartbeat._advice()`: ветка для `"reconnecting"` **до** проверок `is True/False`,
   поэтому гейт с bool не задет.
4. Флаг `wappi_reconnecting_advice_enabled` (дефолт OFF) + строка в `docker-compose.yml`.

**Риск:** если состояние «переподключается» будет выдаваться при реально лежащем приложении,
владелец получит совет «QR не нужен» и потеряет время. Смягчение: `decide()` независимо от
этого совета всё равно поднимет тревогу разлогина по истечении грации 90 минут, и в ней QR
будет назван прямо. То есть ложно-успокаивающий совет ограничен окном, а не постоянен.

**Recovery:** флаг выключается тумблером/переменной без выкатки.

## Completion requirements

- Relevant tests/checks: `python -m pytest tests -q`; `python scripts/prod_traps_check.py --diff-base HEAD`
- Review: класс C → `codex-reviewer` **и** `codex review`; ни один из них не является автором кода
- CI / deploy / production / user acceptance: CI N/A (нет в проекте); деплой и включение флага —
  требуют слова Алана, в эту задачу не входят
- Handoff: `ai/handoffs/2026-09-29-2015-qr-advice-on-reconnect.md`

## Open decisions

Нет. Формулировка текста — техническая, правится после ревью без продуктового решения.
