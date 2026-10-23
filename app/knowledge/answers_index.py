"""Индекс отвечаемых кусков базы знаний — тот, который спрашивает бот.

Зачем отдельно от `app/knowledge/retrieval.py`. Тот индекс сделан для ревью человеком:
он ищет по РАЗДЕЛАМ, принудительно помечает выдачу `may_quote=False` и при каждом вызове
заново пересобирает корпус из исходного Markdown (замер: 79 мс против 0.5 мс на сам
поиск). Для админки это нормально, для хода бота — нет.

Здесь то же лексическое ранжирование, но:

* ищем по кускам (`app/knowledge/answerable.pieces`), а не по разделам: раздел бывает
  4133 символа, медианный кусок — 163;
* индекс строится один раз на процесс и кешируется;
* **отдаём только одобренные куски.** Право произнести даёт оверлей, подписанный
  человеком (`app/knowledge/answers_approval.py`). Нет оверлея — выдача пуста, и бот
  передаёт человеку. Это решение владельца: отвечать из общих знаний модели запрещено.

Токенизатор и формулу ранжирования берём из `retrieval.py`, а не копируем: расхождение
двух реализаций означало бы, что админка и бот ищут по-разному, и проверка человеком
перестала бы говорить что-либо о поведении бота.
"""
from __future__ import annotations

import logging
from collections import Counter
from functools import lru_cache
import math
from typing import Any

# Белый список полей ремня валидатора — больше кусок открыть не может.
BELT_FIELDS = frozenset({"regime", "stay_limit", "registration", "unified_permit"})


class AnswersIndex:
    """Лексический индекс по кускам. Ни БД, ни сети, ни LLM."""

    def __init__(self, pieces: list[dict[str, Any]], *, sections: Any,
                 corpus_hash: str, source_hash: str) -> None:
        from app.knowledge.retrieval import _tokens

        self.corpus_hash = corpus_hash
        self.source_hash = source_hash
        # Индекс разделов — первый этап поиска. Держим его, а не пересоздаём: его
        # сборка стоит ~80 мс, а ход бота делает до шести витков.
        self._sections = sections
        self._pieces = {p["piece_id"]: p for p in pieces}
        self._counts = {key: Counter(_tokens(p["text"]))
                        for key, p in self._pieces.items()}
        self._df: Counter[str] = Counter(
            token for counts in self._counts.values() for token in counts)
        self._lengths = {key: sum(counts.values())
                         for key, counts in self._counts.items()}
        self._average = (sum(self._lengths.values()) / max(len(self._lengths), 1)) or 1.0
        self._by_section: dict[str, list[str]] = {}
        for key, piece in self._pieces.items():
            self._by_section.setdefault(str(piece.get("section") or ""), []).append(key)

    def __len__(self) -> int:
        return len(self._pieces)

    def _score(self, keys, terms) -> list[tuple[float, str]]:
        """BM25 по кускам из заданного набора."""
        total = max(len(self._pieces), 1)
        ranked: list[tuple[float, str]] = []
        for key in keys:
            counts = self._counts[key]
            if not self._pieces[key].get("answerable"):
                continue           # кусок с меткой РЕШЕНИЕ не выдаём никогда
            score = 0.0
            for term in terms:
                freq = counts.get(term, 0)
                if not freq:
                    continue
                document_frequency = self._df[term]
                idf = math.log(1 + (total - document_frequency + .5)
                               / (document_frequency + .5))
                length = self._lengths[key] / max(self._average, 1)
                score += idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * length))
            if score > 0:
                ranked.append((round(score, 8), key))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return ranked

    def search(self, query: str, *, limit: int = 4,
               approved_only: bool = True) -> list[dict[str, Any]]:
        """Куски по запросу. Два этапа: сначала раздел, потом кусок внутри раздела.

        Почему два этапа, а не прямой поиск по кускам. Замерено на наборе
        `scenarios/kg_knowledge_queries.json`: прямой поиск по кускам давал по русским
        вопросам 70% попаданий в top-3, поиск по РАЗДЕЛАМ — 90%. Причина в статистике:
        медианный кусок 163 символа, и BM25 по такой короткой записи шумит, а раздел
        даёт устойчивое распределение слов. Поэтому тему определяет проверенный
        индекс разделов (`app/knowledge/retrieval.py`, ~50 тестов), а куски нужны
        только чтобы достать из найденного раздела ровно то, что отвечает на вопрос,
        и не тащить в контекст модели 4133 символа целого раздела.

        `approved_only=False` существует для замера полноты поиска: так видно качество
        ранжирования отдельно от состава одобренного человеком. В рантайме всегда True.
        """
        from app.knowledge.answers_lexicon import expand
        from app.knowledge.retrieval import RetrievalError, _tokens

        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            return []
        if type(limit) is not int or not 1 <= limit <= 10:
            return []
        # Запрос дополняем русскими эквивалентами: база русская, а половина клиентов
        # пишет по-английски. Без этого по английским вопросам было 20% попаданий в
        # top-3 против 60% по русским.
        expanded = expand(query)[:200]
        terms = list(dict.fromkeys(_tokens(expanded)))
        if not terms or len(terms) > 40:
            return []

        try:
            found = self._sections.search(expanded, limit=min(limit + 2, 10))
        except RetrievalError:
            return []

        out: list[dict[str, Any]] = []
        for item in found["results"]:
            section = str(item["fragment"].get("section") or "")
            for score, key in self._score(self._by_section.get(section, ()), terms):
                piece = self._pieces[key]
                if approved_only:
                    from app.knowledge import answers_approval
                    if not answers_approval.approved(
                            piece, corpus_hash=self.corpus_hash,
                            source_hash=self.source_hash):
                        continue
                out.append(dict(piece, score=score))
                break              # не больше одного куска на раздел
            if len(out) >= limit:
                break
        return out


@lru_cache(maxsize=1)
def load() -> AnswersIndex | None:
    """Индекс или None. None — поиск недоступен, бот передаёт человеку.

    Кешируется на процесс: пересборка стоит ~80 мс, а ход бота делает до шести витков.
    Сбрасывается только через `reset()` (тесты, разовые скрипты).
    """
    try:
        from app.knowledge.answerable import pieces
        from app.knowledge.retrieval import load_review_index

        index = load_review_index()
        collected: list[dict[str, Any]] = []
        corpus_hash = ""
        for fragment_id in sorted(index._fragments):          # noqa: SLF001
            fragment = index.fragment(fragment_id)
            corpus_hash = corpus_hash or str(
                fragment.get("source_markdown_lf_sha256") or "")
            collected.extend(pieces(fragment))
        if not collected:
            return None
        return AnswersIndex(collected, sections=index, corpus_hash=corpus_hash,
                            source_hash=index.source_hash)
    except Exception:  # noqa: BLE001 — нет базы, значит бот отдаёт человеку
        # Логируем обязательно: иначе сбой сборки образа выглядит как «бот просто
        # передаёт человеку» при зелёном /health, и причину не найти.
        logging.getLogger(__name__).warning("kg answers index unavailable",
                                            exc_info=True)
        return None


def reset() -> None:
    """Сброс кеша — для тестов и разовых скриптов.

    Терпим к подмене `load`: в тестах его заменяют простой функцией без кеша.
    """
    getattr(load, "cache_clear", lambda: None)()
