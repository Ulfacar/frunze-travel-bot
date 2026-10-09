# TASK — E5-03D unified qualification review

- Authorization: Алан «Ладно продолжай работу», продолжение PDF; commits/push ранее разрешены.
- Base: fix/tours-search-quality @ 430768b. CRITICAL / solo.
- Target: local implementation, checks, review packet, commits and handoff. No production.
- Independent review/final audit UNKNOWN; SELF_REVIEW не заменяет gate.

## Scope and acceptance

1. Единый детерминированный отчёт по шагам PDF 2.1 (physical page 19): въездной паспорт,
   документ, цель, кандидаты правил, даты/история, нарушения, регистрация, вывод.
   Не объявлять право въезда на основании черновых норм. selected_regime/visa_required
   и точные клиентские значения остаются NULL; may_quote=false.
2. Минимальный строгий request использует определения existing slots, без контактов,
   номеров документов, свободных заметок и входных decision/history/stop_factors.
   Partial profile допускает недостающие поля; не подменять unknown отрицанием.
   Явный паспорт входит в гражданства; неизвестная страна и неверные даты отклоняются.
3. Упорядоченные missing facts/следующие 1–3 вопроса RU/EN; known stop reasons имеют
   приоритет перед продолжением анкеты. Особые документы/работа/заявленные нарушения/
   отказ/истёкший паспорт направляются на manager review, без правовых утверждений.
4. Country index + ConditionReview объединяются по unit_id. Отдельно registration
   references, excluded predicates и withheld all_others. Нельзя выбрать самый удобный
   паспорт/режим, считать condition met разрешением или применять fallback автоматически.
   Без каталога условный кандидат остаётся unknown. Несколько кандидатов видны явно.
5. Read-only DB adapter использует named full-admin, accepted pinned knowledge version,
   verified projection/catalog и, опционально, scoped saved history. Никаких INSERT,
   UPDATE, DELETE, flush/commit, данных клиента в журнале; corrupt/cross-contact отклоняются.
   Анкета — заявленные данные; history только из БД. Расчёты дней/сроков не запускаются
   автоматически без явной политики и выбора источника.
6. Read-only CLI на явном source и synthetic profile, без .env/DB/network. Тесты
   branch/order/unknown/conflict/PII-injection, source identity, DB auth/scope/integrity,
   неизменность данных и реальный PDF MDA/особые условия. Adjacent tests, committed copy.

## Pre-audit / design

Прямо прочитана physical page 19 PDF, SHA256
141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2.
Источник описывает алгоритм, но не утверждает наши extracted units. Слой orchestration
не повышает их статус. Несколько национальностей требуют явного паспорта даже если
один вариант выгоднее. Условия >3 лет/1 месяца — отдельные заключения проверяющего,
не вывод LLM из дат. Fallback all_others удерживается до отдельной полноты/приоритета.

Новая схема частичной анкеты переиспользует типы slots, не меняет collecting/handoff
валидацию существующего модуля. Необязательность полей нужна для последовательного
сбора; полнота определяется ordered questions. История не берётся из этой анкеты.
Read-only adapter оставляет прежнюю ограничительную auth boundary; manager scope,
HTTP/LLM, persistence квалификации и политика retention не входят в этап.

No migration, no changes to existing calculators or source bundle. Recovery — revert
новых модулей/CLI, данных для отката нет. CRITICAL independent review/audit и PG16
предыдущих этапов остаются UNKNOWN. Старый facts date test и prod_traps baseline вне scope.
