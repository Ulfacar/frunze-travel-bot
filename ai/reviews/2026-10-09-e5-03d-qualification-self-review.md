# SELF_REVIEW — E5-03D

- Reviewer: Codex, тот же builder/context; независимость отсутствует.
- CRITICAL / solo; base 430768b, target UNCOMMITTED.
- Local checks PASS; статус **PARTIALLY_READY**, independent review/final audit UNKNOWN.

Повторно прочитаны task AC1–6, весь новый code/tests/CLI и соседние schema/index/conditions,
read-only DB boundary. Existing implementation/source files не менялись.

## Findings / decisions

1. При сборке condition facts нельзя менять исходный request перед hashing: копия facts
   отделена; тест проверяет исходный input, canonical hash и owned output.
2. MDA конфликт лежит в registration rule. Первое тестовое ожидание искало его только
   среди entry candidates; исправлена область проверки, общий blocker уже сохранялся.
3. Fault injection unsealed journal первоначально менял result, нарушая DB CHECK ещё
   до проверяемого вызова. Исправлен сценарий: удалить accepted journal прямым SQL
   в disposable DB; API действительно отказывает в чтении непроверенной версии.
4. Partial interview отделён от готового handoff: типы slots переиспользованы, required
   collecting/handoff не ослаблены. Missing answers перечислены, known stops приоритетны.
5. Не выбирается страна/режим по выгодности. Метки unknown/not_evaluated/met видны,
   fallback all_others не применяется; публикация/eligibility/точные значения выключены.
6. Read-only adapter не расширяет manager access, не принимает готовую историю,
   не пишет анкету/журнал и проверяет DB sources перед ответом. SQL recorder видит SELECT only.

## Evidence

- Initial new tests: 47 passed / 2 failed, оба test setup/expectation выше.
- Related: `pytest test_kg_qualification test_kg_entry_validation test_kg_country_index
  test_kg_conditions test_knowledge_projection test_entry_storage`: **382 passed / 83.81s**.
- После добавления source ownership и passport switching: **51 passed / 12.33s**.
- CLI original PDF + real draft/catalog + synthetic MDA profile: PASS, 2 candidates,
  2 registration references, source_conflict; selected=NULL/may_quote=false.
  SHA256+mtime шести файлов (PDF, 3 YAML, catalog, request) неизменны.
- Full suite N/A для этого diff: новые изолированные review modules, нет runtime/model/
  migration/существующих алгоритмов changes. Предыдущий полный прогон и его dates baseline
  не выдаются за новый PASS. Независимое review и PG16 UNKNOWN.
- Production N/A: локальный scope; runtime не подключён, внешних записей/отправок не было.

## Remaining limits

Это не весь CALC-01 и не полный список стоп-факторов Б.4. Клиентский диалог, сохранение
квалификации, выбор утверждённых правил, автоматическое соединение с CALC-02/03,
специальные вопросы/политика приоритета и scoped manager UI — отдельные этапы.
Нельзя представлять условие met или проверенную целостность истории как разрешение въезда.
SELF_REVIEW не закрывает critical gate; независимый packet подготовлен.
