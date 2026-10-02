# Current work

- Updated: 2026-10-02
- Project/repository: Frunze Travel Bot
- Active task: M2 — админка на телефоне (программа «админка как CRM»)
- Branch / revision: `fix/tours-search-quality` / `dc9cb06`; прод на `c80fa32`
- Relevant handoff: ai/handoffs/2026-10-02-1900-deploy-m1-and-mobile-m2.md
- Status: PARTIALLY_READY — M1 выкачен и функционально проверен на проде; M2 реализован,
  1804 теста зелёные, независимого ревью и деплоя не было
- Next action: **Оплатить Wappi по туровым каналам — истекает 03.10 00:00 UTC**
  (`frunze_tours` 996707660009, `frunze_tours_sezim` 996554660009; `getvisa` до 23.10).
  Там же: пополнить OpenRouter — остаток $3.99 при `LLM_DAILY_BUDGET_USD=10`, то есть
  предохранителя нет, а трафик 01–02.10 удвоился. Из кода: ревью M2 и деплой по слову.
- Blockers / decisions: деплой и включение флагов требуют прямого слова Алана.
  NEEDS_HUMAN_DECISION: отказ от Bitrix в ноябре (ТЗ 01.10) — нужны слово, дата и план
  замещения потока Открытых линий.

For parallel workstreams, add one row per scope rather than overwriting another task's state.
Always verify the branch and revision before trusting a handoff.

| Scope | Task | Branch/revision | Handoff | Next action |
|---|---|---|---|---|
| Сторожа и наблюдаемость | Таймауты Wappi в `manager_sync` | прод `c80fa32` | 2026-10-02-1900 | Выкачено 02.10, в контейнере `wappi_messages_timeout_seconds=12.0`, за 15 минут 0 `ReadTimeout`. Остаются сутки наблюдения |
| Сторожа и наблюдаемость | Ложный совет QR при переподключении | прод `c80fa32` | 2026-09-29-2015-qr-advice-on-reconnect.md | Выкачено 02.10 с флагом OFF (на проде все три профиля `condition=ok`). Включение флага и вопрос о временной границе — по слову |
| Админка как CRM | M1: каркас + разделение туров/виз | прод `c80fa32` | 2026-10-01-1840-admin-shell-and-direction-split.md | DONE: ревью пройдено, выкачено и функционально проверено на проде 02.10. Флаг `admin_direction_split_enabled` остаётся OFF |
| Админка как CRM | M2: телефон (лист переписки, тач-перетаскивание, канбан лентой) | `dc9cb06` | 2026-10-02-1900-deploy-m1-and-mobile-m2.md | Независимое ревью по диффу `c80fa32..dc9cb06`, затем деплой по слову и приёмка с телефона |
| Админка как CRM | Долг M3: `/admin/inbox` отдаёт 2 МБ HTML и 6042 карточки одним ответом | — | — | Главный тормоз панели на телефоне; в M2 не брал |
| Сторожа и наблюдаемость | 402 Wappi неотличим от сетевого сбоя: сторож слеп, пока канал мёртв | — | — | ТЗ готово (черновик в плане), ждёт двух решений Алана |
| Протокол и документы | Подключение v4, профиль проекта | `8feec27` | 2026-09-29-1930-protocol-v4-onboarding.md | Закрыто 30.09: скилл `/protocol` переписан под v4 (соответствие S/M/B/C → LIGHT/STANDARD/CRITICAL, solo-ревью, статусы, handoff). Файл вне git — `.claude/skills/protocol/SKILL.md` |
| Расход LLM | Экономия `outcome_infer` (флаг ON с 28.09) | прод `5b04cc5` | — | Контрольный замер ~03.10, когда круг 2418 диалогов закроется |
| Битрикс и продажи | Встреча с Гришей 30.09 | — | — | Провести встречу, получить ответы на шесть вопросов (в т.ч. кто такой 155631) |
| Гигиена репозитория | `main` отстаёт на `643ed93` | — | — | Подтянуть `main` к рабочей ветке |
