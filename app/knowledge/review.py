"""E5-02C: сравнение проверенных снимков без решения о публикации или праве въезда."""
from __future__ import annotations

from collections import Counter
import json


def canonical(value) -> str:
    """JSON сравнение различает boolean/integer и не зависит от порядка ключей."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def field_changes(before: dict, after: dict) -> dict:
    changed = {}
    for key in sorted(before.keys() | after.keys()):
        if (key in before) != (key in after) or canonical(before.get(key)) != canonical(after.get(key)):
            changed[key] = {"before_present": key in before, "after_present": key in after,
                            "before": before.get(key), "after": after.get(key)}
    return changed


def review_findings(unit: dict) -> list[str]:
    """Только наблюдаемые факты. Пустой список НЕ означает готовность к публикации."""
    findings = []
    if unit["confirmation_status"] != "confirmed":
        findings.append("not_confirmed")
    if unit["value"] is None:
        findings.append("value_missing")
    if unit.get("blocked_value"):
        findings.append("unresolved_evidence")
    if unit.get("conflict_ref"):
        findings.append("source_conflict")
    if unit.get("owner", "").startswith("unassigned:"):
        findings.append("owner_unassigned")
    if not unit.get("verified_at") or not unit.get("verified_by"):
        findings.append("verification_missing")
    if not unit.get("effective_from"):
        findings.append("effective_from_unknown")
    if not unit.get("review_due_at"):
        findings.append("review_due_unknown")
    return findings


def unit_summary(unit: dict) -> dict:
    return {key: unit[key] for key in ("unit_id", "kind", "title", "confirmation_status",
                                      "source_ref", "page")}


def compare_snapshots(before: dict | None, after: dict) -> dict:
    """Входы уже валидированы сервисом; функция чистая, не импортирует DB/config.

    Порядок единиц не значим. Отсутствие поля отличается от явного null. При новом
    наборе все единицы added; это не сравнение с якобы действующей пустой версией.
    """
    old = {u["unit_id"]: u for u in before["units"]} if before else {}
    new = {u["unit_id"]: u for u in after["units"]}
    changed = []
    for uid in sorted(old.keys() & new.keys()):
        changes = field_changes(old[uid], new[uid])
        if changes:
            changed.append({**unit_summary(new[uid]), "fields": changes})
    added = [unit_summary(new[uid]) for uid in sorted(new.keys() - old.keys())]
    removed = [unit_summary(old[uid]) for uid in sorted(old.keys() - new.keys())]
    findings = [{"unit_id": uid, "codes": codes} for uid in sorted(new)
                if (codes := review_findings(new[uid]))]
    return {
        "mode": "review_only", "baseline_present": before is not None,
        "publication_approved": False, "activation_supported": False,
        "source_reverified": False,
        "summary": {"before_units": len(old), "after_units": len(new), "added": len(added),
                    "removed": len(removed), "changed": len(changed),
                    "unchanged": len(old.keys() & new.keys()) - len(changed)},
        "metadata_changes": field_changes(before["meta"] if before else {}, after["meta"]),
        "country_alias_changes": field_changes(before["countries"] if before else {}, after["countries"]),
        "added": added, "removed": removed, "changed": changed,
        "status_counts": dict(sorted(Counter(u["confirmation_status"] for u in new.values()).items())),
        "finding_counts": dict(sorted(Counter(code for item in findings for code in item["codes"]).items())),
        "findings": findings,
    }
