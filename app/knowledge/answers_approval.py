"""Оверлей одобрения кусков базы знаний: что именно человек разрешил произносить.

Устроен точно так же, как `app/knowledge/entry_confirmations.py` для единиц знаний, и
по той же причине: рискованный артефакт должен быть дата-диффом, а не кодом. В ревью
видно ровно те строки, из-за которых бот начал утверждать клиенту норму чужого закона.

Почему это вообще нужно именно здесь. Движок поиска (`app/knowledge/retrieval.py`) по
своему контракту не импортирует ни БД, ни настройки, и `_authorize`, запрещающий актора
`bot`, в нём не вызывается — единственная защита поиска сегодня это HTTP-гейт админки.
Значит подключение поиска к боту ничего не ослабляет, но и никаких гарантий доменного
слоя не получает. **Этот оверлей и есть замена отсутствующей авторизации:** именованный
человек подписывает конкретные куски, бот сам себе ничего разрешить не может.

Что даёт такая форма:

- **правка текста аннулирует одобрение** — в строке записан хеш одобренного текста;
- **правка корпуса или источника аннулирует оверлей целиком** — записаны хеши обоих;
- **нет файла — одобрено ничего**, и это штатное состояние до приёмки: бот тогда
  отвечает «уточнит специалист» и передаёт человеку (решение владельца 22.10);
- **битый оверлей недоверенный целиком**, а не частично: пропущенный хеш в одной строке
  не должен оставлять в силе остальные.

Кеш: читается один раз на процесс, сбрасывается `reset()`. Как и у подтверждений
единиц, инвалидация — рестарт: оверлей меняется в момент приёмки, а не на каждом ходе.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

OVERLAY = (Path(__file__).resolve().parents[2]
           / "knowledge" / "kg_entry" / "answers-approved-v1.1.yaml")
SCHEMA_VERSION = "kg-entry-answers-approved/1"

# Поля, без которых строка не считается подписанной человеком.
REQUIRED_ROW_FIELDS = ("piece_id", "text_sha256", "basis", "approved_by",
                       "checked_by", "approved_at")


@dataclass(frozen=True)
class Approvals:
    corpus_hash: str
    source_hash: str
    by_piece: dict[str, str]          # piece_id -> text_sha256


@lru_cache(maxsize=1)
def load() -> Approvals | None:
    """Оверлей или None. None = одобрено ничего (штатное состояние до приёмки)."""
    if not OVERLAY.exists():
        return None
    try:
        doc = json.loads(OVERLAY.read_text(encoding="utf-8"))
        if doc.get("schema_version") != SCHEMA_VERSION:
            log.warning("kg answers approval: чужая схема %r", doc.get("schema_version"))
            return None
        corpus_hash = str(doc.get("corpus_hash") or "")
        source_hash = str(doc.get("source_hash") or "")
        if not corpus_hash or not source_hash:
            # Привязка обязательна: хеш текста защищает от правки текста, но не от
            # подмены корпуса или источника целиком.
            log.warning("kg answers approval: оверлей без привязки к корпусу или PDF")
            return None
        by_piece: dict[str, str] = {}
        for row in doc.get("approved") or ():
            if any(not row.get(field) for field in REQUIRED_ROW_FIELDS):
                log.warning("kg answers approval: неполная строка — оверлей недоверенный")
                return None
            by_piece[str(row["piece_id"])] = str(row["text_sha256"])
        return Approvals(corpus_hash=corpus_hash, source_hash=source_hash,
                         by_piece=by_piece)
    except Exception as exc:  # noqa: BLE001 — битый оверлей = одобрено ничего
        log.warning("kg answers approval unreadable: %s", type(exc).__name__)
        return None


def approved(piece: dict[str, Any], *, corpus_hash: str, source_hash: str) -> bool:
    """Можно ли произнести этот кусок клиенту.

    Пять условий, и все обязательны:
      1. оверлей есть;
      2. его привязка совпала с текущим корпусом и исходным PDF;
      3. кусок в списке одобренных;
      4. хеш текста совпал — иначе текст правили после одобрения;
      5. кусок подлежит одобрению: не несёт метку `[РЕШЕНИЕ]` (её ТЗ запрещает
         озвучивать безусловно) и не содержит сумм (решение владельца: бот цен не
         называет, а сумма в контексте модели рано или поздно будет произнесена).
    """
    overlay = load()
    if overlay is None:
        return False
    if overlay.corpus_hash != corpus_hash or overlay.source_hash != source_hash:
        return False
    if not piece.get("approvable", piece.get("answerable")):
        # `approvable` строже: кроме метки РЕШЕНИЕ исключает всё, где есть деньги.
        return False
    piece_id = str(piece.get("piece_id") or "")
    expected = overlay.by_piece.get(piece_id)
    return bool(expected) and expected == str(piece.get("text_sha256") or "")


def reset() -> None:
    """Сброс кеша — для тестов и разовых скриптов.

    Терпим к подмене `load`: в тестах его заменяют простой функцией без кеша, и
    уборка не должна падать из-за этого.
    """
    getattr(load, "cache_clear", lambda: None)()
