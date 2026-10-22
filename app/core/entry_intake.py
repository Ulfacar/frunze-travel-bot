"""Машинный снимок въездной заявки — то, что бот передаёт в нашу CRM.

Зачем отдельно от карточки. `entry_card` рисует ТЕКСТ для человека: его удобно читать
в Telegram и в панели, но нельзя ни разобрать машинно, ни проверить через месяц. А
предмет здесь — нормы миграционного права, и вопрос «почему бот так сказал клиенту»
рано или поздно задаст либо заказчик, либо проверяющий.

Снимок отвечает ровно на этот вопрос: что собрано, что посчитано, **что из этого
произнесено клиенту**, что умышленно скрыто и на каких единицах знаний всё держится —
с разделом и страницей ТЗ. Он же служит контрактом данных для любого пути в CRM: экрана
в панели, кнопки «принять», выгрузки. Границу см. `docs/bot-to-crm-handoff.md`: снимок
НИЧЕГО не создаёт в типизированной CRM, durable-запись там заводит только named-
администратор.

Два свойства важнее остальных:

1. **Снимок описывает прошлое и не переписывается.** Пишется один раз, в момент
   передачи. Если потом правят данные знаний, подтверждения или флаги, прежний снимок
   остаётся прежним — иначе разбор инцидента опирается на сегодняшнее состояние вместо
   того, что было тогда. Поэтому в нём зафиксированы контрольные суммы бандла и PDF.
2. **Сумм в снимке нет.** Решение владельца «бот цен не называет» распространяется и
   на служебные данные: попав в снимок, сумма попадёт в карточку, выгрузку и CRM.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA = "kg-entry-intake/1"

# Поля анкеты, которые переносятся в снимок. Перечислены явно: случайный ключ из
# диалога не должен уехать в CRM, а служебные (`_verdict_line`, `intake`) — тем более.
SLOTS = (
    "citizenship", "citizenship_iso3", "document_type", "purpose", "purpose_details",
    "location", "in_kg_since", "entry_on", "exit_on", "applicants_count", "inviter",
    "family", "language", "consent_given",
)


def _registration(term: Any) -> dict[str, Any] | None:
    if term is None:
        return None
    return {"exempt_days": getattr(term, "exempt_days", None),
            "working_days_from_border": getattr(term, "working_days_from_border", None),
            "registered_for_days": getattr(term, "registered_for_days", None)}


def _basis(verdict: Any) -> list[dict[str, Any]]:
    """Единицы знаний, на которых держится вывод, — с основанием и страницей ТЗ."""
    rows: list[dict[str, Any]] = []
    for unit in getattr(verdict, "units", ()) or ():
        rows.append({"unit_id": unit.unit_id, "kind": unit.kind, "label": unit.label,
                     "section": unit.section, "page": unit.page,
                     "source_ref": unit.source_ref,
                     "confirmed": bool(getattr(unit, "confirmed", False))})
    return rows


def snapshot(kg: dict[str, Any], verdict: Any, *, said_to_client: Any,
             handoff_reason: str, flags: Any = ()) -> dict[str, Any]:
    """Собрать снимок. Чистая функция: ни БД, ни сети, ни решений о продукте."""
    from app.knowledge.entry_bundle import loaded

    bundle = loaded()
    said = sorted(said_to_client or ())
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bundle_hash": bundle.bundle_hash if bundle is not None else "",
        "source_hash": (str((bundle.meta or {}).get("source_hash") or "")
                        if bundle is not None else ""),
        "citizenship_iso3": (kg or {}).get("citizenship_iso3") or None,
        "slots": {key: kg[key] for key in SLOTS if (kg or {}).get(key) not in (None, "")},
        "verdict": None,
        "said_to_client": said,
        "withheld": list(getattr(verdict, "withheld", ()) or ()),
        "basis": _basis(verdict),
        "flags": list(flags or ()),
        "handoff_reason": handoff_reason or "",
        # Из каких кусков базы знаний бот отвечал. Клиенту раздел и страница не
        # показываются (решение владельца), поэтому снимок и карточка — единственное
        # место, где это остаётся, и единственный способ потом ответить на вопрос
        # «почему бот так сказал».
        "knowledge_used": [
            {"piece_id": row.get("piece_id"), "block": row.get("block"),
             "section": row.get("section"), "pdf_pages": list(row.get("pdf_pages") or ()),
             "labels": list(row.get("labels") or ())}
            for row in ((kg or {}).get("_knowledge") or ())
        ],
    }
    if verdict is not None:
        out["verdict"] = {
            "regime": getattr(verdict, "regime", None),
            "stay_limit_days": getattr(verdict, "stay_limit_days", None),
            "window_days": getattr(verdict, "window_days", None),
            "unified_permit_required": getattr(verdict, "unified_permit_required", None),
            "gknb_approval": getattr(verdict, "gknb_approval", None),
            "registration": _registration(getattr(verdict, "registration", None)),
            "notes": list(getattr(verdict, "notes", ()) or ()),
        }
    return out


def store(kg: dict[str, Any], intake: dict[str, Any]) -> None:
    """Положить снимок в анкету один раз. Повторная передача его не переписывает."""
    if isinstance(kg, dict) and not kg.get("intake"):
        kg["intake"] = intake
