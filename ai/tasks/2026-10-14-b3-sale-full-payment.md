# TASK B3 — продажа = полная оплата (CRITICAL, деньги)

- 14.10.2026, ветка `feat/visa-bitrix-exit`, бриф Алана (автономная сессия), решение Алана 14.10
  «продажа = полная оплата» (ТЗ §20, handover 03.10).
- Без деплоя и push; всё за флагами OFF. Builder: Claude. Pre-audit / review / final audit — отдельные контексты.

## Правило
Продажа наступает, когда подтверждённые оплаты по договору **в валюте договора** покрывают сумму
договора: `paid − refunded ≥ agreed`, сумма договора известна, нет «сломанных» записей
(`Balance.broken_entries`). Оплаты в другой валюте без зафиксированного курса (`Balance.unconverted`)
в зачёт не идут. Переплата — отдельно (`paid − refunded − agreed > 0`), продажу не удваивает.
Тогда `conversations.outcome = won` у диалога(ов) этого контакта в направлении дела, с основанием
в журнале (дело, сумма, валюта). Повтор запроса денег не удваивает (идемпотентность записи оплаты
уже есть в `service_money._record`).

## Факты (14.10, чтение кода)
- `app/domain/service_money.py` (`balance_from_rows`, `record_payment`, `void_entry`, `correct_*`) и
  `app/domain/service_cases.py` есть в прод-коде `913feab`; таблицы `service_cases`/`service_payments`
  есть в схеме прода (миграции 0007–0009).
- Экраны договора/оплаты (`app/admin/contracts.py`, `app/admin/workday.py`) — только в новом коде
  (не в проде). Выкатка ветки = миграция БД 0009→0043 (Dockerfile гонит `alembic upgrade head`) —
  NEEDS_HUMAN_DECISION (см. handoff).
- Дело связано с клиентом через `contact_id`; диалог — через номер (`live_assign.contact_for_channel`).

## Приёмка
| ID | Сценарий | Ожидание |
|---|---|---|
| S1 | Договор 500 USD, оплата 500 USD | won, основание с делом |
| S2 | Частичная оплата 300 из 500 | не won |
| S3 | USD при договоре в KGS без курса | не won, деньги в «без курса» |
| S4 | Двойной клик / повтор той же оплаты | одна запись, одна продажа |
| S5 | Чужое направление (менеджер туров) | отказ, без записи |
| S6 | Полная оплата, затем аннулирование/возврат | **решение Алана 15.10:** `won` остаётся, пометка `sale_reversal_flag` в деле и `sale_fp_reversal` в журнале, один раз на эпизод |
| S7 | Переплата 600 при договоре 500 | won один раз, переплата видна отдельно |
| S8 | sale_check под флагом | не пишет CONVERTED в Bitrix, ведёт к договору в панели |

## Флаги
Новые: `sale_by_full_payment_enabled` (OFF), `sale_check_panel_contract_enabled` (OFF).
Существующие: `service_cases_enabled`, `admin_workday_enabled` (OFF).

## Статус 15.10.2026 (Claude, builder)

Код на ветке `feat/visa-bitrix-exit`, не закоммичен до ревью. Флаги OFF, миграций нет, Bitrix не
трогается. Продажа пишется событием `service_events.sale_full_payment` (а не в
`ServiceCase.outcome` — он значит «дело закрыто»), диалог получает `won` через атомарную защёлку
`claim_outcome`, в журнал панели — ровно один `sale_full_payment` на дело (его считает
`scripts/pilot_daily_summary.py`), плюс `sale_fp_dialog` / `sale_fp_conflict` / `sale_fp_reversal`.

| ID | Статус | Доказательство |
|---|---|---|
| S1 | DONE | `tests/test_sale_by_payment.py::test_s1_*`, `tests/test_admin_workday.py::test_b3_s1_*` |
| S2 | DONE | `test_s2_partial_payment_is_not_a_sale` |
| S3 | DONE | `test_s3_foreign_currency_without_a_rate_does_not_count` |
| S4 | DONE | `test_s4_the_same_payment_twice_is_one_record_and_one_sale`, маршрут — повтор ключа в `test_b3_s1_*` |
| S5 | DONE | `test_b3_s5_a_tours_manager_cannot_pay_into_a_visa_case` |
| S6 | DONE | `test_s6_refund_after_the_sale_keeps_won_and_flags_once` |
| S7 | DONE | `test_s7_overpayment_is_one_sale_with_the_excess_visible` |
| S8 | DONE | `tests/test_sale_check.py::test_panel_mode_keeps_the_lead_untouched_and_links_to_the_contract` + регрессия флага OFF |

Сверх карточки: флаг OFF ничего не пишет; диалог другого направления с тем же номером не трогается;
сбой панели после коммита события дозакрывается на следующей денежной операции.
Ревью/аудит — см. handoff `ai/handoffs/2026-10-15-*-b3-sale-full-payment.md`.
