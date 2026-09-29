# Current work

- Updated: 2026-09-29
- Project/repository: Frunze Travel Bot
- Active task: закрытие долгов — протокол подключён, ложный совет QR исправлен
- Branch / revision: `fix/tours-search-quality` / `f6bbc86`; прод на `5b04cc5` (отстаёт на 2 коммита)
- Relevant handoff: ai/handoffs/2026-09-29-2015-qr-advice-on-reconnect.md
- Status: PARTIALLY_READY — реализация и оба независимых ревью пройдены, релиз не выполнялся
- Next action: **Оплатить подписку Wappi по туровым каналам — истекает 01.10.2026**
  (`frunze_tours` 996707660009, `frunze_tours_sezim` 996554660009; `getvisa` до 23.10).
  Действие владельца, не код. Из кода: решение о выкатке `eef6fb0` и `f6bbc86`.
- Blockers / decisions: деплой и включение флагов требуют прямого слова Алана.
  NEEDS_HUMAN_DECISION: нужна ли жёсткая временная граница у совета «переподключается»
  (в `decide` она есть — 90 минут, у совета сейчас только словесная).

For parallel workstreams, add one row per scope rather than overwriting another task's state.
Always verify the branch and revision before trusting a handoff.

| Scope | Task | Branch/revision | Handoff | Next action |
|---|---|---|---|---|
| Сторожа и наблюдаемость | Таймауты Wappi в `manager_sync` | `eef6fb0` | — | Деплой по слову, затем сутки наблюдения за `ReadTimeout` и интервалом проб |
| Сторожа и наблюдаемость | Ложный совет QR при переподключении | `f6bbc86` | 2026-09-29-2015-qr-advice-on-reconnect.md | Деплой и включение флага по слову; решить вопрос о временной границе |
| Протокол и документы | Подключение v4, профиль проекта | `8feec27` | 2026-09-29-1930-protocol-v4-onboarding.md | Долг: скилл `/protocol` (вне git) не обновлён под v4 |
| Расход LLM | Экономия `outcome_infer` (флаг ON с 28.09) | прод `5b04cc5` | — | Контрольный замер ~03.10, когда круг 2418 диалогов закроется |
| Битрикс и продажи | Встреча с Гришей 30.09 | — | — | Провести встречу, получить ответы на шесть вопросов (в т.ч. кто такой 155631) |
| Гигиена репозитория | `main` отстаёт на `643ed93` | — | — | Подтянуть `main` к рабочей ветке |
