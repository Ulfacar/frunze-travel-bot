# REVIEW: E5-02E conditions

- Task: `ai/tasks/2026-10-07-e5-02e-conditions.md`; STANDARD / solo.
- Base: `e410078`; target: UNCOMMITTED, manifest `2026-10-07-e5-02e-conditions-snapshot.json`.
- Builder / reviewer: Codex / Codex. Independence: **SELF_REVIEW**.
- First assessment without builder conclusions: NO, один контекст. Отдельный проход:
  PDF physical 22/23, Б.5 capture, схема/код, вывод CLI, реальные и негативные сценарии.

## Findings and boundaries

| Finding | Consequence / correction | Evidence |
|---|---|---|
| PDF range 5–25 разорван переводом строки | Первый builder отказал source_conditions_missing; regex разрешает пробел после тире, пределы не изменены | Повтор с original PDF PASS; 4/5/25/26/unknown tests |
| Поля разных документов могут дать ложное совпадение | Каждый item проверяется целиком; ANY работает поверх результатов отдельных документов | Cross-visa issuer/duration и cross-residence country/kind tests PASS |
| Месяц не равен фиксированным 30 дням; база >3 лет неоднозначна | Отдельные проверенные assertions или unknown; вычислений дней/лет нет | numeric shortcut/неполный факт отклонён или unknown |
| Старые NULL units нельзя незаметно переписать | Versioned draft-каталог привязан к source + bundle hash; исходные snapshots неизменны | Все 6 исходных value всё ещё NULL; прежние source/import tests PASS |
| Profile match не проверяет все условия въезда | Flags всегда no quote / no eligibility / no date calculation; unresolved preserved | Позитивные и пустые профили, source_outcome с форс-мажором и unknown GCC work field |

## Acceptance coverage

| Criterion | Result | Evidence |
|---|---|---|
| E1 strict schema | PASS | Bad type/unknown field/private input/unknown code/catalog/hash/ref/range cases; no partial result |
| E2 source catalog | PASS | 6 rules, exact artifact bytes, source YAML comparison, --check --pdf direct capture comparison |
| E3 categories | PASS | HK residence vs citizenship, UN LP without nationality, GCC citizens vs resident profile |
| E4 same document | PASS | No cross-document mixing; incomplete and unknown items preserve uncertainty |
| E5 group | PASS | Inclusive boundaries, organized/membership/petition independent requirements |
| E6 duration semantics | PASS | Source month/year assertions retained, no invented days or remaining-duration interpretation |
| E7 local CLI | PASS | All 3 outcomes, input/output isolation, unchanged file hashes+mtime, invalid source/private field, no runtime imports |
| E8 continuity | PASS | ca387a0; Git copy 218 passed / 2 skipped; real PDF через оба CLI PASS, JSON stdout корректен; 13/13 normalized hashes; final handoff/STATE |

## Checks actually performed

Windows / Python 3.12, snapshot из manifest:

- `python -m pytest tests/test_kg_conditions.py -q`: **58 passed, 16.16s**.
- `python -m pytest tests/test_kg_conditions.py tests/test_kg_country_index.py tests/test_kg_search_corpus.py tests/test_kg_entry_source_bundle.py tests/test_kg_entry_validation.py tests/test_knowledge_review.py tests/test_knowledge_import.py tests/test_knowledge_migration.py -q`:
  **357 passed, 55.29s**, финальный код.
- `python -X utf8 scripts/build_kg_entry_conditions.py --check --pdf original.pdf`: PASS,
  direct capture comparison; file SHA `3e499dd29aa7c0dba1d338d48b7d0ca64c4ca98277509c2506f706d32a9b890c`.
- JSON backlog parse + `git diff --check`: PASS.
- `python scripts/prod_traps_check.py --diff-base e410078 --limit 1`: FAIL baseline
  **1 ERROR / 57 WARN**, ANTHROPIC_API_KEY compose forwarding; секреты не выводились.

Full repository suite не повторялся: новые isolated modules/artifact, существующие runtime,
DB/import, schemas слотов/units и source bundle не менялись. Проверены 8 связанных модулей.

## Verdict

**APPROVE — SELF_REVIEW для STANDARD local condition profiles.** Источник не утверждён,
проверяющий вводит duration assertions, а не LLM. Документальная/юридическая проверка,
полный selection/calculation и publication впереди. CRITICAL IMPORT/CONTRACT независимые
review/audit и PG16 всё ещё UNKNOWN; этот этап их не закрывает.
