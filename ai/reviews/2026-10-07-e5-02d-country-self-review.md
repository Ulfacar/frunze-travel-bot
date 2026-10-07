# REVIEW: E5-02D country index

- Task: `ai/tasks/2026-10-07-e5-02d-country-index.md`; STANDARD / solo.
- Base: `a6b2f3c`; target: UNCOMMITTED, `2026-10-07-e5-02d-country-snapshot.json`.
- Reviewer / builder: Codex / Codex. Independence: **SELF_REVIEW**.
- First assessment without builder conclusions: NO, один контекст; отдельный проход по
  задаче, архитектурному проекту, коду и реальному source bundle.

## Findings

| Severity | Location / trigger | Consequence | Resolution |
|---|---|---|---|
| Resolved | NULL value, одновременно country_iso3 и candidate.countries с разными странами | Первое поле могло скрыть противоречие в evidence | Обе привязки валидируются и сравниваются; conflict отклоняется. Тест также проверяет совпадающие алиасы |
| Design boundary | Групповой безвиз, отдельная регистрация и term | Одно объединённое поле скрыло бы SRC-04/05 | Раздельные категории и реальные тесты MDA/GRC/CHL |
| Design boundary | Неполные special/GCC units | Вывод общего режима мог бы скрыть неизвестные условия | Unmapped ссылки всегда видны; fallback не применяется, eligibility не вычисляется |
| Limitation | Архитектура ожидает entry_country_rules | Чистый review index не закрывает DB/import integration | Явно сохранено в контракте, backlog и STATE; E5-02 не объявлен DONE |

## Acceptance coverage

| Criterion | Result | Evidence |
|---|---|---|
| D1 preflight | PASS | Неверный source hash, conflicting aliases, overlapping VF отклоняются без частичного индекса |
| D2 normalization | PASS | ISO3, регистр/NFKC/пробелы, реальные русские aliases; неизвестные/похожие/ISO2 без fallback |
| D3 separate facts | PASS | MDA blocked NULL + term отдельно; GRC/CHL значения из country units; все 114 единиц учтены |
| D4 incomplete facts | PASS | Evidence-only value=NULL, некорректные/дублирующие/противоречащие hints; 5 явных unmapped |
| D5 document | PASS | diplomatic/service/UN/stateless/unknown: review required, selected_regime=NULL, may_quote=false |
| D6 snapshot | PASS | Перестановка входов сохраняет результат/hash; изменения входа/ответа/summary не влияют на следующие запросы |
| D7 local CLI | PASS | synthetic/real source, повтор с теми же bytes+mtime, неверный источник; нет runtime/DB/network imports |
| D8 continuity | PASS local / commit pending | Task/contract/review/STATE/handoff подготовлены; actual commit и Git-copy result дописываются в handoff |

## Checks actually performed

- First module run: 41 passed, 5.03s. First related run: 298 passed, 38.47s.
- После исправления conflicting evidence, **финальный** прогон:
  `python -m pytest tests/test_kg_country_index.py tests/test_kg_search_corpus.py tests/test_kg_entry_source_bundle.py tests/test_kg_entry_validation.py tests/test_knowledge_review.py tests/test_knowledge_import.py tests/test_knowledge_migration.py -q`
  → **299 passed, 37.80s**, Windows/Python 3.12, manifest snapshot.
- Real CLI `--source original.pdf --summary` → PASS: 249 codes / 365 aliases,
  114 units / 201 links / 16 evidence-only, 110 linked countries, 5 unmapped; bundle hash unchanged.
- `python -X utf8 -m json.tool docs/crm-delivery/backlog.json` → PASS.
- `python scripts/prod_traps_check.py --diff-base a6b2f3c --limit 1` → **FAIL baseline**:
  1 ERROR / 57 WARN, missing ANTHROPIC_API_KEY compose forwarding. Значения секретов не выводились.

Full suite не повторялся: изменения — новые изолированные модули без runtime подключения,
существующие import/model/schema/source files не менялись. Связанные семь модулей проверены.

## Verdict

**APPROVE (SELF_REVIEW, STANDARD local index only).** Результат — кандидаты для проверки,
не разрешение въезда/котирования; source/hash доказывает идентичность, не юридическую точность.
Python API доверяет явно переданному source_hash; CLI хеширует файл самостоятельно.
Независимые CRITICAL IMPORT/CONTRACT review/audit и PG16 всё ещё UNKNOWN.
