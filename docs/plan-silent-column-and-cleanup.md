# План: чистка диалогов + колонка «Молчат» (дожим)

> Автор плана: Claude (ревью за Claude). Реализация: Codex.
> Контекст данных на проде 30.06.2026: tours 227 активных (214 greeting, 218 last=client, 9 last=bot/manager),
> visa 106 активных (93 greeting, 95 last=client, 11 last=bot/manager). Строгих «молчат» (мы писали
> последними, не терминал) всего ~5 на воронку — поэтому колонка строится по ШИРОКОМУ определению
> (любой застрявший лид), а дожим расширяется на тех же. Решение заказчика: «широко, дожим расширить».

## Цель
1. Почистить доску от рекламы/пустых лидов.
2. Новая колонка канбана «Молчат (на дожим)» — застрявшие лиды; автодожим работает на них.
3. Единое определение «молчат» для доски и дожима (один источник правды).

## Шаг 0. Новый модуль `app/core/leadstate.py` (источник правды)
Вынести чистые функции, чтобы доска и дожим судили одинаково:

- `is_noise(conv) -> bool` — перенести логику из `app/admin/router.py` (`_card_model`, ~стр. 140-150:
  `NOISE_LINK_RE` / `NOISE_MEDIA_TERMS`) **плюс** расширить: пустой/мёртвый лид =
  `stage == 'greeting'` И пустой `qualification` И нет ни одного сообщения от `bot`/`manager`
  (только клиент) И возраст диалога > `cfg.noise_stale_days` (нов. конфиг, дефолт 3 дня).
- `is_silent(conv, now, cfg) -> bool` — **широкое** определение застрявшего лида:
  `not intercepted` И `not followup_sent` И `not is_noise(conv)` И `outcome not in {won, lost}`
  И колонка стадии **не** в `{office, manager, follow_up}` И есть хоть какое-то сообщение
  И неактивен ≥ `cfg.followup_after_hours` (24 ч). **НЕ зависит от того, кто писал последним.**

`STAGE_TO_COLUMN` тоже перенести сюда (используют обе стороны). `app/admin/router.py` и
`app/core/followup.py` импортируют из `leadstate`.

## Шаг 1. Колонка на доске (`app/admin/router.py`)
- В `BOARD_COLUMNS` добавить `("silent", "Молчат (на дожим)")` — перед `("follow_up", …)`.
- `COLUMN_TO_STAGE` строить **исключая** `silent`:
  `{key: key for key, _ in BOARD_COLUMNS if key != "silent"}` → ручной drop В неё отклоняется
  (колонка вычисляемая, не стадия).
- В `_card_model` добавить поле `is_silent` (вызов `leadstate.is_silent(conv, now, settings)`).
- В `_build_board` роутить: если `m["is_silent"]` → bucket `silent`, иначе по стадии (как сейчас).
  Молчащие **вынимаются** из обычных колонок в общий пул (без дублей).
- В `metrics` добавить `"silent": len(buckets["silent"])`.

## Шаг 2. Бейдж в шаблоне (`app/admin/templates/_board.html`)
После блока `needs_reply` (~стр. 55-60) добавить:
```html
{% if c.is_silent %}<span class="badge silent">молчит {{ c.time_label }}</span>{% endif %}
```
+ CSS-правило `.badge.silent` (приглушённый серо-янтарный) рядом с прочими `.badge`.

## Шаг 3. Дожим (`app/core/followup.py`)
- `select_followup_targets` переписать через `leadstate.is_silent` (вместо собственных проверок)
  + оставить канальные ограничения: `channel == 'whatsapp'` И есть `chat_id`/`user_id` И `bot_id`.
- **Убрать** строку `if c.last_sender == "client": continue` (теперь дожимаем и тех, кому бот не
  ответил), но **обязательно** опираться на `is_silent`, который уже исключает `is_noise` —
  чтобы НЕ пинговать рекламу/пустые.

## Шаг 4. Чистка (`app/admin/router.py`)
- Кнопка «Скрыть рекламу/без диалога» (endpoint `/conversations/archive-noise`) уже есть —
  автоматически станет ловить больше за счёт расширенного `is_noise`.
- (Опц.) добавить в планировщик авто-архив `is_noise`-диалогов старше N дней.

## Шаг 5. Конфиг (`app/config.py`)
- `noise_stale_days: int = 3`.
- Дожим использует существующий `followup_after_hours = 24`.

## Шаг 6. Тесты
- `tests/test_leadstate.py`: таблица кейсов на `is_noise` / `is_silent` (реклама-ссылка,
  пустой greeting, client-last старый → silent, bot-last старый → silent, у менеджера → нет,
  won/lost → нет, свежий < 24 ч → нет, followup_sent → нет).
- Доска: молчащие уходят в `silent`, не дублируются в стадийных колонках; `metrics.silent` верный.
- Дожим: реклама не пингуется; client-last старый — пингуется; whatsapp-only сохраняется.

## Файлы
- `app/core/leadstate.py` (новый)
- `app/admin/router.py`
- `app/admin/templates/_board.html`
- `app/core/followup.py`
- `app/config.py`
- `tests/` (новые/обновлённые)

## Проверка критерия «>10»
После чистки рекламы реальные застрявшие лиды (client-last greeting, которых сотни) попадут в
«Молчат» → колонка будет >10. До чистки строгих ~5; именно широкое определение + чистка дают объём.
SQL-проверка на проде — считать по той же формуле `is_silent`.

## Ревью
После реализации Codex — Claude ревьюит диф (корректность `is_noise`/`is_silent`, отсутствие
дублей карточек, что дожим не пингует рекламу, тесты зелёные).
