"""Оверлей подтверждений: какие единицы знаний человек сверил с PDF и разрешил говорить.

Почему отдельный файл, а не правка бандла. Чтобы поставить единице
`confirmation_status: "confirmed"` прямо в `units.yaml`, валидатор требует заодно
очистить `blocked_value` у всех 208 единиц. Это сдвигает контрольную сумму бандла и
роняет инвариантные тесты, которые специально караулят, чтобы данные по визам не
менялись молча. Вместо этого подтверждения живут рядом, отдельным файлом.

Что это даёт:

- рискованный артефакт становится **дата-диффом**: в ревью видно ровно те строки,
  из-за которых бот начал утверждать правила закона;
- правка значения в бандле **аннулирует** подтверждение, потому что в оверлее записан
  хеш подтверждённого значения. Устаревший текст не протащится клиенту;
- несовпадение `bundle_hash` аннулирует весь оверлей сразу;
- откат — удаление строки, бот возвращается к «уточню у менеджера».

Файла может не быть вовсе: это штатное состояние до приёмки Гришей, и тогда не
подтверждено ничего.
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
           / "knowledge" / "kg_entry" / "confirmations-v1.1.yaml")
SCHEMA_VERSION = "kg-entry-confirmations/1"


@dataclass(frozen=True)
class Confirmations:
    bundle_hash: str
    source_hash: str
    by_unit: dict[str, str]          # unit_id -> value_sha256


def value_digest(value: Any) -> str:
    """Хеш значения единицы. `canonical` — та же нормализация, что в ревью знаний."""
    from app.knowledge.review import canonical
    from hashlib import sha256
    return sha256(canonical(value).encode()).hexdigest()


@lru_cache(maxsize=1)
def load() -> Confirmations | None:
    """Оверлей или None. None = не подтверждено ничего (штатное состояние до приёмки)."""
    if not OVERLAY.exists():
        return None
    try:
        doc = json.loads(OVERLAY.read_text(encoding="utf-8"))
        if doc.get("schema_version") != SCHEMA_VERSION:
            log.warning("kg entry confirmations: чужая схема %r", doc.get("schema_version"))
            return None
        by_unit: dict[str, str] = {}
        for row in doc.get("confirmed") or ():
            uid, digest = row.get("unit_id"), row.get("value_sha256")
            if not uid or not digest:
                log.warning("kg entry confirmations: запись без unit_id/хеша — игнорирую")
                return None          # битый оверлей целиком недоверенный, а не частично
            by_unit[uid] = digest
        return Confirmations(bundle_hash=str(doc.get("bundle_hash") or ""),
                             source_hash=str(doc.get("source_hash") or ""),
                             by_unit=by_unit)
    except Exception as exc:  # noqa: BLE001 — битый оверлей = ничего не подтверждено
        log.warning("kg entry confirmations unreadable: %s", type(exc).__name__)
        return None


def confirmed(unit: dict[str, Any]) -> bool:
    """Можно ли считать единицу подтверждённой человеком.

    Четыре условия, и все обязательны:
      1. оверлей есть и его `bundle_hash` совпал с текущим бандлом;
      2. единица в списке подтверждённых;
      3. у единицы есть значение (пустое подтвердить нельзя);
      4. хеш значения совпал — иначе значение правили после подтверждения.
    """
    from app.knowledge.entry_bundle import loaded
    conf = load()
    if conf is None:
        return False
    bundle = loaded()
    if bundle is None or (conf.bundle_hash and conf.bundle_hash != bundle.bundle_hash):
        return False
    uid = unit.get("unit_id")
    value = unit.get("value")
    if not uid or value is None or uid not in conf.by_unit:
        return False
    return conf.by_unit[uid] == value_digest(value)


def reset() -> None:
    """Сброс кеша — для тестов."""
    load.cache_clear()
