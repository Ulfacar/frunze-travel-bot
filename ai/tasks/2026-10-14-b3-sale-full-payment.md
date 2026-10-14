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
| S6 | Полная оплата, затем аннулирование/возврат | см. решение (NEEDS_HUMAN_DECISION) |
| S7 | Переплата 600 при договоре 500 | won один раз, переплата видна отдельно |
| S8 | sale_check под флагом | не пишет CONVERTED в Bitrix, ведёт к договору в панели |

## Флаги
Новые: `sale_by_full_payment_enabled` (OFF), `sale_check_panel_contract_enabled` (OFF).
Существующие: `service_cases_enabled`, `admin_workday_enabled` (OFF).
