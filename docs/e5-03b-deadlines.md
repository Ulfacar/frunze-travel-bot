# E5-03B — календарь и проверочные сроки

07.10.2026. CRITICAL / solo; **PARTIALLY_READY**. Локальная реализация CALC-03 и части
CALC-05: чистая арифметика с явно переданными версиями календаря. Independent review,
final audit и утверждение владельцем знаний пока UNKNOWN. Выпуска в production не было.

Источники: CALC-03/05 и AC-21 в [ТЗ](spec-crm-frunze-getvisa-2026-10-03.md),
§3.4 [проекта схемы](e5-02-slots-schema.md), блок 13 PDF (физические страницы 61–62).
PDF SHA256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.
Все 22 deadline и 10 processing-time units реального draft имеют `value=NULL`.
Этот этап не извлекает числа из blocked evidence и не заполняет эти значения.

## Исполняемый контракт

- `app/knowledge/work_calendar.py`: owned in-memory snapshot календарей, по одной явно
  выбранной версии на год. `deadline_schema.py`: строгая форма календаря и запроса.
- `app/knowledge/deadlines.py`: `DeadlineReview` принимает validated bundle/source hash,
  набор календарей, выбранный `KG.DL.*`, событие и явную proposed policy.
- `scripts/review_kg_deadline.py`: read-only CLI с preflight исходного PDF. Не читает
  `.env`, DB, сеть или офисный график. Результат — JSON в stdout, файлы не меняются.

`mode=review_only`, `may_quote=false`, `publication_approved=false`, `exact_deadline=NULL`
всегда, даже для synthetic confirmed rule. Успешная арифметика даёт
`arithmetic_status=computed_scenario` и `scenario.status=unapproved_scenario`.
Отсутствие rule value/policy, несовпадение имени события или невозможность вычисления
дают `needs_input`, `blocked_by`, `scenario=NULL`; частичный расчёт не возвращается.
Ошибочная структура/неизвестный rule ID дают статическую ошибку без входных значений.
CLI exit 0 означает корректный отчёт (в том числе needs_input), а не готовую дату;
exit 1 — ошибка валидации/чтения. Проверять поля отчёта обязательно.

## Календарь

Набор `kg-work-calendars/1` содержит до 10 yearly `kg-work-calendar/1`:
KG, Asia/Bishkek, government schedule, год, номер версии, source_ref, явные
`week_rest_days` (ISO 1..7), список overrides. Overrides: public_holiday,
floating_holiday, transfer_rest, transfer_working, weekend_override; каждый имеет
дату, is_working, title/source_ref. Проверяются уникальность годов/дат, год override
и согласованность kind/is_working. Две версии одного года — ошибка выбора, а не
автоматический выбор последней. Вход копируется; хеши не зависят от порядка списков.

Все календари `status=draft`. `completeness=complete` описывает заявленную полноту
снимка, а не подтверждённую официальность. `provisional` требует причины и блокирует
весь соответствующий год, если он нужен расчёту. Точных интервалов неопределённости
пока нет. Обычная неделя используется только внутри явно предоставленного complete
года; отсутствующий год не заменяется пн–пт. Для рабочих дней проверяется даже
исключённый день события. Для переноса — каждая просмотренная дата переноса.

Fixture `tests/fixtures/kg_entry/synthetic_work_calendars.json` — **искусственный**
календарь 2026/2027, не официальный производственный календарь КР. В нём 9 октября
условный праздник, 10 октября рабочая суббота, 12–13 октября нерабочие; 1 января
условный праздник, 2 января рабочая суббота. Эти даты проверяют алгоритм и не
подтверждают реальный режим работы госорганов. Офисный календарь не подключён.

## Арифметика и границы

| Unit | Явные параметры | Поведение |
|---|---|---|
| working_days | date anchor, count_anchor_day bool | Считает только рабочие даты по переданному календарю, before/after |
| calendar_days | date anchor, count_anchor_day bool | N или N−1 суток от anchor в указанную сторону; рабочий календарь нужен только для переноса |
| months | date anchor, month_end=clamp/reject | Прибавляет N календарных месяцев сразу к исходной дате; день отсутствует → последний день либо отказ |
| hours | aware timestamp, hours_mode=elapsed | N×3600 секунд по UTC, результат в Asia/Bishkek и UTC; дата без времени не превращается в полночь |

