# Разбор: «бот молчит» — диагностика и архитектура (2026-06-23)

Лог рабочей сессии: почему тур-бот не отвечал, как это нашли, и сопутствующее
уточнение архитектуры + чек-лист включения Bitrix (фаза 2).

---

## 1. Жалоба

- Номер **996707660009 (TRAVEL / тур-бот)** молчит.
- Номер **996706660009 (GetVisa / виза-бот)** работает («только что тестил»).

## 2. Что проверили (по шагам)

Доступ к проду: `ssh root@62.171.185.155`, проект в `/root/frunze-travel`.

1. **Конфиг ботов** (`prod.env` → `BOTS`): два профиля Wappi
   - `frunze_tours` → profile `02a4708d-ec6c`, номер 996707660009
   - `getvisa` → profile `2f099bc3-478d`, номер 996706660009
2. **Логи приложения**: за 24ч **0 событий** по тур-профилю `02a4708d`, при этом
   **нет** предупреждений «без сопоставленного бота». Шлёт только `2f099bc3` (visa).
3. **Статус профилей в Wappi** (`/api/sync/get/status`): оба **авторизованы**,
   оплачены, у обоих верный `webhook_url = https://frunzetravel.kg/webhook/wappi`.
   → конфиг Wappi не виноват.
4. **Живой захват логов** во время теста: вебхуки **приходят** (`POST /webhook/wappi`
   200 OK), но **ни одного ответа бота** и **ни одной ошибки маршрутизации**.
5. **Postgres** (`conversations`): всего один диалог — `user_id=996500494009`,
   `bot_id=getvisa`, `funnel=tours`(!), `stage=manager`, **`intercepted=true`**.
6. **Redis** (`frunze:dialog:996500494009`): полный визовый диалог (клиент «Азамат»),
   `stage=manager`, **`intercepted=true`** — бот вызвал `handoff_to_manager` и замолк.
7. **Wappi chats тур-профиля**: чат с тем же `996500494009` существует — то есть
   человек писал и на тур-номер, Wappi принял.

## 3. Корневая причина

**Состояние диалога и карточка панели ключевались по `user_id` (номеру телефона)
без привязки к боту.**

- Redis-ключ: `frunze:dialog:<user_id>` (`app/core/state.py:66`)
- Postgres: `conversations.user_id`
- Гейт в оркестраторе: `app/core/orchestrator.py:68` → `if state.intercepted: return`

Один тест-номер `996500494009` прошёл визовый диалог → `handoff_to_manager` →
`intercepted=true`. Так как состояние общее на номер, **тот же флаг заглушил и
тур-бота**, когда с этого номера писали на тур-номер. Тур-бот ловил сообщение,
логировал его (поэтому `funnel` в Postgres переписался на `tours`), но молчал.

**Тур-бот не был сломан** — это коллизия общего состояния по номеру. Усугублялось
тем, что менеджер реально отвечал в чат вручную (видно как `sender=manager`).

## 4. Что сделали

- **Немедленный анфикс (прод):** сбросили застрявший тест-диалог
  - `redis-cli DEL frunze:dialog:996500494009`
  - `UPDATE conversations SET intercepted=false, stage='greeting', assigned_to='' WHERE user_id='996500494009';`
  - → бот снова отвечает с этого номера.
- **Правильный фикс (код, git main, 2026-06-24):** диалог/состояние теперь
  ключуются по **`<bot_id>:<phone>`** — состояние и карточка раздельные на каждого
  бота, номер для показа в `conversations.phone`. Перехват одного бота больше **не
  глушит** другой. Тест: `tests/test_panel.py::test_conversations_separated_by_bot`.
  (См. память проекта `dialog-state-per-phone`.)

## 5. Уточнение архитектуры (как устроено на самом деле)

Бот — **центр (хаб)**, а не звено в линейной цепочке. Bitrix и админка висят на
боте параллельно.

```
Клиент WhatsApp ──Wappi webhook──► БОТ (оркестратор + AI, воронки тур/виза/билеты)
                                     ├──► TourVisor              (поиск туров)
                                     ├──► CRM (get_crm)          (лид/сделка)
                                     └──► Postgres conversations ──► Админка (менеджеры:
                                                                      перехват / ответ)

Отдельно:  Wappi ──СВОЯ интеграция──► Bitrix24   (это она создаёт «Лид #181771»)
```

Опора в коде:
- TourVisor — инструмент бота: `app/funnels/tours.py:30,45`, `app/agent/runner.py:31,87`
- CRM зовётся ботом: `app/funnels/tours.py:48-59`, `app/agent/runner.py:85,95,101,128,173`
- Админка — отдельный слой: лог пишется в `orchestrator.py:108-148`, перехват
  читается как стоп-флаг `orchestrator.py:68`. В цепочку «бот→CRM» админка не входит.
- Канал-вход: `app/main.py` `wappi_webhook` → `orchestrator.handle`

**Важная поправка:** на проде `CRM_BACKEND=postgres` → бот пишет сделки в свою
таблицу `deals` в Postgres, **а в Bitrix НЕ пишет**. Код `Bitrix24Crm` есть, но не
включён. Лиды в Bitrix сейчас создаёт **встроенная интеграция Wappi↔Bitrix**, не наш бот.

## 6. Чек-лист включения Bitrix (фаза 2)

`Bitrix24Crm` (`app/integrations/crm/bitrix24.py`) реализован полностью:

| Метод | Bitrix REST |
|---|---|
| `create_lead` | `crm.deal.add` |
| `update_stage` | `crm.deal.update` |
| `add_note` | `crm.timeline.comment.add` |
| `send_message` | `imbot.message.add` |

Что нужно для переключения (сейчас в `prod.env` отсутствует):

1. `CRM_BACKEND=bitrix24` (сейчас `postgres`)
2. `BITRIX24_WEBHOOK_URL` — входящий вебхук портала `getvisakg.bitrix24.kz`
   (права `crm.*`, `imbot.*`). **Без него вызовы упадут.**
3. `BITRIX_CATEGORY_BY_FUNNEL={"tours":"<id>","visa":"<id>","tickets":"<id>"}`
4. `BITRIX_STAGE_MAP={"office_consultation":"...","manager_handoff":"...","visa_scoring":"..."}`
   — ключи ровно те, что шлёт бот.

Пункты 2–4 — данные от заказчика (реальные ID воронок/стадий из портала).
Деградация мягкая: при пустых картах сделка идёт в воронку по умолчанию, сдвиг
стадии пропускается с warning — бот не падает.

**⚠ Риск двойных лидов:** при включении нашего бэкенда на клиента будут создаваться
ДВЕ сделки (Wappi-интеграция + наш бот). Перед включением — либо отключить
Bitrix-интеграцию в кабинете Wappi (оставить Wappi только транспортом WhatsApp),
либо не включать наш бэкенд.

## 7. Полезные команды (прод)

```bash
ssh root@62.171.185.155
cd /root/frunze-travel

# логи приложения
docker compose logs --since 1h --timestamps app | grep -iE 'wappi|profile|send to'

# живой захват
docker compose logs --since 1s --follow app | grep --line-buffered 'webhook/wappi'

# состояние диалога
docker compose exec redis redis-cli GET 'frunze:dialog:<phone>'

# карточки/сообщения
docker compose exec db psql -U postgres -d frunze -c "SELECT * FROM conversations ORDER BY last_message_at DESC LIMIT 10;"

# статус профиля Wappi
curl -s -H "Authorization: $WAPPI_TOKEN" "https://wappi.pro/api/sync/get/status?profile_id=<id>"
```
