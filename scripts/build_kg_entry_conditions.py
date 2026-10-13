"""Build/check six unapproved condition profiles bound to the unchanged v1.1 bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge.bundle import validate_bundle
from app.knowledge.conditions import ConditionReview
from app.knowledge.validation import load_document
from scripts.build_kg_entry_bundle import OUTPUT_DIR, read_inputs
from scripts.kg_entry_source import extract_pdf, json_bytes, source_yaml, validate_capture

OUTPUT = ROOT / "knowledge/kg_entry/conditions_v1_1/catalog.json"


def build_catalog():
    capture, aliases, _, lock = read_inputs()
    validate_capture(capture)
    original, _ = source_yaml(capture)
    data = {name: load_document(OUTPUT_DIR / f"{name}.yaml") for name in ("meta", "countries", "units")}
    report = validate_bundle(**data, source_hash=capture["pdf_sha256"])
    if not report.ok:
        raise ValueError("invalid_bundle")
    page22 = " ".join(capture["pages"]["22"].split())
    page23 = " ".join(capture["pages"]["23"].split())
    years = re.search(r"долгосрочной \(>(\d+) лет\)", page23)
    group = re.search(r"тургруппы граждан КНР \((\d+)\s*[–-]\s*(\d+) чел\.\)", page23)
    month = re.search(r"только TS до (\d+) месяца", page22)
    if not all((years, group, month)) or "кроме форс-мажора" not in page23:
        raise ValueError("source_conditions_missing")
    # Mapping reviewed directly against physical p.22; no inferred GCC membership service.
    residence_names = ("ОАЭ", "Саудовской Аравии", "Кувейта", "Катара", "Брунея", "Омана", "Бахрейна")
    residence_sentence = page22.split("при ВНЖ/резидент-карте ", 1)[1].split(".", 1)[0]
    if not all(name in residence_sentence for name in residence_names):
        raise ValueError("source_residence_list_changed")
    residence_codes = ["ARE", "SAU", "KWT", "QAT", "BRN", "OMN", "BHR"]
    common_unknown = ["legal_source_unapproved", "effective_dates_not_verified", "document_validity_not_verified"]
    rules = []

    def add(uid, clauses, outcome, pages, unresolved=()):
        rules.append({"unit_id": uid, "all": clauses, "source_outcome": outcome,
                      "source_locations": [{"page": page, "section": section} for page, section in pages],
                      "unresolved": common_unknown + list(unresolved)})

    special = original["special"]
    hk = dict(special["hong_kong_macao_permanent_residents"])
    hk["stay_days"] = hk.pop("days")
    hk["visa_inside_exception"] = "force_majeure"
    add("KG.SP.HK_MACAO", [{"type": "permanent_residence_in", "countries": ["HKG", "MAC"]}],
        hk, [(23, "2.5"), (89, "Б.5/special")], ["stay_and_reentry_not_calculated"])
    add("KG.SP.UN_LP", [{"type": "document_type_is", "value": "un_lp"}],
        {"stay_days": special["un_laissez_passer"]["days"]}, [(23, "2.5"), (89, "Б.5/special")])
    visa = special["china_india_with_longterm_us_uk_schengen_visa"]
    add("KG.SP.CHN_IND_LONGTERM_VISA", [
        {"type": "passport_country_in", "countries": ["CHN", "IND"]},
        {"type": "foreign_visa", "issuers": ["USA", "GBR", "SCHENGEN"], "validity_years_gt": int(years[1])},
    ], {"stay_days": visa["days"], "reentry_after_days": visa["reentry_after_days"]},
        [(23, "2.5"), (89, "Б.5/special")], ["three_year_duration_basis_needs_review", "stay_and_reentry_not_calculated"])
    tour = special["china_organized_tour_group_5_25"]
    add("KG.SP.CHN_TOUR_GROUP", [
        {"type": "passport_country_in", "countries": ["CHN"]},
        {"type": "organized_tour_group", "country": "CHN", "minimum": int(group[1]),
         "maximum": int(group[2]), "petition_required": True},
    ], {"stay_days": tour["days"], "reentry_after_days": tour["reentry_after_days"],
        "visa_inside_kg": tour["visa_inside_kg"], "visa_inside_exception": "force_majeure"},
        [(23, "2.5"), (89, "Б.5/special")], ["stay_and_reentry_not_calculated"])
    gcc = original["visa_free"]["gcc"]
    add("KG.VF.GCC", [{"type": "passport_country_in", "countries": sorted(aliases[name] for name in gcc["countries"])}],
        {"stay_days": gcc["limit"]["days"], "window_days": gcc["limit"]["window_days"], "work_permit_requirement": "unknown"},
        [(21, "2.2"), (88, "Б.5/visa_free/gcc")], ["work_permit_requirement_unknown", "rolling_window_not_calculated"])
    eligible = original["visa_required"]["simplified_annex2_no_gknb"]["only_tourist_up_to_1_month_if_gcc_or_brunei_residence"]
    add("KG.VR.SIMPLIFIED_GCC_RESIDENT_TS", [
        {"type": "passport_country_in", "countries": sorted(aliases[name] for name in eligible)},
        {"type": "visa_type_is", "value": "TS"},
        {"type": "stay_within_months", "maximum": int(month[1])},
        {"type": "residence_permit_in", "countries": sorted(residence_codes)},
    ], {"visa_type": "TS", "max_stay_months": int(month[1]), "gknb_approval": False},
        [(22, "2.4"), (89, "Б.5/visa_required")], ["one_month_boundary_needs_review"])
    catalog = {"format": "kg-entry-conditions/1", "status": "draft", "publication_approved": False,
               "source_hash": capture["pdf_sha256"], "bundle_hash": report.bundle_hash,
               "source_capture_sha256": lock["files"]["capture.json"], "source_date": "2026-10-02",
               "date_basis": "source_claim", "rules": sorted(rules, key=lambda r: r["unit_id"])}
    ConditionReview(catalog, **data, source_hash=capture["pdf_sha256"])
    return catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--pdf", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.pdf and extract_pdf(args.pdf) != read_inputs()[0]:
            raise ValueError("pdf_capture_mismatch")
        encoded = json_bytes(build_catalog())
        if args.output.is_symlink():
            raise ValueError("output_symlink")
        if args.output.exists():
            if args.output.read_bytes() != encoded:
                raise ValueError("output_differs")
        elif args.check:
            raise ValueError("output_missing")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("xb") as stream:
                stream.write(encoded)
        print(json.dumps({"ok": True, "rules": 6, "catalog_file_sha256": hashlib.sha256(encoded).hexdigest(),
                          "source_pdf_compared": args.pdf is not None, "publication_approved": False}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        print(json.dumps({"ok": False, "code": "conditions_build_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
