> Приложение к `docs/crm-chronology.md`. Собрано 27.11.2026 агентом (Claude, отдельный контекст, только чтение) и проверено ведущим выборочно. Замер ведущего на проде (psql, только чтение).

# D. Прод — замер 27.11.2026 (read-only, psql в frunze-travel-db-1)

## Когда включали флаги панели (app_flags.updated_at)
- 19.10: admin_new_look, admin_chat_redesign, admin_focus, admin_workday, service_cases, panel_send_media, pilot_reply_queue (audit: admin, flag=on)
- 20.10: admin_inbox_limit; 21.10: panel_simple_mode
- 11.11: board_columns_by_direction, visa_touch_tasks, panel_pilot_summary, lost_reason
- 12.11: visa_card_fields
- 27.11: panel_fresh_first, panel_board_column_cap
- bitrix_*: 06.07–14.09 (зеркало/автосделки — Битрикс по-прежнему основная система)
- bots_enabled глобальный = f с 24.06 (боты включаются пер-бот ключами `bots_enabled:<bot>` — не трогал)

## Входы в панель (audit_log action=login), за всё время
admin 87 (последний 23.10) | grisha 43 (последний 27.11 — ВСЕ 5 ноябрьских входов 27.11 = мой скрипт замера) |
sezim 23 (28.07, уволилась) | medina 19 (последний 21.10) | ademi 18 (13.11) | grisha-admin 7 (13.11 — показ) | eliza 5 (08.07) | aisina 0.
С 01.10: admin 33, grisha 25 (до 27.11 — только октябрь), grisha-admin 7, medina 6 (13–21.10), ademi 5.

## Ручные действия людей в панели с 01.10 (кроме login/assign)
- 1 смена стадии (01.10, admin); ademi — takeover ×15 (03.10–10.11), release ×2; reassign ×1 (21.10 admin);
  grisha-admin takeover ×2 (13.11 — показ); task_cancel ×1 (13.11 ademi); 9 переключений флагов (admin).
- assign 725 — автоназначение (1 «менеджер» = система).
- Итого: после 21.10 Медина не входила ни разу; Элиза и Айсина — ни разу с июля / никогда.

## Данные CRM
- service_cases 0, service_payments 0, entry_applications 0, requests 0, client_notes 0; deals 628 (это зеркало Битрикса).
- calendar_tasks с 01.10: 2677, все kind=call, status=planned; просрочено 2600; выполнено с 01.10 — 0.
- Визовые диалоги по стадиям (не архив): greeting 2472, office 113, manager 87, progress 15, qualification 5.
- Исходы: in_progress 2021, manager 338, office 131, won 6; «lost»/причины отказа — 0 (флаг lost_reason ON с 11.11).

## Трафик по неделям (messages, sender) — визы / туры
- Сентябрь–середина октября: туры ~1000–1700 клиентских в неделю, менеджеры туров ~900–1400; визы клиентов 370–1020.
- Неделя 19.10: туры почти ноль (manager 16), визы бот 8 — провал (Wappi 402 по GetVisa с 23.10; туры — тоже).
- Неделя 26.10: туры 148 клиентских, визы бот 6.
- 02.11–15.11: восстановление (09.11: туры 2597 клиентских, бот 1388).
- 16.11: туры 1022; с 23.11 туров нет совсем (Wappi туры 402 с 17.11), визы 488 клиентских / бот 202 / менеджеры 237.
- Менеджеры при этом пишут сотни сообщений в неделю — в WhatsApp/Битриксе, не через панель.

## Дополнение (после агента C)
- Опубликованные воронки (workflow_versions): tour_package v1 — 7 этапов (19.10, alan); visa_usa v1 — 9 этапов (19.10, alan);
  visa_schengen v1 — 19 этапов (11.11, admin). Других нет: въездная КР (23), США новая (22), Китай/Корея/Япония (16) — НЕ опубликованы.
  (В ai/tasks/2026-11-11-demo-readiness.md сказано «версия #4» — в базе версия 1.)
- alert_awaiting_minutes = 10 (ответ 5.7 заказчика: 3 минуты); pilot_reply_sla_minutes = 30.
