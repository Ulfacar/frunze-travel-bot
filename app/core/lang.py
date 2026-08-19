"""Определение языка клиента там, где ошибка стоит ответа не на том языке.

Пока нужен ровно один вопрос: пишет ли клиент по-английски. Правило «отвечай на языке
клиента» лежит в системном промпте с 06.07, но сам промпт и персона написаны по-русски —
и модель уезжала в русский: замер 19.08.2026 показал 18 русских ответов на 21 английское
сообщение за месяц.

Главная ловушка — считать латиницу английским. На туровом канале латиницей приходят
названия отелей («KIMEROS PARK HOLIDAY VILLAGE 5», «Antalya Kremlin Kristal Barut Sera») и
транслит («Assalamu alekum»), причём от русско- и кыргызоязычных клиентов. Поэтому судим
не по алфавиту, а по служебным словам, которые в названиях отелей не встречаются.
"""
from __future__ import annotations

import re

_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
_WORD_RE = re.compile(r"[a-z']+")

# Служебные и вопросительные слова — то, из чего состоит живая английская фраза. Намеренно
# БЕЗ «hotel», «resort», «room», «beach» и прочего словаря отелей: именно они делают
# ложные срабатывания на пересланных названиях.
_EN_STOPWORDS = frozenset("""
i you we they he she it me my your our their this that these those
is are am was were be been do does did can could would should will shall have has had
a an the and or but if so not no yes for with from about of to in on at by
what when where which who why how much many more please thanks thank sorry
need want help get send tell know make give take give price cost visa tour ticket flight
""".split())

# Голое приветствие — сильный сигнал само по себе: «Hi» или «Hello!» служебных слов не
# наберут, а язык клиента показывают однозначно.
_EN_GREETINGS = frozenset({"hello", "hi", "hey", "goodmorning", "goodevening", "goodafternoon"})

MIN_STOPWORD_HITS = 2


def looks_english(text: str) -> bool:
    """True, если клиент пишет по-английски. Консервативно: сомнение → False.

    Ложное «да» дороже ложного «нет»: ответить по-английски человеку, приславшему название
    отеля, — заметная ошибка, а лишний русский ответ англичанину модель ещё может выправить
    на следующем ходу, если он продолжит по-английски.
    """
    if not text or _CYRILLIC_RE.search(text):
        return False
    words = _WORD_RE.findall(text.lower())
    if not words:
        return False
    if len(words) <= 2 and any(w in _EN_GREETINGS for w in words):
        return True
    return sum(1 for w in words if w in _EN_STOPWORDS) >= MIN_STOPWORD_HITS
