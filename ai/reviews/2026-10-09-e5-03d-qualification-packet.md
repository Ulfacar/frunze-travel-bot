# Independent review packet — E5-03D

- Risk/mode: CRITICAL / solo. Target local implementation, not release.
- Base `430768bfe9de7dc798db18671173c2e39436cbf2`; branch fix/tours-search-quality.
- Target **cdc490c691d0437cfc0863bc1dc399ae1f39f723**; manifest `2026-10-09-e5-03d-qualification-snapshot.json`.
- Independent reviewer/final auditor UNKNOWN. Builder SELF_REVIEW читать после своего прохода.

Требования: task `ai/tasks/2026-10-09-e5-03d-qualification-review.md`, AC1–6;
PDF physical page 19 §2.1; CALC-01/AC-18/20 в CRM spec. Контракт
`docs/e5-03d-qualification-review.md`. Только read-only review + isolated tests;
production/отправки/private data transfer не разрешены.

Проверить фактические новые qualification_schema/qualification/entry_qualification,
CLI, fixture и tests, вместе с country_index, conditions, slots и DB source verification.

| Requirement | Critical checks |
|---|---|
| AC1 route | Все восемь шагов представлены вопросами/кандидатами/blockers, нет client eligibility |
| AC2 input | Unknown не false; паспорт в гражданствах; нет arbitrary PII/history/decision; bounded errors |
| AC3 interview | RU/EN 1–3 вопроса в порядке; known stops приоритетнее missing; это не весь Б.4 |
| AC4 rules | MDA registration conflict не потерян; met не approval; исключения not_met; all_others удерживается |
| AC5 DB | Named full-admin до данных; accepted journal, projection+links, contact/history scope, SQL только SELECT |
| AC6 evidence | CLI входы неизменны, error не повторяет PII; pinned source, passport switching, source ownership |

Проверить отсутствие скрытого выбора режима, угадывания одно/двойного гражданства,
официальных сроков или календарной политики. History integrity не равна достоверности
истории; continuity/полнота/подтверждение должны оставаться отдельными ограничениями.
condition_facts — заключения специалиста, не свободный LLM tool input.

`python -m pytest tests/test_kg_qualification.py -q`; соседние команды в handoff после
своего первого verdict. Записать реально проверенный commit и findings. Нельзя принять
manifest или builder PASS как независимое разрешение на release.
