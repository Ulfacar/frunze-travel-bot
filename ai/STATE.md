# Current work

- Updated: 2026-10-01
- Project/repository: Frunze Travel Bot
- Active task: M1 — каркас админки и разделение туров/виз (программа «админка как CRM»)
- Branch / revision: `fix/tours-search-quality` / рабочее дерево, не закоммичено; прод на `5b04cc5`
- Relevant handoff: ai/handoffs/2026-10-01-1840-admin-shell-and-direction-split.md
- Status: PARTIALLY_READY — M1 реализован, 1787 тестов зелёные, ревью не было, деплоя не было
- Next action: **Оплатить Wappi по туровым каналам на полный срок — оплачено только до 03.10.2026**
  (`frunze_tours` 996707660009, `frunze_tours_sezim` 996554660009; `getvisa` до 23.10). 01.10
  каналы уже стояли 6,5 часов на `402 Profile not paid`. Из кода: ревью M1 и решение о
  визуальном языке (синий или бирюза из макетов) — правится только в `base.html`.
- Blockers / decisions: деплой и включение флагов требуют прямого слова Алана.
  NEEDS_HUMAN_DECISION: нужна ли жёсткая временная граница у совета «переподключается»
  (в `decide` она есть — 90 минут, у совета сейчас только словесная).

For parallel workstreams, add one row per scope rather than overwriting another task's state.
Always verify the branch and revision before trusting a handoff.

| Scope | Task | Branch/revision | Handoff | Next action |
|---|---|---|---|---|
| Сторожа и наблюдаемость | Таймауты Wappi в `manager_sync` | `eef6fb0` | — | Деплой по слову, затем сутки наблюдения за `ReadTimeout` и интервалом проб |
| Сторожа и наблюдаемость | Ложный совет QR при переподключении | `f6bbc86` | 2026-09-29-2015-qr-advice-on-reconnect.md | Деплой и включение флага по слову; решить вопрос о временной границе |
| Админка как CRM | M1: каркас + разделение туров/виз | рабочее дерево | 2026-10-01-1840-admin-shell-and-direction-split.md | Ревью по диффу, затем M2 (телефон) |
| Сторожа и наблюдаемость | 402 Wappi неотличим от сетевого сбоя: сторож слеп, пока канал мёртв | — | — | ТЗ готово (черновик в плане), ждёт двух решений Алана |
| Протокол и документы | Подключение v4, профиль проекта | `8feec27` | 2026-09-29-1930-protocol-v4-onboarding.md | Закрыто 30.09: скилл `/protocol` переписан под v4 (соответствие S/M/B/C → LIGHT/STANDARD/CRITICAL, solo-ревью, статусы, handoff). Файл вне git — `.claude/skills/protocol/SKILL.md` |
| Расход LLM | Экономия `outcome_infer` (флаг ON с 28.09) | прод `5b04cc5` | — | Контрольный замер ~03.10, когда круг 2418 диалогов закроется |
| Битрикс и продажи | Встреча с Гришей 30.09 | — | — | Провести встречу, получить ответы на шесть вопросов (в т.ч. кто такой 155631) |
| Гигиена репозитория | `main` отстаёт на `643ed93` | — | — | Подтянуть `main` к рабочей ветке |
