# REVIEW: E5-02A — локальная проверка анкеты и пакета

- Task: `ai/tasks/2026-10-06-e5-02a-validation.md`.
- Base: `fix/tours-search-quality` / `4a22ecb8823585387f90bbdc6321506743989132` + UNCOMMITTED.
- Target: `ai/reviews/2026-10-06-e5-02a-snapshot.json`, включая новые файлы вне git diff.
- Reviewer / builder: Codex / Codex.
- Independence: **SELF_REVIEW**, отдельный проход после первой реализации.
- First assessment without builder conclusions: NO — тот же контекст; независимость не заявляется.

## Findings

| Severity | Location | Trigger / problem / consequence | Evidence | Correction |
|---|---|---|---|---|
| Medium, FIXED | validation.py | SafeLoader трактовал `012` как восьмеричное, `1:20` как sexagesimal: значение менялось молча | воспроизведено на парсере | decimal JSON-resolvers; неоднозначные скаляры остаются строками и не проходят числовые схемы |
| Medium, FIXED | validation.py | Комментарий после заголовка `\|`/`>` маскировался вместе с текстом блока и обходил запрет inline comments | ручной сценарий принимал оба заголовка; теперь regression tests | маскируется только тело блока |
| Medium, FIXED | validation.py | `.json` принимал YAML, включая комментарии и trailing comma | негативные проверки грамматики | дополнительно json.loads с duplicate-key/non-finite отказом |
| Low, FIXED | validation.py | Число >4300 цифр или escaped surrogate могли обрушить парсер/канонический хеш | тесты YAML/JSON и Python API | контролируемые ошибки, ограничение целых и проверка Unicode |
| Low, FIXED | bundle.py | Шаблон с `{{days}}` проходил сверку множества placeholders | негативные шаблоны | после удаления допустимых placeholders фигурных скобок оставаться не должно |

Все исправления проверены отдельным прогоном **120 passed**. Открытых дефектов
в пределах этого локального этапа не выявлено. Это не доказательство полного импорта/публикации.

## Acceptance coverage

| Criterion | Result | Evidence |
|---|---|---|
| A1 | PASS | collecting/handoff, четыре состояния, реальные несуществующие даты, условные поля |
| A2 | PASS | readOnly enforced API, mismatch citizenship/passport, интервалы, contact strip, вычисленный expiry flag |
| A3 | PASS | 12 видов, сохранность входа/blocked_value, стабильный hash, обе CLI-команды на сохранённых fixtures |
| A4 | PASS | duplicate keys/IDs, anchors/tags, inline comments в разных стилях, source hash, bounds, JSON grammar; данные анкеты в отчёт не попадают |
| A5 | PASS | тариф decision_pending не может иметь рабочее value, per-country exceptions, term не подменяет exemption, конфликт not_in_list |

## Checks actually performed

| Command/scenario | Environment | Result | Limitation |
|---|---|---|---|
| `python -m pytest tests/test_kg_entry_validation.py -q` | Windows, Python 3.12.10, jsonschema 4.26.0, PyYAML 6.0.3 | PASS — 120 passed, 1.61 s | синтетические данные; не юридическая сверка |
| `python -m pytest tests -q`, окончательный снимок | тот же Windows/Python; 17 хешей сверены после прогона | PASS — 2626 passed, 8 skipped, 1 warning, 242.04 s | существующий warning Starlette/httpx; пропуски не PASS |
| обе команды CLI из docs/e5-02a-validation.md | локально, snapshot | PASS — exit 0; imported=false, decision_calculated=false | действующая база не используется |
| import isolation, subprocess | свежий Python без conftest | PASS, тест в профильном наборе | не импортируются app.config/app.db/app.main/sqlalchemy/httpx |
| `git diff --check` + AST parse новых Python | локально | PASS; Git сообщает только LF/CRLF warnings | новые файлы включены отдельным manifest |
| `python scripts/prod_traps_check.py --diff-base HEAD` | локальный env | FAIL — 1 ERROR / 57 WARN, прежний baseline | не основание для релиза; значений секретов в отчёте нет |

Полный финальный прогон и его фактическое число проверок записываются в handoff задачи.
Первый полный прогон: 2618 passed / 8 skipped / 1 warning, 244.36 s; он был запущен
до последних исправлений парсера, поэтому сам по себе не сертифицирует окончательный снимок.

## Verdict

APPROVE для локального объёма E5-02A. Финальный общий прогон завершён без регрессий.
SELF_REVIEW соответствует STANDARD/solo. Независимые проверки/аудит будущих CRITICAL
миграций и публикации этим ревью не закрыты. Полная E5-02 остаётся частично реализованной.