Неприменимые поля proposed policy должны быть NULL. Defaults для включения anchor,
month-end и elapsed hours нет. Имя события должно точно совпадать с typed rule anchor.
`boundary_inclusive` из source rule выводится отдельно без нормативной интерпретации;
это не неявное одобрение `count_anchor_day`. `boundary_interpretation_approved=false`.
Истинный нормативный смысл границ ещё должен определить владелец знаний.

Для дат/месяцев применяется typed rule `shift_from_nonworking`:
none / next_working / previous_working. Рабочая дата остаётся на месте; остальные
сканируются в указанную сторону независимо от before/after. Hours + перенос
заблокирован как `hour_calendar_shift_unsupported` до определения бизнес-правила.

Формат anchor: YYYY-MM-DD либо YYYY-MM-DDTHH:MM:SS[.ffffff](Z|±HH:MM), дробная часть
1–6 цифр. Строгая форма и стандартный datetime parser действуют даже без optional
RFC3339 checker jsonschema. Неверные даты, минуты смещения, leap seconds, naive
timestamps отклоняются. `-00:00` не считается известным UTC offset для часов.
Day rules не обрезают timestamp до даты. Нет tzdata → `timezone_unavailable`;
постоянное смещение вместо IANA zone не подставляется.

Защитные пределы: duration 3660 дней / 87840 часов / 120 месяцев, до 3660 переходов
даты на каждый поиск рабочих дней/перенос; годы Python date 1..9999. Превышение
возвращает причину без частичной даты. Это технические ограничения, не нормы PDF.

## Примеры для проверки, не утверждённые эталоны

| Synthetic input | Scenario result |
|---|---|
| 3 working_days after 2026-10-08, exclude anchor | 2026-10-15; counted 10, 14, 15 октября |
| То же, include anchor | 2026-10-14 |
| 3 working_days before 2026-10-15, exclude anchor | 2026-10-08 |
| 2 working_days after 2026-12-31, exclude anchor | 2027-01-04, нужны версии обоих годов |
| То же, без календаря 2027 | calendar_missing, никакой даты |
| 1 calendar_day after 2026-10-08, next_working | 2026-10-10 |
| 1 month after 2026-01-31, clamp | 2026-02-28; reject → month_day_missing |
| 2 months after 2026-01-31, reject | 2026-03-31, без промежуточного округления февраля |
| 72 hours after 2026-12-30T20:30:00Z | 2027-01-03T02:30:00+06:00 |

99 tests включают 120 seeded cases с отдельным oracle на отсортированном множестве
рабочих дней, прочие типы времени, негативные входы, пропущенный/неполный календарь,
date overflow, trace/hashes, повторный CLI без записи и все 22 реальные NULL deadlines.

```powershell
python -m pytest tests/test_kg_deadlines.py tests/test_kg_stay_days.py tests/test_kg_conditions.py tests/test_kg_country_index.py tests/test_kg_entry_validation.py -q
python -X utf8 scripts/review_kg_deadline.py tests/fixtures/kg_entry/synthetic_bundle --source tests/fixtures/kg_entry/synthetic_source.txt --calendars tests/fixtures/kg_entry/synthetic_work_calendars.json --request tests/fixtures/kg_entry/synthetic_deadline_review.json
```

## Воспроизведение и следующий этап

Отчёт включает algorithm version, input/source/bundle hash, версии/hash календарей,
trace по просмотренным дням и calculation hash. Хеш всего набора календарей учитывает
и неиспользованные годы. Для воспроизведения сохранить исходные request/bundle/calendar
JSON, код алгоритма, результат, окружение и версию tzdata: сами хеши не хранят данные.
Разрешённые timezone offsets входят в output fingerprint. Это помогает выявить другой
результат при смене tzdata, но не заменяет фиксацию версии tzdata в будущей persistence.

Таблицы work_calendars/work_calendar_days, StayInterval/Calculation snapshots, права
публикации и runtime adapter пока не реализованы. Официальный календарь, утверждённые
события/границы/месяцы и mapping NULL deadline/processing-time values также впереди.
Далее — отдельная задача на persistence и trusted DB adapter; клиентские даты до
подтверждения правил, календарей, примеров и independent review/audit закрыты.
Откат локального этапа не требует миграций или изменения реальных данных.
