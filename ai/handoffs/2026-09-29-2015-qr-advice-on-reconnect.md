# HANDOFF: 2026-09-29-2015 — совет QR при переподключении профиля

- STATUS: **PARTIALLY_READY** — реализация и проверки закончены, независимое ревью пройдено,
  но релиз и включение флага требуют слова владельца и не выполнялись
- CLASS / MODE: CRITICAL / solo
- Task and project: `ai/tasks/2026-09-29-qr-advice-on-reconnect.md`
- Scope / branch / revision: `fix/tours-search-quality` @ `f6bbc86` (база `8feec27`)
- Completion target: reviewed change

## Outcome and files

Закрыта вторая дверь дефекта, из-за которого владельцу советовали сканировать QR по живому
каналу. Вчера грация введена в `wappi_health.decide()`, но сторож тишины берёт здоровье через
`profile_health()` — там критерий остался «не `open` = нездоров», и совет говорил «проверь
авторизацию (QR)». Замер 27.09: серия `connecting` шла 64 минуты при `authorized=true`, и
канал `frunze_tours_sezim` в эти минуты принимал от клиентов голосовые и документы.

- `app/core/wappi_health.py` — чистая `profile_condition()`: `ok` / `reconnecting` /
  `logged_out` / `None`; `diagnoses_and_health()` при флаге отдаёт третье состояние.
- `app/core/channel_heartbeat.py` — ветка совета для `reconnecting`, `down_log_line` больше не
  падает на незнакомом значении, аннотации типов расширены.
- `app/config.py`, `docker-compose.yml` — флаг `wappi_reconnecting_advice_enabled`, дефолт OFF.
- `app/admin/router.py` — регистрация флага (вне первоначальных границ, добавлено по находке
  ревью: без неё обещанный откат тумблером возвращал 404).
- `tests/test_silence_advice_on_reconnect.py` — 13 тестов, включая регрессии на все находки.
- Гейт `tests/test_silence_advice_respects_profile_health.py` не редактировался.

## Evidence

| Claim / criterion | Command or scenario | Environment / revision | Result | Limitation |
|---|---|---|---|---|
| AC1 — при переподключении нет приказа сканировать QR | `pytest tests/test_silence_advice_on_reconnect.py` | локально, `f6bbc86` | PASS | — |
| AC2 — настоящий разлогин сохраняет совет про QR | там же | локально | PASS | — |
| AC3 — флаг OFF даёт прежнее поведение | там же + чтение `diagnoses_and_health` | локально | PASS | Проверено на уровне функции, не полного тика |
| AC4 — гейт 01.09 цел | `pytest tests/test_silence_advice_respects_profile_health.py` | локально | PASS | Файл не изменялся |
| AC5 — нет регрессий | `python -m pytest tests -q` | локально, `f6bbc86` | PASS — 1767 passed, 4 skipped | — |
| AC6 — настройка в compose | `python scripts/prod_traps_check.py --diff-base HEAD` | локально | PASS | Единственный ERROR предсуществующий (`ANTHROPIC_API_KEY`) |
| Тумблер существует в админке | тест `test_flag_registered_in_admin_panel` | локально | PASS | — |
| Поведение на проде | — | — | **N/A — деплоя не было** | Прод остаётся на `5b04cc5`, флаг не включался |

## Review and remaining gates

Класс C требует двух независимых ревью; оба выполнены, автор кода (Claude Code) в них не судья.

1. `codex-reviewer` (Opus, read-only) — вердикт **BLOCKER**.
2. `codex review --uncommitted` (GPT, Codex CLI) — **P1 + P2**.

Оба независимо нашли один и тот же блокер: `down_log_line` брал значение из словаря через `[]`
и падал `KeyError('reconnecting')` уже **после** записи защёлки cooldown — канал остался бы без
алерта на сутки, а исключение обрывало цикл и лишало алертов остальные каналы. Ровно в том
сценарии, ради которого делалась правка. Мои тесты его не ловили: они звали только `_text`.

Закрыто также: регистрация флага в админке (иначе откат тумблером → 404); строка `"false"`
истинна в Python, поэтому разлогин с нестандартным форматом читался как «переподключается» —
теперь требуется настоящий `bool`; мусорный ответ без `app_status` больше не выдаётся за
переподключение; текст не обещает, что всё в порядке, и называет срок в полтора часа.

Финальный аудит — повторный прогон `codex review` по исправленному диффу: блокер закрыт,
осталась одна P2, она исправлена в этом же коммите.

**Оставшийся гейт:** деплой на прод и включение флага — только по прямому слову Алана.

## Unknowns, risks, and baseline failures

- **NEEDS_HUMAN_DECISION (поднято ревью):** у совета нет жёсткой временной границы, в отличие
  от `decide()` с грацией 90 минут. Сейчас это смягчено текстом («дольше полутора часов —
  считай канал потерянным»), но формально состояние не ограничено. Нужна ли общая настройка с
  `wappi_connecting_grace_minutes` — решение владельца.
- `authorized=true` держится по семантике сессии Wappi даже при выключенном телефоне; поведение
  в этом случае на реальных данных **не измерялось** (UNKNOWN).
- Полный тик сторожа тишины с включённым флагом на проде не гонялся: флаг OFF, деплоя не было.
- Предсуществующее: `prod_traps_check` даёт ERROR `ANTHROPIC_API_KEY` и 57 WARN — фон.

## Found out of scope

- `app/admin/router.py` — вне первоначальных границ диффа, добавлено по находке ревью и названо
  здесь явно.
- Восемь других флагов не имеют тумблера в админке (`FLAG_WITHOUT_TOGGLE` в отчёте гейта) —
  предсуществующий долг, не трогал.

## Next action / resume

1. Решение владельца: выкатывать ли `eef6fb0` (таймауты Wappi) и `f6bbc86` (этот фикс), и
   включать ли флаг `wappi_reconnecting_advice_enabled`.
2. После деплоя — функциональная проверка в боевом контейнере: вызвать `profile_condition` на
   живых статусах и `down_log_line` с состоянием `reconnecting`, показать вывод.
3. Отдельно от кода: **оплата Wappi по туровым каналам до 01.10.2026**.
