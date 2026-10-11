# Актуальный статус PDF / CRM · 11.10.2026

**90/100 технических баллов; 10 остаётся.** Это результат фиксированных50 критериев,
а не процент готовности к запуску. Актуальные доказательства —
[реестр критериев](pdf-engineering-criteria.json) и [сверка26 разделов](e5-pdf-section-coverage.md).
E6-16 сохраняет внутренние черновики уведомлений; E6-17 закрывает ревью анкет;
E6-18 исправляет типовую целостность семи журналов. E6-19 закрывает ревью задач.
E6-20 (`27b8463`) закрывает ревью самих сроков: снятие ручной даты доступно при
заполненном журнале, история сохраняется, связанная задача согласуется атомарно.
Независимые APPROVE/GO получены. Ранее найденный дефект G02 закрыт; новых баллов
за исправление не добавлено.

Общий прогон снимка `dc474d8`: **4702 PASS, 231 SKIP, 0 FAIL/ERROR**. Он предшествует
E6-20. Финальное исправление отдельно прошло **113 проверок**, включая26 реальных
PostgreSQL. Дополнительный прогон на `27b8463`: **240 PASS**, включая все230 ранее
пропущенных PostgreSQL-сценариев и10 проверок SQLite. Остался один тест внешней сети,
который не запускался. Эти пересекающиеся проверки не складываются в новый полный прогон.

Остались C05 — утверждённый выбор продукта; H02/H03 — полный диалог и ответы по
утверждённым источникам; J01/J02 — все14 SOP и эталоны приёма/квалификации;
J03 — остальные критические ревью; J05 — приёмка владельцем и допуск пилота.
208 исходных единиц остаются черновыми,0 confirmed. Нужны решения по источникам,
деньгам, хранению, ролям и сообщениям. Код сохраняется только в рабочую ветку;
деплоя и включения новых функций на сервере нет.

Итоговый [PDF-отчёт](reports/frunze-pdf-progress-2026-10-11-overnight-local.pdf):
5 проверенных страниц, результат и остаток по всем26 разделам исходного документа.
[Контекст для продолжения](../ai/handoffs/2026-10-11-0705-overnight-local-pdf.md).
Отчёт сохранён в рабочей ветке и отправлен владельцу через существующего Telegram-бота
11.10 в07:24 по Алматы; API подтвердил отправку. Временная тестовая БД остановлена.

Ниже сохранены исторические этапы. Их проценты, «следующий шаг» и незавершённые
проверки относятся к времени записи и не заменяют актуальный статус выше.

# Исторический E6-14 checkpoint — durable handoff suppression

Reviewed local code `fe43b46a9dc184a5430ee7b9f4653c8e296c475a`, saved/pushed only to origin working branch. **89/100 technical points,11 remaining**. Fixed B04/H04 add5 only for explicitly activated and bound private WhatsApp routes. Atomic frozen card/stop, separate named-owner ACK, installed final reply/followup guards and durable suppression through policy removal/recovery. No global multi-channel claim; real activation and authority remain empty.

Builder163 PASS/2 optionalPG SKIP plus30 actualPG PASS; independent review APPROVE and separate audit GO (118/31/2/1 and153 PASS, overlapping scopes). Mobile/no-JS/sole print page inspected. Exact26-file root/archive/commit identity PASS. Two reviewed concurrency defects were fixed and retested. Broad/full exact-r2 suites continue; running checks are not counted green. E6-12 full completed4371PASS/66SKIP. Detailed evidence: `ai/handoffs/2026-10-11-0435-e6-14-channel-handoff.md`.

Next E6-15 connected source scenarios and E6-16 policy-gated saved notification drafts. Approved qualification/answers, full escalation/trigger integration, earlier critical review and owner acceptance remain. No deploy; final Telegram pending.

# E6-13 checkpoint — versioned internal quotations

Reviewed local code `c611b86d23d622c64bb9056e4e855c6e93437370`. **84/100 technical points,16 remaining**, fixed definitions unchanged; only C04 adds2. Immutable exact application/applicant quotes retain old algorithms and policy snapshots, separate four fee components and USD/KGS, and block complete prices when any required amount is unknown. Explicit preview/save, current authority overlay, native history/print. Actual server recipes remain empty; no legal eligibility, FX, payment, contract or client sending is inferred.

