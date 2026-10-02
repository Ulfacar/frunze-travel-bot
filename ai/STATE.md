# Current work

- Updated: 2026-10-02
- Project/repository: Frunze Travel Bot
- Active task: включение флагов по одному после деплоя 02.10
- Branch / revision: `fix/tours-search-quality` / `41c8e12`; **прод на `41c8e12`**
- Relevant handoff: ai/handoffs/2026-10-02-2200-deploy-three-flags-off.md
- Status: PARTIALLY_READY — три изменения на проде и функционально проверены (флаги OFF,
  инбокс отдаёт прежние 1016 карточек, правила телефона доехали, приём живой). Поведение с
  включёнными флагами не наблюдалось
- Next action: **Включать флаги по одному с замером между ними**, по возрастанию риска:
  `admin_inbox_limit_enabled` → `admin_direction_split_enabled` → `tour_flights_enabled`
  (последний виден клиенту и добавляет 18–22 с к ответу). Вне кода: Wappi продлён только
  до 06.10 — взять на срок.
- Blockers / decisions: включение каждого флага — отдельное слово Алана. BLOCKED: ссылка
  `tourcart` (запрос в поддержку TourVisor отправлен 02.10). NEEDS_HUMAN_DECISION: отказ
  от Bitrix в ноябре (ТЗ 01.10).

For parallel workstreams, add one row per scope rather than overwriting another task's state.
Always verify the branch and revision before trusting a handoff.

| Scope | Task | Branch/revision | Handoff | Next action |
|---|---|---|---|---|
| Сторожа и наблюдаемость | Таймауты Wappi в `manager_sync` | прод `c80fa32` | 2026-10-02-1900 | Выкачено 02.10, в контейнере `wappi_messages_timeout_seconds=12.0`, за 15 минут 0 `ReadTimeout`. Остаются сутки наблюдения |
| Сторожа и наблюдаемость | Ложный совет QR при переподключении | прод `c80fa32` | 2026-09-29-2015-qr-advice-on-reconnect.md | Выкачено 02.10 с флагом OFF (на проде все три профиля `condition=ok`). Включение флага и вопрос о временной границе — по слову |
| Админка как CRM | M1: каркас + разделение туров/виз | прод `c80fa32` | 2026-10-01-1840-admin-shell-and-direction-split.md | DONE: ревью пройдено, выкачено и функционально проверено на проде 02.10. Флаг `admin_direction_split_enabled` остаётся OFF |
| Админка как CRM | M2: телефон | прод `41c8e12` | 2026-10-02-2200-deploy-three-flags-off.md | Выкачено 02.10, правила проверены в боевой странице. Осталась приёмка с настоящего телефона менеджера |
| Туры и подача | Рейсы в карточке (`tour_flights_enabled` OFF) | прод `41c8e12` | 2026-10-02-2200-deploy-three-flags-off.md | Выкачено; включать последним — видит клиент, +18–22 с к ответу. После включения показать живую подборку из `messages` и `quota.status()` |
| Туры и подача | Короткая ссылка `tourcart` | — | то же | BLOCKED: отправить запрос в поддержку TourVisor, текст готов в ТЗ |
| Туры и подача | Долг: страница `/t/` не показывает рейсы, хотя данные уже есть | — | то же | Взять после ответа TourVisor |
| Админка как CRM | Инбокс страницей (`admin_inbox_limit_enabled` OFF) | прод `41c8e12` | 2026-10-02-2200-deploy-three-flags-off.md | Выкачено; при OFF прод отдаёт прежние 1016 карточек, числа сошлись со `stats`. Включать первым |
| Сторожа и наблюдаемость | 402 Wappi неотличим от сетевого сбоя: сторож слеп, пока канал мёртв | — | — | ТЗ готово (черновик в плане), ждёт двух решений Алана |
| Протокол и документы | Подключение v4, профиль проекта | `8feec27` | 2026-09-29-1930-protocol-v4-onboarding.md | Закрыто 30.09: скилл `/protocol` переписан под v4 (соответствие S/M/B/C → LIGHT/STANDARD/CRITICAL, solo-ревью, статусы, handoff). Файл вне git — `.claude/skills/protocol/SKILL.md` |
| Расход LLM | Экономия `outcome_infer` (флаг ON с 28.09) | прод `5b04cc5` | — | Контрольный замер ~03.10, когда круг 2418 диалогов закроется |
| Битрикс и продажи | Встреча с Гришей 30.09 | — | — | Провести встречу, получить ответы на шесть вопросов (в т.ч. кто такой 155631) |
| Гигиена репозитория | `main` отстаёт на `643ed93` | — | — | Подтянуть `main` к рабочей ветке |
