# СПЕКА для Codex — ссылки только из search_tours (анти-выдумка URL)

Автор: Claude (ревьюит). Исполнитель: Codex. Ветка: `feature/token-economy-phase1`. Не деплоить/не пушить/не коммитить.

Цель: бот даёт ссылки только на отели из `search_tours` и НИКОГДА не выдумывает URL (фейковые booking/тур-сайты и т.п.).

## Факты из кода (разведка)
- Единственный легитимный клиентский URL в системе — google-поиск отеля из `_hotel_link` (`app/integrations/tourvisor/client.py:417-423`): `https://www.google.com/search?q=<hotel+region+hotel>`. TourVisor реальных URL не отдаёт.
- Тул-результат `search_tours` (с строками `ссылка: https://www.google.com/search?q=...`) идёт в историю и **перефразируется LLM** (`runner.py:57-91`) → модель может выдумать/исказить URL.
- Других клиентских URL в коде НЕТ (офис/почта — текст, не ссылки; сайт/карты отсутствуют). → безопасно вырезать любой URL, кроме google-поиска.

## TASK 1 — промпт туров (`app/agent/prompts/tours.py`)
После строки «Никогда не выдумывай туры и цены — реальные варианты только из search_tours...» (`~tours.py:69`) добавить правило про ссылки:
«Ссылки на отели: используй ТОЛЬКО ссылки (https://www.google.com/search?q=...), пришедшие в результате search_tours. Никогда не сочиняй, не меняй и не достраивай URL сам. Если ссылки для отеля в результате не было — не давай ссылку вообще.»

## TASK 2 — бэкстоп в валидаторе (`app/agent/validator.py`)
Добавить (рядом с существующими паттернами ~стр. 32-42):
```python
_URL = re.compile(r"https?://[^\s>)\]]+", re.IGNORECASE)
_SAFE_URL_PREFIXES = (
    "https://www.google.com/search?q=",   # ссылки отелей из search_tours (client.py:423)
)

def _strip_unknown_urls(text: str) -> tuple[str, bool]:
    """Убрать любой URL, кроме безопасных префиксов (google-поиск отеля)."""
    stripped = False
    def _rep(m):
        nonlocal stripped
        url = m.group(0)
        if url.startswith(_SAFE_URL_PREFIXES):
            return url
        stripped = True
        return ""
    new = _URL.sub(_rep, text)
    if stripped:
        new = " ".join(new.split())
    return new, stripped
```
Встроить в `validate_reply` СРАЗУ после `strip_markdown` (до тур-дисклеймера и flight/visa-бэкстопов), для ВСЕХ воронок (funnel-параметр тут не нужен — легитимных не-google URL нет ни в одной воронке):
```python
    clean = strip_markdown(text)
    if clean != text.strip():
        violations.append("markdown")
    clean, url_stripped = _strip_unknown_urls(clean)
    if url_stripped:
        violations.append("invented_url_stripped")
```
Не сломать существующие правки (markdown, tours_price_disclaimer, flight/work-visa бэкстопы, лог-сигналы).

## TASK 3 — тесты (`tests/`)
- Ссылка отеля сохраняется: reply с `ссылка: https://www.google.com/search?q=Palmora+Lara+hotel` → URL НЕ удалён, нет флага.
- Выдуманный URL вырезается: `«Забронируйте тут: https://booking-fake.com/tour123»` → URL удалён, violation `invented_url_stripped`, остальной текст сохранён.
- Ответ без URL → не изменён.
- Не сломать текущие тесты валидатора/калибровки/tourvisor.

## TASK 4 — прогон
`PYTHONPATH=. pytest -q` — зелёное. Отчёт: файлы + результат pytest + до/после для 2 ключевых кейсов (google-ссылка сохранена, фейк вырезан).
