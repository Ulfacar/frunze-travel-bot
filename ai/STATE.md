# Current work

- Updated: 2026-09-29
- Project/repository: Frunze Travel Bot
- Active task: Подключение протокола v4 и описание проекта (`ai/PROJECT.md`)
- Branch / revision: `fix/tours-search-quality` / `eef6fb0`; прод на `5b04cc5`
- Relevant handoff: ai/handoffs/2026-09-29-1930-protocol-v4-onboarding.md
- Status: DONE (подключение), задача владельца в этой сессии не поставлена
- Next action: **Оплатить подписку Wappi по туровым каналам — истекает 01.10.2026**
  (`frunze_tours` 996707660009 и `frunze_tours_sezim` 996554660009; `getvisa` до 23.10).
  Это действие владельца, не код. Из кода следующий кандидат — выкатить на прод коммит
  `eef6fb0` (таймауты Wappi в `manager_sync`) по прямому слову Алана и сделать функциональную
  проверку в боевом контейнере.
- Blockers / decisions: деплой не входил в задачу и не выполнялся. Политика хранения и удаления
  персональных данных не определена (UNKNOWN) — вопрос к владельцам.

For parallel workstreams, add one row per scope rather than overwriting another task's state.
Always verify the branch and revision before trusting a handoff.

| Scope | Task | Branch/revision | Handoff | Next action |
|---|---|---|---|---|
| Протокол и документы | Подключение v4, профиль проекта | `fix/tours-search-quality` / `eef6fb0` | 2026-09-29-1930-protocol-v4-onboarding.md | Решить судьбу `ai-protocol/` (v2 как историческая справка) |
| Сторожа и наблюдаемость | Таймауты Wappi в `manager_sync` | `fix/tours-search-quality` / `eef6fb0` | — | Деплой по слову Алана, затем сутки наблюдения: число `ReadTimeout` и интервал проб `wappi_health` |
| Расход LLM | Экономия `outcome_infer` (флаг ON с 28.09) | прод `5b04cc5` | — | Контрольный замер ~03.10, когда круг 2418 диалогов закроется |
| Битрикс и продажи | Материал к встрече с Гришей 30.09 | — | — | Провести встречу, получить ответы на шесть вопросов (в т.ч. кто такой сотрудник 155631) |