Independent review APPROVE/final audit GO for r2, extended to exact r3 after independent one-file whitespace/AST checks. Builder92 focused/browser,23 actualPG; broader273PASS/2 optionalPG SKIP; reviewer94/24/1/2 and separate auditor121PASS with26 actualPG checks (overlapping scopes). Binary COPY recovery preserves old receipts and supports a new revision; root inspected both print pages. Failure/fix sequence, exact commands and limitations: `ai/handoffs/2026-10-11-0350-e6-13-versioned-quotes.md`.

Next E6-14: explicitly bound WhatsApp dialog suppression and atomic handoff, pre-audit GO. No runtime implementation or B04/H04 credit yet. Complete classification/approved responses, client notifications, exact whole-SOP/B8 acceptance, prior critical review and owner decisions remain. No deploy; final Telegram pending.

# E6-12 checkpoint - 2026-10-11

Reviewed local code `594a9f3c28be2d2b44986c6eed583b805e0c677b`, pushed to origin working branch. **82/100 technical points,18 remaining**, fixed definitions unchanged. Only B03/H01 add5 points for the complete typed A-H catalog and persisted RU/EN adapter. B04/H02/H04/J02 remain partial/UNKNOWN; installed bot/followup suppression and exact approved qualification scenarios are not complete.

Independent review APPROVE, final audit GO;22-file root/archive/commit identity PASS. Exact-r3 builder43 focused +19 actualPG PASS, reviewer116+28 PASS, auditor30 PASS including five goldens/two browsers/21actualPG checks; counts overlap. COPY recovery/read/retry/new write PASS. Whole-project review, actual source/privacy authority, native pg_dump and owner acceptance remain UNKNOWN. No deploy. Evidence: `ai/handoffs/2026-10-11-0325-e6-12-interview-handoff.md`.

Next E6-13 versioned quotations; preliminary36pure arithmetic checks do not earn C04. Final Telegram status remains pending until the overnight work concludes.

# Прогресс по Kyrgyzstan visa knowledge base v1.1

Историческая оценка этапа E6-11: **77/100**; актуальный счёт указан в начале документа. Журнал уведомлений портала и отдельное атомарное подтверждение сохранены в `8ad7b78`; локальные PostgreSQL16, конкуренция и восстановление через COPY проверены. Независимые review/audit этого модуля завершены. Реальная почта и политики ещё не подключены. Ниже сохранён исторический экспертный ориентир предыдущего этапа, а не текущий процент или статус всех модулей.

На **10.10.2026**, после E6-01A/B/C и первого среза документов E6-02A, рабочий
ориентир — **около 30% выполнено / около 70% осталось**. Это округлённая экспертная
оценка инженерного объёма полного использования PDF въездным ботом и CRM:
подготовки знаний, расчётов, диалога, заявок, документов и приёмки.
Остальная CRM, туры и выездные визы в знаменатель не включены.

Это экспертный диапазон по готовности компонентов, а не измеренный процент требований,
страниц, строк кода или трудозатрат. Задачи пока не оценены в часах; точность до единиц
процента была бы ложной. Готовность к запуску отдельно не подтверждена.

