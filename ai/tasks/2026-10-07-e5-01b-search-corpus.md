# TASK: E5-01B-SEARCH — корпус знаний по инструкции PDF и оценка остатка

- Date: 2026-10-07; CLASS / MODE: STANDARD / solo (локальная подготовка источника).
- Completion target: local change + локальные commits, разрешённые ранее Аланом.
- Base: fix/tours-search-quality @ ad41b2e. Builder: Codex, review SELF_REVIEW.
- User: «продолжай и скажи по пдфу нам сколько еще процентов осталось чтобы все выполнить».

## Goal / evidence restored

В PDF (физическая стр.2, печатная стр.1) прямо задано разбиение RAG по разделам с целыми
таблицами, version/date/block metadata; JSON Б.3 и YAML Б.5 не отправлять в поиск.
Сейчас есть конверсия полного текста и выбранные 208 machine-rule drafts, но отдельного
поискового корпуса нет. Не смешивать «импортировано 208» с реализацией всех требований PDF.

## Scope

- Pure parser/chunker для указанного в PDF RAG scope: блоки 1–2, 5–13, 15–17.
- Сохранять текст/таблицы/метки и provenance; деление по H2, длинных разделов по существующим
  H3 с родительским контекстом. Не дробить таблицу, fence или абзац по числу символов.
- Не включать промпт/слоты/машинные YAML, инструкции CRM и приложения конвертера в RAG.
- Deterministic builder + check для derived Markdown/PDF hash, локальный corpus JSON и audit.
- Каждый фрагмент draft, publication_approved=false: RAG-корпус ещё не подтверждён и не подключён к боту.
- Карта прогресса по IT-инструкции PDF с диапазоном остатка и явным основанием оценки.
- Не писать в prod, векторный сервис или бота; embeddings/LLM не вызывать. Не подтверждать нормы/цены.

## Acceptance

| ID | Scenario | Expected |
|---|---|---|
| S1 | Real derivative | Все выбранные разделы покрыты; вне-scope Б.3/Б.5/инструкции/конвертер не попали |
| S2 | Tables/code/long section | Таблицы и fenced blocks не разрезаны; длинное содержимое не потеряно; H3 получает H1/H2 контекст |
| S3 | Labels/metadata | VERIFY/PRACTICE/DECISION сохранены и учтены с родительским контекстом; version/date/source/hash/section присутствуют; no approval |
| S4 | Bad headings/unclosed table or fence/source mismatch/changed file | Безопасный отказ, нет молчаливой усечки или перезаписи изменённого корпуса |
| S5 | Repeated build/check + Windows checkout | Совпадающие байты при повторе; SHA/LF stable; --check не пишет |
| S6 | Progress estimate | Отдельно локальная реализация и production/approval; число 208 не считается всем PDF, диапазон не назван измеренными процентами |

## Plan / verification

Task → pure parser + deterministic builder → real corpus + coverage audit → meaningful parser/
reproduction/negative tests + relevant existing source checks → SELF_REVIEW/handoff/STATE → commits.
Существующие CRITICAL review/PG16 gates не закрываются этим STANDARD этапом.
Процентная оценка до реализации: примерно 20–30% инженерного объёма сделано, 70–80% остаётся
для полного использования PDF ботом и CRM. Это экспертная оценка без оценённых трудозатрат,
не юридическое подтверждение, не page coverage и не процент production acceptance.
