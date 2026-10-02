# Current work

- Updated: 2026-10-02
- Project/repository: Frunze Travel Bot
- Active task: рейсы в карточке тура (просьба Гриши 02.10)
- Branch / revision: `fix/tours-search-quality` / `596ae70`; прод на `c80fa32`
- Relevant handoff: ai/handoffs/2026-10-02-2130-tour-flights-and-tvcard.md
- Status: PARTIALLY_READY — рейсы сделаны за флагом OFF, 1820 тестов, замер на живых
  данных 15.2 с; ревью и деплоя не было. Ссылка `tourcart` — BLOCKED на ответе TourVisor
- Next action: **Оплатить Wappi по туровым каналам и пополнить OpenRouter** (остаток $3.99
  при `LLM_DAILY_BUDGET_USD=10`, трафик удвоился). Отправить запрос в поддержку TourVisor —
  готовый текст в `docs/task-tour-flights-and-tvcard-0210.md`. Из кода: ревью и деплой по слову.
- Blockers / decisions: деплой и включение флагов требуют прямого слова Алана.
  BLOCKED: короткая ссылка `tourcart.ru/?tvcard=…` — функция кабинета TourVisor, в XML-шлюзе
  методов нет (11 кандидатов → 404, `cart.php` → «Client Zero» на любые параметры), новый
  REST за заглушкой и без токена. NEEDS_HUMAN_DECISION: отказ от Bitrix в ноябре (ТЗ 01.10).

For parallel workstreams, add one row per scope rather than overwriting another task's state.
Always verify the branch and revision before trusting a handoff.

| Scope | Task | Branch/revision | Handoff | Next action |
|---|---|---|---|---|
| Сторожа и наблюдаемость | Таймауты Wappi в `manager_sync` | прод `c80fa32` | 2026-10-02-1900 | Выкачено 02.10, в контейнере `wappi_messages_timeout_seconds=12.0`, за 15 минут 0 `ReadTimeout`. Остаются сутки наблюдения |
| Сторожа и наблюдаемость | Ложный совет QR при переподключении | прод `c80fa32` | 2026-09-29-2015-qr-advice-on-reconnect.md | Выкачено 02.10 с флагом OFF (на проде все три профиля `condition=ok`). Включение флага и вопрос о временной границе — по слову |
| Админка как CRM | M1: каркас + разделение туров/виз | прод `c80fa32` | 2026-10-01-1840-admin-shell-and-direction-split.md | DONE: ревью пройдено, выкачено и функционально проверено на проде 02.10. Флаг `admin_direction_split_enabled` остаётся OFF |
| Админка как CRM | M2: телефон (лист переписки, тач-перетаскивание, канбан лентой) | `dc9cb06` | 2026-10-02-1900-deploy-m1-and-mobile-m2.md | Независимое ревью по диффу `c80fa32..dc9cb06`, затем деплой по слову и приёмка с телефона |
| Туры и подача | Рейсы в карточке, как у операторов (флаг `tour_flights_enabled` OFF) | `596ae70` | 2026-10-02-2130-tour-flights-and-tvcard.md | Ревью по диффу `c80fa32..596ae70`, деплой по слову, затем включить флаг и показать живую подборку из `messages` |
| Туры и подача | Короткая ссылка `tourcart` | — | то же | BLOCKED: отправить запрос в поддержку TourVisor, текст готов в ТЗ |
| Туры и подача | Долг: страница `/t/` не показывает рейсы, хотя данные уже есть | — | то же | Взять после ответа TourVisor |
| Админка как CRM | Долг M3: `/admin/inbox` отдаёт 2 МБ HTML и 6042 карточки одним ответом | — | — | Главный тормоз панели на телефоне; в M2 не брал |
| Сторожа и наблюдаемость | 402 Wappi неотличим от сетевого сбоя: сторож слеп, пока канал мёртв | — | — | ТЗ готово (черновик в плане), ждёт двух решений Алана |
| Протокол и документы | Подключение v4, профиль проекта | `8feec27` | 2026-09-29-1930-protocol-v4-onboarding.md | Закрыто 30.09: скилл `/protocol` переписан под v4 (соответствие S/M/B/C → LIGHT/STANDARD/CRITICAL, solo-ревью, статусы, handoff). Файл вне git — `.claude/skills/protocol/SKILL.md` |
| Расход LLM | Экономия `outcome_infer` (флаг ON с 28.09) | прод `5b04cc5` | — | Контрольный замер ~03.10, когда круг 2418 диалогов закроется |
| Битрикс и продажи | Встреча с Гришей 30.09 | — | — | Провести встречу, получить ответы на шесть вопросов (в т.ч. кто такой 155631) |
| Гигиена репозитория | `main` отстаёт на `643ed93` | — | — | Подтянуть `main` к рабочей ветке |