Основание: прямо прочитанная IT-инструкция на физической стр.2 PDF (печатная стр.1),
код на `fix/tours-search-quality` с этапами E5-01B/C, E5-02D/E/F, E5-03A/B/C/D/E и E5-04A/B/C/D,
backlog E5 и относящиеся к въезду задачи E6. PDF SHA256:
`141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.

| Требование IT-инструкции PDF | Что уже есть | Что остаётся |
|---|---|---|
| System prompt: Б.1, Б.2, Б.7 | Текст в конверсии | Отдельный въездной сценарий, подключение инструкций и проверка поведения |
| Эскалация: 4.1, Б.4, Б.6 | Черновые стоп-факторы, схема handoff, карточка сохранённых ответов/пробелов/источников и печать | Исполняемые переходы, передача менеджеру, проверка ошибочных/неполных ответов |
| Слоты JSON: Б.3 и блок 18 | JSON Schema, семантическая валидация collecting/handoff, тесты | Сохранение в процессе, условные поля, история поездок, использование в диалоге |
| Машинные правила: Б.5 | 208 черновых единиц, строгий preflight, 7 таблиц знаний, атомарный локальный импорт и diff; review-индекс 201 связь и 6 условий; CALC-02/03 и 7 новых таблиц истории/календарей/расчётов, DB adapter и replay | Выбор режима, независимая проверка и PG16, утверждение, публикация/откат, клиентские расчёты и официальный календарь |
| Диалог: блоки 3–4 | Анкета v2: заявители, семья, приглашающий, пункты/цель/риски; RU/EN до трёх вопросов; версии, CAS/retry/replay; форма и PDF-карточка в CRM под full-admin gate | Реальный поток бота, оставшиеся слоты A–H, менеджерский scope и handoff workflow |
| Поисковые знания: 1–2, 5–13, 15–17 | 74 фрагмента / 40 таблиц; проверяемый локальный индекс, CLI и поиск в CRM с полным текстом/метками/provenance | Независимая сверка, допуск к клиентским ответам, качество ответов и подключение к боту |
| CRM: 13, 14, 18, 19 | Общая инфраструктура услуг; E6-01A: отдельные номерные заявители, попытки/reference и журнал фактов | Профили/права людей, четыре полных процесса, документы/сроки и сопровождение |
| Шаблоны: приложение А | 13 извлечённых черновых шаблонов | Проверка содержимого, заполнение, документы/email и включение в процесс; 2 шаблона заблокированы |
| Приёмка: примеры Б.8 | Исходный текст примеров | Проверенные эталоны, сквозные диалоги, негативные проверки и пилот с менеджерами |

Доказательства готовой основы: `app/knowledge/`, `app/domain/knowledge_import.py`,
`app/domain/knowledge_review.py`, `knowledge/kg_entry/` и тесты соответствующих модулей.
E5-03C реализовал `stay_intervals` в составе версий полной истории и сохранение расчётов.
Анкета читает закреплённую историю через E5-03D/E. E5-04D добавляет редактор истории
в CRM и явное подключение версии к новой проверке; клиентского диалога пока нет.
E5-03A считает локальные сценарии по отдельному history snapshot; клиентский остаток
заблокирован, правила включения границ и эталоны ещё требуют утверждения.
E5-03B добавил версии календарей в памяти и арифметику сроков; реальные праздники,
переносы, события и правила не утверждены. Все 22 deadline units пока NULL.
Общие старые воронки visa/tours/tickets не считаются выполненным въездным сценарием.

Из 208 черновых единиц **0 confirmed**, 183 needs_verification, 22 decision_pending,
3 blocked; у 82 значение отсутствует. Это характеристика источника, не 208 завершённых
требований. Точность юридических норм/цен не утверждалась. Импорт и договор всё ещё
ожидают независимые CRITICAL review/audit; PostgreSQL-проверки этого импорта UNKNOWN.

## Следующие законченные этапы

1. Независимо проверить готовое локальное хранение истории/календарей/расчётов, DB-индекс и условия на PG16.
   Параллельно владельцу знаний закрыть SRC/DEC и определить порядок утверждения.
2. Реализовать публикацию с проверками и откатом; независимо проверить импорт на PG16.
3. Утвердить примеры дней/окон/сроков и официальный календарь, добавить стоимость и подключить расчёты к проверенным данным.
4. Подключить допущенные знания, RU/EN диалог и передачу менеджеру.
5. Довести въездные процессы CRM, документы и сопровождение; провести сквозную приёмку.

Новый корпус закрывает локальную подготовку поискового текста, но не весь поиск.
После него общий диапазон **70–80% остатка** пока сохраняется: основные интеграции впереди.
Следующий локальный этап E5-02D добавил [поиск страны для проверки](e5-02d-country-index.md),
но не исполняемый выбор режима. Он также не даёт оснований менять диапазон на точный процент.
E5-02E добавил [условия шести режимов](e5-02e-conditions.md) и проверку полноты профиля;
публикация и полноценное определение применимости ещё впереди.
E5-02F добавил [атомарное сохранение индекса и условий](e5-02f-projection.md) и чтение
из БД с проверкой целостности. CRITICAL gates остаются UNKNOWN; диапазон остатка прежний.
E5-03A/B добавили локальную арифметику дней и [сроков](e5-03b-deadlines.md). Это ещё
не клиентский калькулятор: подтверждение норм, официальный календарь,
выбор режима и интеграция не закрыты. E5-03C добавил persistence и воспроизведение
по сохранённым версиям; независимая проверка и PG16 runtime ещё UNKNOWN.
Нового измеренного процента по этим этапам нет; общий диапазон сохраняется.
E5-03D связал частичную анкету, country index, conditions и registration references
в [единый проверочный отчёт](e5-03d-qualification-review.md), включая read-only DB adapter.
Он пока не выбирает утверждённый режим и не подключён к клиентскому диалогу.
E5-03E добавил [сохранение частичной анкеты и отчёта](e5-03e-qualification-storage.md),
восстановление последней версии, историю исправлений и воспроизведение. Это ещё
не все слоты, не handoff и не подключение к боту. Независимая проверка и PG runtime
остаются UNKNOWN. Оснований для нового точного процента нет.
E5-04A связал требования PDF с [пилотной формой CRM](e5-04a-crm-qualification.md):
редактирование, сохранение, вопросы RU/EN, ошибки и история версий через браузер.
Доступ пока только администратору, feature OFF; это не запуск диалога и не выполнение
четырёх процессов E6. По указанию Алана PDF/CRM развиваются вместе, общий редизайн позже.
E5-04B добавил [карточку для проверки](e5-04b-review-card.md) по сохранённой версии:
ответы, дополнительные условия, пробелы §3.4/Б.4, источники и печать/PDF. Карточка
не создаёт передачу менеджеру; права остаются full-admin до ответа владельца.
Общий диапазон остатка прежний, нового измеренного процента нет.
PDF-отчёт `reports/frunze-pdf-progress-2026-10-09.pdf` остаётся историческим снимком E5-03E.
Предыдущий [пятистраничный отчёт E5-04C/E5-01C](reports/frunze-pdf-progress-2026-10-09-intake-search.pdf)
содержит результаты и полную таблицу разделов; актуальные evidence — в `ai/STATE.md`.
E5-04C добавил [расширенную анкету](e5-04c-intake.md) и семейные сведения в карточке;
E5-01C — [реальный локальный поиск](e5-01c-knowledge-search.md) с проверкой источника.
Это ещё не полный диалог, не отдельные заявки и не автоматический handoff.
Подробная [сверка всех 26 разделов PDF](e5-pdf-section-coverage.md) показывает
выполненную локальную часть и оставшиеся требования без подмены процедур наличием текста.
E5-04D добавил [редактор фактической истории](e5-04d-history-crm.md), явное подключение
версии к новой проверке и поездки в закреплённой печатной карточке. Часть D1/D2/D5;
неизвестные даты, тип/срок прежних виз и паспортная преемственность ещё требуют работы.
Предыдущий [отчёт E5-04D](reports/frunze-pdf-progress-2026-10-09-history.pdf) сохраняет
различие между локальными функциями, полным выполнением PDF и запуском.
См. [детали корпуса](e5-01b-search-corpus.md) и [backlog](crm-delivery/backlog.md).

E6-01A добавил [реестр заявителей и подач](e6-01a-applications.md): раздельные люди,
документы и попытки, доработка/отказ/связанный повтор, источники/даты и уникальный
reference. Работа проверяется только локально на синтетике. Это ещё не полный
профиль заявителя, не все четыре процесса и не выполнение всего PDF. Нового
измеренного процента по этому этапу нет; точный остаток не пересчитывался.

Предыдущий [пятистраничный отчёт E6-01A](reports/frunze-pdf-progress-2026-10-10-applications.pdf)
содержит результат реестра, фактические проверки и остаток по всем 26 разделам.
Точная история проверки и исправления — в handoff от 10.10.2026 из `ai/STATE.md`.

E6-01B добавил [сводку группы](e6-01b-group-overview.md): текущие попытки всех
зарегистрированных людей, прежняя история, люди без заявок, исключения, фильтры
и печать. Общие итоги охватывают всю услугу независимо от страницы. Одобрение
не подтверждает документы, поездку или завершение услуги; полнота необходимых
процедур ещё не определяется. Новый процент не вычислялся.
Предыдущий [отчёт E6-01B](reports/frunze-pdf-progress-2026-10-10-group-overview.pdf)
содержит результат и обновлённую сверку всех 26 разделов.

E6-01C добавил [проверку черновых переходов](e6-01c-process-preview.md): 87 кодов
четырёх процессов, 71 вариант переходов с условными фактами, версии и экран CRM. Флаги,
отказ/повтор и отдельные процедуры различаются; отсутствие данных не считается
подтверждением. Это ещё не опубликованные исполняемые процессы.
[Отчёт предыдущего этапа E6-01C](reports/frunze-pdf-progress-2026-10-10-process-preview.pdf)
содержит результат, проверки и остаток по всем26 разделам. Нового процента нет.

## E6-02A — матрица документов

[Чек-листы документов](e6-02a-document-checklists.md): все23 строки и9 типов
исходной матрицы, явная условность, получение/доработка/проверка и актуальность
версии. Полные дополнительные требования сохранены для сверки, но не оцениваются
автоматически. Реальный комплект не принимается; загрузки/хранения файлов ещё нет.
Новый [PDF-отчёт](reports/frunze-pdf-progress-2026-10-10-document-checklists.pdf)
фиксирует этот срез и остаток по всем26 разделам. Ориентир30/70 приблизительный.
