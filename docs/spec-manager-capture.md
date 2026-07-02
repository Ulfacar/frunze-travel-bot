# СПЕКА для Codex — захват ответов менеджера из WhatsApp (Wappi echo)

Автор: Claude (ревьюит). Исполнитель: Codex. Ветка: `feature/token-economy-phase1`. Не деплоить/не пушить/не коммитить.

Цель: когда менеджер отвечает клиенту НАПРЯМУЮ из WhatsApp (с номера компании), сохранять этот текст в нашу историю как `sender="manager"`, помечать диалог перехваченным (бот молчит), и не дублировать наши собственные (бот/панель) исходящие.

⚠️ ЭТО ТРОГАЕТ ЖИВОЙ WEBHOOK (`/webhook/wappi`) — точку входа всех клиентских сообщений. Требования безопасности:
- Новая ветка ТОЛЬКО ДОБАВЛЯЕТ обработку `is_me:true` echo; существующий путь входящих клиентских сообщений НЕ менять.
- Всё под флагом `capture_manager_echo` (по умолчанию **False**) — при False поведение webhook идентично текущему (echo по-прежнему отбрасывается).
- Fail-safe: любая ошибка в обработке echo НЕ должна влиять на обработку нормальных сообщений (try/except вокруг новой ветки, лог + continue).

## Факты (разведка)
- Wappi шлёт исходящие как `{"wh_type":"incoming_message","is_me":true,...}` (фикстура `tests/fixtures/wappi/own_echo.json`), структурно как входящие, только `is_me:true` и `from`=наш номер. Отличить «бот через API» от «менеджер печатал» по payload НЕЛЬЗЯ — только по нашему `provider_msg_id`.
- Текущий фильтр: `app/channels/wappi.py:46-58 is_incoming_user_message` (`not is_me`), применён в `app/main.py:224-225` (`if not is_incoming_user_message(raw): continue`).
- Наши исходящие получают `provider_msg_id` (тот же hex-id, что в webhook `id`): бот `orchestrator._reply` (`:296-297 mark_message_status set_provider_msg_id`), панель `admin/router.py:759-760`. Отправка → `WappiAdapter.send` → `_extract_msg_id` (`wappi.py:131-147`).
- Дедуп webhook-ретраев уже есть: `_seen_before(event_id)` (`main.py:81-94`).
- Ключ диалога `f"{bot_id}:{phone}"`; bot резолвится из profile_id как в обычном пути (`main.py:230-231`).
- Intercept-примитив: `admin/router.py:853-860 _set_intercept` (грузит state, `intercepted=True`, `store.save`, `conv_store.set_intercepted`).

## TASK 1 — конфиг + флаг
`app/config.py`: `capture_manager_echo: bool = False` (env `CAPTURE_MANAGER_ECHO`). Добавить в `docker-compose.yml` `environment:` → `CAPTURE_MANAGER_ECHO: ${CAPTURE_MANAGER_ECHO:-false}`.

## TASK 2 — отслеживание своих исходящих id (анти-дубль)
Небольшой модуль `app/core/own_outbound.py`: множество недавних `provider_msg_id`, которые отправили МЫ (бот/панель), с коротким TTL (напр. 900с), потокобезопасно (как `_seen_wappi_ids` в main.py):
```python
def mark_own(provider_msg_id: str | None) -> None: ...   # запомнить наш исходящий id
def is_own(provider_msg_id: str | None) -> bool: ...      # это наш собственный echo?
```
Вызвать `mark_own(provider)` СРАЗУ после получения provider от отправки:
- `orchestrator._reply` — после `self.channel.send` (там же где `mark_message_status`).
- панель `admin/router.py send_message` — после `outbound.send_to_client`.
- (followup если шлёт — тоже).
Так наш echo будет распознан ещё до прихода webhook.

## TASK 3 — детектор echo (`app/channels/wappi.py`)
`is_outgoing_echo(raw) -> bool`: `wh_type=="incoming_message" and raw.get("is_me") is True and raw.get("type")!="reaction" and raw.get("chat_type","dialog")!="group"`. Плюс хелпер извлечь `text` (body), `chat_id`/`from`/`to`, `id` — переиспользовать существующий парсинг где можно.

## TASK 4 — ветка в webhook (`app/main.py`)
В цикле `/webhook/wappi`, ДО текущего `if not is_incoming_user_message(raw): continue`, добавить (обёрнуто в try/except, fail-safe):
```python
if settings.capture_manager_echo and is_outgoing_echo(raw):
    await _handle_manager_echo(raw, ...)   # см. ниже
    continue
```
`_handle_manager_echo`:
1. `event_id = raw.get("id")`; если `_seen_before(event_id)`: return (дедуп ретраев).
2. Если `is_own(event_id)`: return (это наш бот/панель — не менеджер).
3. Резолв bot из profile_id (как обычный путь), phone из `to` (клиент — это НЕ наш номер; в echo `from`=наш, `to`=клиент), `key=f"{bot_id}:{phone}"`. text = body; если пусто/медиа — можно пропустить или сохранить пометку.
4. `await panel.add_message(key, "manager", text, channel="whatsapp", bot_id=bot_id, status="sent", phone=phone)`.
5. Пометить перехват: тем же способом, что `_set_intercept` (state.intercepted=True + conv_store.set_intercepted) + `assigned_to` маркер (напр. "whatsapp"). Вынести общий хелпер, если удобно, чтобы не дублировать admin/router.
6. НЕ вызывать `orchestrator.handle` (никакого ре-энтри/цикла).

## TASK 5 — тесты (`tests/`, по образцу `test_wappi_contract.py`/`test_panel.py`)
- Флаг OFF (default): outgoing echo по-прежнему игнорируется (webhook как раньше) — регресс-защита.
- Флаг ON: echo с НЕизвестным id (менеджер печатал) → сохранён как `sender="manager"`, диалог `intercepted=True`.
- Флаг ON: echo, чей id помечен `mark_own` (наш бот/панель) → НЕ сохранён (дедуп).
- Флаг ON: повтор того же echo-event (ретрай) → не сохранён дважды (`_seen_before`).
- Входящее клиентское сообщение → обрабатывается как раньше (не сломать).
- Ошибка в обработке echo → не роняет обработку остальных сообщений.
- Не сломать существующие 218 тестов.

## TASK 6 — прогон
`PYTHONPATH=. pytest -q` — зелёное. Отчёт: файлы + pytest + поведение при флаге OFF/ON.
