# TASK: E5-02D — индекс стран для локальной проверки правил

- Date: 2026-10-07; CLASS / MODE: STANDARD / solo.
- Base: `fix/tours-search-quality` @ `a6b2f3c`.
- Completion target: local implementation + tests + SELF_REVIEW + handoff + local commits.
- Authorization: «Делай бро», продолжение PDF; разрешение на коммиты сохраняется.

## Goal and scope

Дать проверяющему поиск по ISO3/явному алиасу из конкретного bundle без сканирования JSON
при каждом запросе. Сохранить связь с исходными единицами и раздельные категории въезда,
освобождения от регистрации и срока регистрации. Основание: E5-02 и
`docs/e5-02-slots-schema.md` §§1.2/3.1–3.3; существующий preflight/bundle — фактический контракт.

Это чистый индекс ссылок и локальный read-only CLI, **не** таблица `entry_country_rules`
и не алгоритм выбора применимого режима. Материализация при DB-импорте, publication,
права/HTTP и калькулятор остаются отдельными этапами. Никаких новых бизнес-приоритетов,
подтверждённых правил, значений из blocked_value или чтения/записи production.

## Acceptance

| ID | Observable behavior |
|---|---|
| D1 | Сборка только после schema/semantic/source-hash preflight; invalid bundle не даёт частичный индекс |
| D2 | Поиск ISO3/явного алиаса использует ту же NFKC/casefold/whitespace нормализацию; неизвестный ввод не становится general procedure |
| D3 | Все шесть country-related kinds учтены; освобождение, default и term раздельны; MDA conflict и GRC/CHL исключения сохранены |
| D4 | NULL value/условные/несопоставленные правила видны; evidence-only ссылки никогда не превращаются в значения или выбранный режим |
| D5 | Дипломатические/service/иные документы не получают ordinary regime автоматически; document applicability не решается поиском по гражданству |
| D6 | Перестановка units/aliases не меняет ответ; изменение входа/выхода не портит индекс; каждый ответ содержит source/bundle/version provenance |
| D7 | Read-only CLI для реального/синтетического bundle: query/summary, bounded errors, no DB/config/network, negative inputs and wrong source |
| D8 | Tests + review + usable handoff/STATE + local commits; full E5-02 не объявлен завершённым |

## Technical choices

Индекс хранит отдельные списки unit IDs, включая several candidates, без last-write-wins.
`all_others` остаётся отдельной ссылкой на fallback в источнике, не выбранным режимом.
Для NULL value читаются только структурированные country hints существующего генератора
(`blocked_value.country_iso3` и `blocked_value.candidate.countries`), исключительно как
evidence-only links; текст источника/ID-похожие суффиксы не угадываются. Нераспределённые
country rules выдаются явно. Special rules без countries — отдельно country-independent.
Любой ответ review_only / may_quote=false, даже для synthetic confirmed единиц.
При использовании в будущем боте нужна отдельная проверка применимости/публикации.
