"""Собрать оверлей подтверждений въездных знаний из бандла.

Подтверждение разрешает боту произносить норму миграционного права как факт, поэтому
оверлей не правится руками: он собирается этим скриптом по явному правилу отбора, и
результат проверяется `scripts/verify_entry_confirmations.py`.

Правило отбора — ровно то, что разрешил заказчик, и ни строкой больше:

  * у единицы есть значение (пустое подтверждать нечем);
  * метка ТЗ — `none`. `[ПРОВЕРИТЬ]` (`verify`) и `[РЕШЕНИЕ]` (`decision`) сам ТЗ
    считает непроверенным, и «как в ПДФ» означает их НЕ произносить;
  * нет отметки о конфликте источников;
  * вид единицы — из белого списка ``KINDS``: режимы въезда и регистрация.

Чего в белом списке нет и почему:

  * ``tariff`` — решение Алана 21.10.2026: бот сумм не называет вообще. В ТЗ
    (прил. Г п.2) государственные сборы имеют статус «Открыт», фактических сумм
    e-Visa не существует, комиссия банка названа двумя разными цифрами;
  * ``rule_param``, ``escalation_trigger``, ``deadline``, ``template`` — движок не
    отдаёт их клиенту как факт, подтверждать нечего;
  * ``special_regime`` — все четыре единицы пустые, по ТЗ это всегда человек.

Запуск: ``python scripts/build_entry_confirmations.py --approved-by "..." [--dry-run]``
"""
from __future__ import annotations

import argparse
from datetime import date
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "knowledge" / "kg_entry" / "draft-v1.1"
OVERLAY = ROOT / "knowledge" / "kg_entry" / "confirmations-v1.1.yaml"

KINDS = ("visa_free_regime", "visa_required_regime",
         "registration_default", "registration_term", "registration_exemption")

BASIS = ("owner_approval_relayed + машинная сверка таблиц 2.3 и 2.10 исходного PDF "
         "скриптом scripts/verify_entry_confirmations.py")
CHECKED_BY = "scripts/verify_entry_confirmations.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved-by", required=True,
                        help="кто разрешил и как это получено — записывается в каждую строку")
    parser.add_argument("--confirmed-at", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    from app.knowledge import entry_confirmations
    from app.knowledge.entry_bundle import loaded

    meta = json.loads((BUNDLE / "meta.yaml").read_text(encoding="utf-8"))
    bundle = loaded()
    if bundle is None:
        print("НЕВОЗМОЖНО: бандл знаний не загружается")
        return 2
    # Единицы берём из ЗАГРУЖЕННОГО бандла, а не из units.yaml: загрузчик нормализует
    # значения (например сортирует списки стран), и движок сверяет хеш именно с этой
    # формой. Хеш, снятый с сырого файла, с ней не совпадёт.
    units = list(bundle.units)

    rows = []
    skipped: dict[str, int] = {}
    for unit in units:
        kind = unit.get("kind")
        if kind not in KINDS:
            skipped[f"вид {kind}"] = skipped.get(f"вид {kind}", 0) + 1
            continue
        if unit.get("value") is None:
            skipped["пустое значение"] = skipped.get("пустое значение", 0) + 1
            continue
        if str(unit.get("label") or "") != "none":
            skipped[f"метка {unit.get('label')}"] = \
                skipped.get(f"метка {unit.get('label')}", 0) + 1
            continue
        if unit.get("conflict_ref"):
            skipped["конфликт источников"] = skipped.get("конфликт источников", 0) + 1
            continue
        rows.append({
            "unit_id": unit["unit_id"],
            "value_sha256": entry_confirmations.value_digest(unit["value"]),
            "source_ref": unit.get("source_ref") or "",
            "section": unit.get("section") or "",
            "page": unit.get("page") or "",
            "basis": BASIS,
            "approved_by": args.approved_by,
            "checked_by": CHECKED_BY,
            "confirmed_at": args.confirmed_at,
        })

    rows.sort(key=lambda r: r["unit_id"])
    doc = {
        "schema_version": entry_confirmations.SCHEMA_VERSION,
        "bundle_hash": bundle.bundle_hash,
        "source_hash": meta.get("source_hash"),
        "confirmed": rows,
    }

    by_kind: dict[str, int] = {}
    index = {u["unit_id"]: u for u in units}
    for row in rows:
        kind = index[row["unit_id"]]["kind"]
        by_kind[kind] = by_kind.get(kind, 0) + 1

    print(f"подтверждений: {len(rows)}")
    for kind, count in sorted(by_kind.items()):
        print(f"   {kind}: {count}")
    print("пропущено:")
    for reason, count in sorted(skipped.items()):
        print(f"   {reason}: {count}")

    if args.dry_run:
        print("\n--dry-run: файл не записан")
        return 0
    OVERLAY.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    print(f"\nзаписан {OVERLAY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())
