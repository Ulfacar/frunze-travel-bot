# E5-03D — единый отчёт квалификации

09.10.2026. CRITICAL / solo; **PARTIALLY_READY**, independent review/final audit UNKNOWN.
Реализован локальный маршрут проверки partial profile по PDF §2.1 (physical page 19).
Он объединяет анкету, country index, специальные условия и ссылки регистрации.
Бот и менеджерский HTTP-интерфейс пока не подключены; нормы остаются черновыми.

## Что возвращает отчёт

| Ситуация | Результат |
|---|---|
| Не выбран въездной паспорт, неизвестны документ/цель/даты/ответы о нарушениях | needs_input, ordered missing_facts и до трёх next_questions RU/EN |
| Особый документ, работа, заявленное нарушение/запрет/отказ, истёкший паспорт, проблема свободных страниц | manager_review; вопросы автоматического продолжения приостановлены |
| У находящегося в КР отсутствует основание или прошла явно указанная дата основания/регистрации | manager_review с отдельными причинами; факт просрочки закона не устанавливается |
| Все общие сведения известны | knowledge_review; кандидаты и ограничения для специалиста |
| Несколько гражданств | Требуется явный паспорт, не выбирается наиболее выгодный вариант |
| Совпало специальное условие | profile_match=met; это кандидат, не подтверждение права въезда |
| Условие опровергнуто | rule ID в excluded_condition_rules |
| Условие неизвестно/нет каталога | unknown/not_evaluated, недостающие факты или condition_catalog_missing |
| Обнаружен all_others | withheld_fallbacks; автоматического применения нет |
| Молдова в реальном draft | source_conflict в общем отчёте; ссылка на конфликтующее правило регистрации сохраняется |

`candidate_rules` и `registration_rules` разделены. У каждой ссылки — unit_id, основание
ассоциации, статус проверки профиля, findings, страница/раздел/source_ref. При нескольких
кандидатах нет ранжирования и выбора; `multiple_candidates_require_review` виден явно.
Полнота правил, их актуальность и приоритет ещё не утверждены.

Всегда `selected_regime=null`, `visa_required=null`, `exact_remaining_days=null`,
`exact_deadline=null`, `may_quote=false`, `publication_approved=false`.
Статус knowledge_review не означает, что клиент может въехать или не нуждается в визе.
Расчёты CALC-02/03 не запускаются без отдельно выбранных правил и явной политики.

## Вход и границы доверия

`app/knowledge/qualification_schema.py` переиспользует типы существующих slots,
но задаёт **частичную минимальную анкету**, а не заменяет collecting/handoff валидацию.
Условно обязательные ответы разрешено опускать, чтобы запросить их последовательно.
Семантика проверяет выбор паспорта среди гражданств, справочник стран, порядок дат,
будущий «фактический» въезд и противоречие между нахождением за рубежом и основанием пребывания в КР.

```json
{
  "format": "kg-qualification-review-input/1",
  "as_of": "2026-10-09",
  "language": "ru",
  "profile": {
    "citizenship": ["RUS", "MDA"],
    "document_type": "ordinary"
  }
}
```

Пример вымышленный. Ответ запрашивает паспорт и другие пробелы; числа/право въезда
не выдаются. Full synthetic example: `tests/fixtures/kg_entry/synthetic_qualification_review.json`.

Поддерживаемые profile поля: гражданства и паспорт въезда, тип документа, expiry/pages,
цель, current_location, entry/exit dates, in_kg_since, current_basis/type/until,
registration_until, violations и previous_refusals_kg. Нет contact, passport_number,
свободных notes, previous_visits/history, decision и stop_factors. Они отклоняются.
`unknown`/`not_applicable` в необходимых ответах не превращаются в false.

Опциональный `condition_facts` использует E5-02E facts schema **без** entry_passport_country
и document_type: они поступают только из profile. Нельзя подставить другой паспорт в
проверку особого режима. `over_three_years_verified`/`stay_within_one_month_verified`
означают отдельное заключение проверяющего, не интерпретацию LLM. `specialist_missing_facts`
содержит пробелы этих условий; клиентские вопросы для них пока не реализованы.

Отчёт не повторяет анкету, даты поездки и контакты. Сохраняет явный as_of, hash исходного
запроса, source/bundle/catalog hashes и version_label. Hash не скрывает данные от
перебора и не является подписью. В БД этот этап анкету/результат не сохраняет.

## Python, DB и CLI

`QualificationReview(**bundle, source_hash=..., catalog=...).evaluate(request)` — чистая
проверка с собственным снимком источника. Caller отвечает за проверку фактического source.

`app.domain.entry_qualification.review_qualification(engine, actor=..., contact_id=...,
knowledge_version_id=..., request=..., history_id=None)` — read-only adapter. Named
full-admin guard применяется до DB/входных данных. Actor должен поступать из trusted auth.
Обычные менеджеры/бот/system не получают права через новый слой.

DB adapter требует accepted journal для конкретной knowledge version, сверяет bundle,
проекцию, country/condition links и каталог. При наличии history_id читает только историю
того же contact с проверкой hash/типизированных интервалов. Возвращает revision/hash,
cutoff, полноту, счётчики интервалов/подтверждения. Неполнота, неподтверждённые интервалы
и иной cutoff добавляют blockers. Passport continuity и применимость истории ещё не
оцениваются; наличие проверенного snapshot не делает историю достаточной для расчёта.
SQL только SELECT, нет flush/commit, журнала анкеты и внешних вызовов.

```powershell
python scripts/review_kg_qualification.py tests/fixtures/kg_entry/synthetic_bundle --source tests/fixtures/kg_entry/synthetic_source.txt --request tests/fixtures/kg_entry/synthetic_qualification_review.json
python scripts/review_kg_qualification.py knowledge/kg_entry/draft-v1.1 --source "..\Kyrgyzstan-visa-knowledge-base-v1.1.pdf" --request tests/fixtures/kg_entry/synthetic_qualification_review.json --catalog knowledge/kg_entry/conditions_v1_1/catalog.json
python -m pytest tests/test_kg_qualification.py -q
```

CLI read-only, без .env/DB/network. Exit 0 означает выполненную проверку, включая
needs_input/manager_review; exit 1 — некорректный запрос/источник. Числовое значение
из source_outcome не превращается в клиентское обещание. Документы/правовые нормы
не проверены автоматически; это ещё не весь CALC-01 и не весь список стоп-факторов Б.4.

Следующие этапы: независимая проверка и утверждение норм/приоритетов; публикация с
контролем версий; явное соединение выбранного маршрута с CALC-02/03; сохранение
квалификации, scoped manager interface, RU/EN диалог и handoff workflow.
