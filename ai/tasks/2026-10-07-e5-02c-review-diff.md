# TASK: E5-02C-REVIEW — сравнение версий и коммиты выполненных этапов

- Date: 2026-10-07. CLASS / MODE: STANDARD / solo, read-only review tooling.
- Completion target: local implementation + local commits. Builder: Codex; SELF_REVIEW.
- Start base: fix/tours-search-quality @ 4a22ecb8823585387f90bbdc6321506743989132,
  сохранённые CONTRACT-UI, E5-02A, E5-02B-SOURCE/IMPORT в рабочем дереве.
- Authorization: Алан «продолжи и сделайте комиты». Разрешены локальные коммиты этих работ;
  push/deploy, production DB и утверждение правил не запрошены.

## Goal / scope

Сделать импортированные версии удобными для проверки: список добавленных/удалённых/изменённых
единиц и полей, изменения metadata/алиасов, фактические нерешённые вопросы draft.
Сравнение только в одном наборе, через existing named full-admin; данные нельзя изменить
и нельзя активировать. На текущем draft должно быть видно 208 added, 0 confirmed и конфликты.

Сначала сохранить прежние этапы отдельными коммитами, проверив состав staging. Включить только
связанные code/test/docs; пользовательские аудио/экспорты/временные файлы и .env не включать.
Зафиксировать LF у byte-locked knowledge и synthetic source: core.autocrlf=true иначе ломает
source-lock/byte-check после checkout. Проверить builder на извлечённом committed snapshot.

## Acceptance

| ID | Scenario | Expected |
|---|---|---|
| C1 | Same version / metadata-only / changed values / removal | Exact added/removed/changed fields; отсутствующий optional != explicit null; порядок не влияет |
| C2 | Corrupt stored snapshot / projection / hash | Отказ с безопасным кодом, не ложный отчёт сравнения |
| C3 | Foreign set / missing version / non-admin | Отказ; нет DB writes; нельзя сравнить чужую версию по id |
| C4 | Real draft without active version | 208 added, no baseline, 183 needs_verification / 22 decision_pending / 3 blocked; 0 confirmed |
| C5 | Source lock after Git checkout with autocrlf | Builder --check PASS; PDF/source hashes сохраняются |
| C6 | Local commits / continuity | Логические коммиты только наших работ, SHA и тесты в STATE/handoff, прежние CRITICAL gates не названы закрытыми |

## Plan / risk

1. Проверить manifests/staging, LF policy и сохранить прежние четыре задачи коммитами.
2. Read-only domain review + local SQLite CLI, без новой миграции и публикации.
3. Проверить целостность source_record против нормализованного bundle и типизированных колонок
   перед сравнениями. Сравнение не является проверкой юридической актуальности.
4. Targeted tests + полный pytest при необходимости регрессий; SELF_REVIEW, final commit, handoff.

## Gates / exclusions

Независимые review/audit, PostgreSQL16 для CRITICAL IMPORT и CONTRACT остаются UNKNOWN.
Новая задача их не закрывает. Не добавлять owner/approval policy до DEC-07, не вычислять права
стран из неизвестных значений. Публикация/CAS, country index, календарь/квалификация и калькулятор
остаются последующими E5-этапами. prod_traps baseline: 1 ERROR / 57 WARN.

## Completion

**DONE для STANDARD/local scope**, SELF_REVIEW; весь E5 остаётся PARTIALLY_READY.
C1–C6 PASS: код/данные сравниваются без записи, foreign/invalid/corrupt отказ безопасен,
коммиты ebf4ee5 / c8228e5 / 41064f7 / 653a20a / e99e067 разделены по задачам.
Финальная docs-only передача отдельным commit, без push/deploy.

Полный прогон до финальной узкой обработки повреждённых дат: 2735 passed / 8 skipped,
278.16 s; финальный новый модуль: 28 passed. В fresh Git copy: 185 passed / 1 skipped
(нет исходного PDF), плюс отдельное чтение реальной БД её CLI: 208 added / DB hash unchanged.
Builder --check и 7 LF-normalized SHA-256 manifest в копии PASS.
Handoff: `ai/handoffs/2026-10-07-0137-e5-02c-review-commits.md`.
