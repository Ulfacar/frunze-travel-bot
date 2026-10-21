"""Загрузчик бандла знаний по въезду в КР для бота. Только чтение, fail-closed.

Зачем отдельный модуль. Весь остальной въездной слой (`app/domain/entry_*`,
`knowledge_*`) закрыт для бота по построению: `_authorize` запрещает актора `bot`, а
durable-операции требуют названного полного админа. Боту нужно ровно одно — прочитать
правила из файлов репозитория и ответить клиенту. Этот модуль читает бандл напрямую
через `preflight_bundle`, без БД, без актора и без политик: к нему просто нечего
применять.

Fail-closed. Любая беда с бандлом (нет файла, не сошёлся хеш, валидатор нашёл ошибку)
даёт `None`, а движок на `None` отвечает «не знаю» — то есть «уточню у менеджера».
Исключение в живой ход не вылетает никогда: иностранец не должен видеть ошибку вместо
ответа, а молчание бота здесь безопаснее догадки о законе.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = _ROOT / "knowledge" / "kg_entry" / "draft-v1.1"
SOURCE_PDF = _ROOT / "runs" / "specialist-source.pdf"

# Хеш исходного PDF ТЗ («Визы в Кыргызстан — база знаний и SOP, версия 1.1»). Нужен,
# когда самого PDF в образе нет: бандл всё равно проверяется на соответствие источнику.
SOURCE_SHA256 = "141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2"


@dataclass(frozen=True)
class Loaded:
    meta: dict[str, Any]
    countries: Any
    units: tuple[dict[str, Any], ...]
    bundle_hash: str
    index: Any                      # CountryRuleIndex

    def unit(self, unit_id: str) -> dict[str, Any] | None:
        for u in self.units:
            if u.get("unit_id") == unit_id:
                return u
        return None


@lru_cache(maxsize=1)
def loaded() -> Loaded | None:
    """Разобранный бандл или None. Кешируется на процесс: файлы в образе не меняются."""
    try:
        from app.knowledge.bundle import preflight_bundle, validate_bundle
        from app.knowledge.country_index import CountryRuleIndex
        from app.knowledge.validation import load_document

        if SOURCE_PDF.exists():
            report = preflight_bundle(BUNDLE_DIR, SOURCE_PDF)
        else:
            # PDF в образ не кладём — целостность держит прибитый хеш источника.
            report = validate_bundle(
                load_document(BUNDLE_DIR / "meta.yaml"),
                load_document(BUNDLE_DIR / "countries.yaml"),
                load_document(BUNDLE_DIR / "units.yaml"),
                source_hash=SOURCE_SHA256)
        if not report.ok or report.errors:
            log.warning("kg entry bundle invalid: %s", (report.errors or [])[:2])
            return None
        nb = report.normalized_bundle
        meta, countries, units = nb["meta"], nb["countries"], nb["units"]
        index = CountryRuleIndex(meta, countries, units,
                                 source_hash=meta.get("source_hash") or SOURCE_SHA256)
        return Loaded(meta=meta, countries=countries, units=tuple(units),
                      bundle_hash=report.bundle_hash, index=index)
    except Exception as exc:  # noqa: BLE001 — молчим и отдаём менеджеру, см. модульный docstring
        log.warning("kg entry bundle unavailable: %s", type(exc).__name__)
        return None


def reset() -> None:
    """Сброс кеша — для тестов."""
    loaded.cache_clear()
