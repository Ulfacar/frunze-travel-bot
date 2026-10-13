# REVIEW: E5-02B-SOURCE-20261007

- Task: `ai/tasks/2026-10-07-e5-02b-source-bundle.md`.
- Base / target: `4a22ecb8823585387f90bbdc6321506743989132` / UNCOMMITTED,
  `ai/reviews/2026-10-07-e5-02b-source-snapshot.json` (15 файлов, включая данные вне git diff).
- Reviewer / builder: Codex / Codex. Independence: **SELF_REVIEW**, отдельный проход.
- First assessment without builder conclusions: NO — тот же контекст, независимость не заявляется.

## Findings

| Severity | Location | Trigger / consequence | Evidence / correction |
|---|---|---|---|
| Medium, FIXED | kg_entry_source.clean_page | `.strip()` убирал отступ первой строки PDF 89; продолжение cis_bilateral превращалось в корневой ключ | исходная сборка отказала на YAML; теперь удаляются только крайние переводы строки, regression проверяет 4 пробела и вложенный limit |
| Medium, FIXED | build_kg_entry_bundle ROW_IDS | Первые draft IDs сроков использовали номера строк, что осложняло стабильность при следующей версии | до фиксации снимка заменены смысловыми PT/DL ID; данные пересобраны с проверкой прежнего canonical hash |
| Low, FIXED | strict_source_yaml | ParserError malformed YAML мог уйти в traceback CLI | контролируемый ValueError, тесты malformed/tag/cycle/duplicate |
| Low, FIXED | PDF CLI | Подсказка PyMuPDF смешивалась бы с JSON stdout | перенаправлена в stderr; отдельный subprocess с настоящим PDF успешно разобрал stdout как JSON |
| Test-only, FIXED | test_unrepresentable_conditions | тест ожидал `60/90`, хотя точный ключ Б.5 содержит `60_90` | поправлен тест на реальное представление; источник и поведение не изменялись |

Повторно проверены границы: нет импортов runtime config/БД/каналов, нет записи поверх
различающихся файлов, полный источник сохраняется даже при `value=null`. При повторной
сборке не меняются ни байты, ни mtime. Частичное создание файлов восстанавливается повтором.

## Acceptance coverage

| Criterion | Result | Evidence |
|---|---|---|
| B1 | PASS | 208 записей, deterministic --check, прямое сравнение capture с тем же PDF; неверный PDF отвергается |
| B2 | PASS в согласованном объёме | 64 строки 5 таблиц, Б.5 с разрешёнными SRC-04/05, 13 шаблонов; 208 provenance-ссылок; визуально PDF 24/25/59/61/62 |
| B3 | PASS | MDA blocked и исключён из default bypass; GRC/CHL отдельные значения; SW1/SW2/RC_WORK pending с обеими сторонами конфликта |
| B4 | PASS | полный текст 10 PT + 22 DL, 13 шаблонов; условия/разные сроки не превращены в однозначные вычисления |
| B5 | PASS | changed source lock, deleted row, altered cell/template, lost exception, foreign output/audit file, repeat/partial recovery |

## Checks actually performed

| Check | Environment | Result | Limitation |
|---|---|---|---|
| `python -m pytest tests/test_kg_entry_source_bundle.py tests/test_kg_entry_validation.py -q` | Windows / Python 3.12.10 | PASS — **158 passed**, 3.31 s (38 новых + 120 E5-02A) | источник фиксирован v1.1 |
| `python -m pytest tests -q` | тот же UNCOMMITTED snapshot | PASS — **2664 passed, 8 skipped, 1 warning**, 267.82 s | пропуски не PASS; существующий Starlette/httpx warning |
| `build_kg_entry_bundle.py --pdf <исходный PDF> --check` | реальный PDF 94 страницы, PyMuPDF 1.27.2.3 | PASS, exit 0, 208, imported=false | сверены выбранные входы, не полная юридическая база |
| `validate_kg_entry.py bundle knowledge/kg_entry/draft-v1.1 --source <PDF>` | реальные файлы пакета | PASS, exit 0, hash bf9faa53… | 0 confirmed, публикации нет |
| direct PDF CLI stdout parse | свежий subprocess | PASS, stderr отделён | нет сетевого доступа |
| AST, whitespace, `git diff --check` | новые/изменённые файлы | PASS | Git предупреждает LF/CRLF |
| Старые code/test snapshots | 13 файлов E5-02A, 6 файлов формы | PASS, SHA-256 совпадают | старые docs E5-02A/backlog обновлены явно, не заявляются неизменными |
| `prod_traps_check --diff-base HEAD` | локальная конфигурация | FAIL — 1 ERROR / 57 WARN, прежний baseline | не использовать как разрешение релиза |

## Verdict

**APPROVE для локального E5-02B-SOURCE**, STANDARD/solo. Полный E5-02 остаётся PARTIALLY_READY.
Юридическая актуальность, независимое ревью фактов, DEC-01/07, весь PDF и CRITICAL-импорт/
публикация не подтверждены этим SELF_REVIEW. Снимок capture и checksum — доказательство
неизменности и воспроизводимости, а не подпись владельца базы.
