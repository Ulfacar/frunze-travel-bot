"""Воспроизводимый НЕУТВЕРЖДЁННЫЙ пакет E5-02B по фиксированному PDF v1.1.

--check сравнивает артефакты; без него создаёт только новые/идентичные файлы.
--pdf дополнительно сверяет capture непосредственно с исходным PDF, без записи в БД.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge.bundle import validate_bundle
from scripts.kg_entry_source import (
    PDF_NAME, PDF_SHA256, compare_conversion, extract_pdf, json_bytes,
    source_yaml, template_sections, validate_capture,
)

SOURCE_DIR = ROOT / "knowledge/kg_entry/source_v1_1"
OUTPUT_DIR = ROOT / "knowledge/kg_entry/draft-v1.1"
DERIVED = ROOT / "docs/kb-visa-inbound-v1.1-derived.md"
ROW_IDS = {
    "processing_times": ("EVISA", "GKNB", "PAPER_VISA", "VISA_SUPPORT", "EP", "RESIDENT_CARD",
                         "REGISTRATION", "EXIT_L", "TEMPORARY_RESIDENCE", "PERMANENT_RESIDENCE"),
    "deadlines": ("EMAIL_VERIFICATION", "VISA_CORRECTION", "EP_RC_CORRECTION", "VISA_FEE_REFUND_REQUEST",
                  "VISA_EXTENSION", "EP_BEFORE_VISA_FREE_END", "RC_BEFORE_EP_END", "EP_BEFORE_RC_END",
                  "DISMISSAL_NOTIFICATION", "EXIT_AFTER_EP_END", "QUOTA_USE", "VISA_SUPPORT_VALIDITY",
                  "EXIT_L_VALIDITY", "REGISTRATION_CODE_PAYMENT", "VISA_FREE_REGISTRATION",
                  "REGISTRATION_OUTSIDE_LIST", "REGISTRATION_EXTENSION", "REREGISTRATION",
                  "NEWBORN_REGISTRATION", "NEWBORN_VISA", "MEKEN_REGISTRATION", "PASSPORT_VALIDITY"),
}


def read_inputs(directory: Path = SOURCE_DIR):
    lock = json.loads((directory / "source-lock.json").read_text(encoding="utf-8"))
    names = {"capture.json", "aliases.json", "iso3166.json"}
    if lock.get("format") != "kg-entry-source-lock/1" or set(lock.get("files", {})) != names:
        raise ValueError("Unexpected source lock")
    loaded = {}
    for name in sorted(names):
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != lock["files"][name]:
            raise ValueError(f"Source snapshot changed: {name}; review before updating lock")
        loaded[name] = json.loads(raw)
    return loaded["capture.json"], loaded["aliases.json"], loaded["iso3166.json"], lock


def build_bundle(capture: dict, aliases: dict, catalog: dict, lock: dict, markdown: str):
    validate_capture(capture)
    comparison = compare_conversion(capture, markdown)
    original, _ = source_yaml(capture)
    countries = {code: code for code in catalog}
    countries.update(aliases)
    if len(catalog) != 249 or any(code not in catalog for code in aliases.values()):
        raise ValueError("ISO3 registry/aliases incomplete")
    units, provenance = [], []

    def codes(names):
        try:
            return [aliases[name] for name in names]
        except KeyError as exc:
            raise ValueError("Unmapped source country alias") from exc

    def add(uid, kind, title, section, pages, source, selector, *, value=None,
            label="none", status="needs_verification", conflict=None, reason="Source has not been approved for publication",
            source_ref=None, extra=None):
        # Каждая запись хранит полный источник даже когда скалярную схему заполнять нельзя.
        quote = source if isinstance(source, str) else json.dumps(source, ensure_ascii=False)
        evidence = {"source": deepcopy(source), "reason": reason}
        if extra:
            evidence.update(deepcopy(extra))
        unit = {"unit_id": uid, "kind": kind, "title": title, "section": section,
                "page": ",".join(map(str, pages)), "source_ref": source_ref or f"KB v1.1, раздел {section}",
                "source_text": quote if len(quote) <= 2000 else None,
                "label": label, "confirmation_status": status, "value": deepcopy(value),
                "value_schema_version": 1, "blocked_value": evidence, "conflict_ref": conflict,
                "effective_from": None, "effective_to": None, "verified_at": None, "verified_by": None,
                "review_due_at": None, "owner": "unassigned:DEC-07"}
        units.append(unit)
        provenance.append({"unit_id": uid, "capture_selector": selector, "pdf_pages": pages,
                           "source_labels": sorted(set(re.findall(r"\[(?:ПРОВЕРИТЬ|ПРАКТИКА|РЕШЕНИЕ)[^\]]*\]",
                                                                  quote + json.dumps(extra or {}, ensure_ascii=False)))),
                           "value_typed": value is not None})

    # Перечень берётся из таблицы 2.10, не из обобщающих полей Б.5.
    exemptions = {}
    registration = capture["tables"]["registration"]
    for index, row in enumerate(registration[:-1]):
        days = int(re.fullmatch(r"(\d+) (?:дней|день)", row["cells"][0]).group(1))
        names = [s.strip() for s in row["cells"][1].split(",")]
        for name, code in zip(names, codes(names)):
            if code in exemptions:
                raise ValueError("Duplicate exemption country in PDF table")
            exemptions[code] = days
            add(f"KG.REG.EXEMPT.{code}", "registration_exemption", f"Освобождение от регистрации: {name}",
                "2.10", [row["page"]], row["cells"], f"tables/registration/{index}",
                value={"days": days}, source_ref="ПР-600, приложение 2 (как процитировано в PDF)")
    if exemptions.get("GRC") != 90 or exemptions.get("CHL") != 60 or "MDA" in exemptions:
        raise ValueError("SRC-04/05 source assumptions changed")
    add("KG.REG.EXEMPT.MDA", "registration_exemption", "Молдова: конфликт срока освобождения",
        "2.10; Б.5", [25, 88], registration[-1]["cells"], "tables/registration/8 + pages/88",
        status="blocked", conflict="SRC-04", reason="Registration duration is not an exemption",
        extra={"source_value": original["visa_free"]["ninety_180"]["registration_exempt_days"]["Молдова"],
               "source_locations": ["PDF 25, раздел 2.10: нет в перечне", "PDF 88, Б.5: Молдова 90"],
               "b5_source": original["visa_free"]["ninety_180"]})
    for code, days in (("UZB", 60), ("MDA", 90)):
        add(f"KG.REG.TERM.{code}", "registration_term", f"Срок оформления регистрации: {code}",
            "2.10", [25], registration[-1]["cells"], "tables/registration/8", value={"days": days})

    free = original["visa_free"]
    for key, suffix in (("eaeu", "EAEU"), ("uzbekistan", "UZB"), ("ninety_180", "NINETY_180"),
                        ("annex1_30_60", "ANNEX1_30_60"), ("gcc", "GCC"), ("cis_bilateral", "CIS_BILATERAL")):
        group = free[key]
        # У GCC поле работы в Б.5 отсутствует; не подставляем предположение как typed value.
        unresolved = key == "gcc"
        value = None if unresolved else {**group["limit"], "countries": codes(group["countries"]),
                                        "work_needs_unified_permit": group["work_needs_unified_permit"]}
        add(f"KG.VF.{suffix}", "visa_free_regime", f"Режим безвизового пребывания: {suffix}",
            "2.2; Б.5", [19, 20, 21, 22, 88, 89], group, f"B.5/visa_free/{key}",
            value=None if unresolved else value, label="verify" if key == "cis_bilateral" else "none",
            reason="Missing work-permit attribute in B.5; reconcile section 2 before typing" if unresolved else
                   "Source rule awaits review; group registration fields are not used",
                extra={"source_inline_context": "[ПРОВЕРИТЬ] по тексту акта"} if key == "cis_bilateral" else None)
    for name in free["other_check_portal"]["countries"]:
        code = codes([name])[0]
        add(f"KG.VF.{code}", "visa_free_regime", f"Дополнительный режим: {name}", "2.2; Б.5", [22, 89],
            free["other_check_portal"], "B.5/visa_free/other_check_portal", label="verify",
            reason="No complete days/window/work-permit tuple in source; do not invent a rolling window",
            extra={"country_iso3": code})

    # not_in_list перечисляет страны, реально затронутые входными правилами, а не весь мир.
    relevant = set()
    for group in free.values():
        relevant.update(codes(group["countries"]))
    for names in original["visa_required"]["simplified_annex2_no_gknb"].values():
        relevant.update(codes(names))
    relevant.update(codes(["Китай", "Пакистан", "Египет", "Афганистан", "КНДР", "Туркменистан", "Ирак", "Сирия", "Нигерия"]))
    # MDA сохраняется только отдельной blocked-единицей, не обходит конфликт через DEFAULT.
    not_in_list = sorted(relevant - set(exemptions) - {"MDA"})
    default_days = original["registration_default"]["deadline_working_days_from_border_crossing"]
    add("KG.REG.DEFAULT", "registration_default", "Регистрация: страны вне перечня", "2.10; Б.5", [25, 88],
        registration[-1]["cells"], "tables/registration/8 + B.5/registration_default",
        value={"deadline_working_days_from_border": default_days, "not_in_list": not_in_list},
        extra={"coverage_derivation": "referenced countries absent from complete 2.10 list, excluding conflicted MDA"})
    add("KG.WATCH.UZB_15DAYS", "rule_param", "Узбекистан: протокол о 15 сутках", "Б.5; Г.3", [88],
        free["uzbekistan"]["watch"], "B.5/visa_free/uzbekistan/watch", label="verify",
        reason="Entry into force is unknown; value is not a current registration deadline")

    for key, suffix in (("hong_kong_macao_permanent_residents", "HK_MACAO"), ("un_laissez_passer", "UN_LP"),
                        ("china_india_with_longterm_us_uk_schengen_visa", "CHN_IND_LONGTERM_VISA"),
                        ("china_organized_tour_group_5_25", "CHN_TOUR_GROUP")):
        add(f"KG.SP.{suffix}", "special_regime", f"Особый режим: {suffix}", "2.5; Б.5", [23, 89],
            original["special"][key], f"B.5/special/{key}",
            reason="Full applicability conditions from section 2.5 need reviewed machine representation",
            extra={"applicability_source": capture["pages"]["23"]})
    vr = original["visa_required"]["simplified_annex2_no_gknb"]
    for key, suffix, scope in (("all_types", "SIMPLIFIED_ALL", "all_types"),
                              ("only_business_and_tourist", "SIMPLIFIED_IRN_B_TS", "business_tourist"),
                              ("only_tourist_up_to_1_month_if_gcc_or_brunei_residence", "SIMPLIFIED_GCC_RESIDENT_TS", "tourist_gcc_resident")):
        value = {"procedure": "simplified", "scope": scope, "gknb_approval": False, "countries": codes(vr[key])}
        add(f"KG.VR.{suffix}", "visa_required_regime", f"Упрощённый визовый порядок: {suffix}", "2.4; Б.5", [22, 23, 89],
            {key: vr[key]}, f"B.5/visa_required/simplified_annex2_no_gknb/{key}",
            value=None if scope == "tourist_gcc_resident" else value,
            reason="Residence document/countries and one-month limit require explicit schema" if scope == "tourist_gcc_resident" else
                   "Source has not been approved for publication", extra={"candidate": value})
    add("KG.VR.GENERAL", "visa_required_regime", "Общий визовый порядок", "2.4; Б.5", [23, 89],
        original["visa_required"]["general_procedure_with_gknb"], "B.5/visa_required/general_procedure_with_gknb",
        value={"procedure": "general", "scope": "all_types", "gknb_approval": True, "countries": "all_others"})

    rule_map = {
        "visa_inside_kg_forbidden": ("VISA_INSIDE_KG_FORBIDDEN", "list"),
        "e_visa_entry_points_official": ("EVISA_ENTRY_POINTS", "list"),
        "multiple_entry_required_if_days_over": ("MULTIPLE_ENTRY_OVER_DAYS", "days"),
        "extension_petition_min_working_days_before_end": ("EXTENSION_MIN_WD", "working_days"),
        "unified_permit_min_working_days_before_visa_free_end": ("EP_MIN_WD_BEFORE_VF_END", "working_days"),
        "resident_card_min_working_days_before_ep_end": ("RC_MIN_WD_BEFORE_EP_END", "working_days"),
        "new_ep_min_working_days_before_resident_card_end": ("NEW_EP_MIN_WD_BEFORE_RC_END", "working_days"),
        "overstay_entry_ban": ("OVERSTAY_BAN", None),
        "registration_does_not_extend_visa_free": ("REG_DOES_NOT_EXTEND_VF", "bool"),
        "no_registration_in_last_days_of_60_90_limit": ("NO_REG_LAST_DAYS", "days"),
    }
    if set(rule_map) != set(original["rules"]):
        raise ValueError("Unmapped B.5 rule parameter")
    for key, (suffix, measure) in rule_map.items():
        raw = original["rules"][key]
        # NO_REG_LAST_DAYS зависит от лимита 60/90, а не универсален; сохранить условие.
        typed = measure is not None and suffix != "NO_REG_LAST_DAYS"
        add(f"KG.RULE.{suffix}", "rule_param", f"Параметр: {suffix}", "Б.5", [89], {key: raw}, f"B.5/rules/{key}",
            value={"value": raw, "unit": measure} if typed else None,
            reason="Conditional parameter needs calculator support" if not typed else "Source awaits review",
            extra={"source_inline_context": "Другие КПП — после подтверждения поддержки портала"}
            if suffix == "EVISA_ENTRY_POINTS" else None)
    for suffix in ("COUNT_ENTRY_DAY", "COUNT_EXIT_DAY", "WINDOW_ANCHOR"):
        add(f"KG.RULE.{suffix}", "rule_param", f"Правило расчёта дней: {suffix}", "2.9; CALC-02", [24],
            capture["pages"]["24"].split("2.9.", 1)[1].split("2.10.", 1)[0], "pages/24/2.9",
            label="decision", status="decision_pending", reason="CALC-02 requires approved calculation examples")

    # Все строки 13.1/13.2 сохраняются. Не заменять диапазон, условие или отсутствующий anchor одним числом.
    for key, kind, prefix, section in (("processing_times", "processing_time", "PT", "13.1"),
                                       ("deadlines", "deadline", "DL", "13.2")):
        for index, row in enumerate(capture["tables"][key]):
            quote = " | ".join(row["cells"])
            add(f"KG.{prefix}.{ROW_IDS[key][index]}", kind, row["cells"][0], section, [row["page"]], row["cells"],
                f"tables/{key}/{index}", label="verify" if "[ПРОВЕРИТЬ" in quote else "none",
                source_ref=row["cells"][-1] if kind == "deadline" else f"KB v1.1, {section}",
                reason="Source row preserved; exact anchor, variants and calendar policy need reviewed mapping")

    approved_line = re.search(r"Утверждено руководством:.*?\(за человека, сверх госплатежей\)\.", capture["pages"]["59"], re.S)
    if approved_line is None:
        raise ValueError("Cannot identify source-approved service fees paragraph")
    amounts = re.findall(r"\$(\d+)", approved_line.group())
    if len(amounts) != 3:
        raise ValueError("Unexpected service fee paragraph")
    for product, amount in zip(("TS", "B", "EP"), amounts):
        add(f"KG.FEE.SERVICE.{product}", "tariff", f"Сервисный сбор: {product}", "0.5; 12.6", [9, 59],
            approved_line.group(), "pages/59/approved_fees", value={"amount": int(amount), "currency": "USD", "per": "person", "component": "service"},
            extra={"approval_in_source": True, "publication_approval": "UNKNOWN"})
    fee_products = (("TR", "RL", "FF", "S", "M", "J", "DN", "A"), ("SW1", "SW2"), ("RC_WORK",),
                    ("RC_STUDY_FAMILY",), ("EXTENSION",), ("URGENT",), ("REGISTRATION",), ("OVERSTAY",),
                    ("RESIDENCE_PERMIT",), ("GROUP",), ("RESUBMISSION",))
    for index, (row, products) in enumerate(zip(capture["tables"]["service_fees"], fee_products)):
        for product in products:
            conflict = "SRC-03" if product in {"SW1", "SW2", "RC_WORK"} else None
            add(f"KG.FEE.SERVICE.{product}", "tariff", row["cells"][0], "12.6", [59], row["cells"], f"tables/service_fees/{index}",
                label="decision", status="decision_pending", conflict=conflict,
                reason="Source proposal, not an approved tariff",
                extra={"source_locations": ["PDF 9, 0.5", "PDF 59, 12.6", "PDF 13/15, 1.2", "PDF 82, 19.8"],
                       "conflicting_source_pages": {n: capture["pages"][n] for n in ("13", "15", "82")}}
                if conflict else {"source_label": "[РЕШЕНИЕ]"})

    for template in template_sections(capture):
        number = template["number"]
        conflict = "SRC-08" if number == 8 else "SRC-07" if number == 11 else None
        add(f"KG.TPL.A{number:02d}", "template", template["title"], f"А.{number}", template["pages"],
            template["text"], f"templates/A.{number}", status="blocked" if conflict else "needs_verification",
            conflict=conflict, reason="Unadapted source template; E5-04 must render from approved calculator output")
    for index, row in enumerate(capture["tables"]["escalation"]):
        add(f"KG.ESC.STOP_{index + 1:02d}", "escalation_trigger", row["cells"][0], "4.1", [30], row["cells"],
            f"tables/escalation/{index}", value={"condition": row["cells"][0], "action": row["cells"][2]})
    extra_escalation = capture["pages"]["89"].split("Б.6. Триггеры эскалации", 1)[1].split("Б.7.", 1)[0].strip()
    add("KG.ESC.ADDITIONAL_B6", "escalation_trigger", "Дополнительные триггеры Б.6", "Б.6", [89],
        extra_escalation, "pages/89/B.6", reason="Compound conditions retained as source; not evaluated")

    meta = {"schema_version": "kg-entry-bundle/1", "set_code": "kg_entry", "version_label": "v1.1-source-draft-20261007",
            "source_document": PDF_NAME, "source_hash": PDF_SHA256, "prepared_by": lock["prepared_by"],
            "prepared_at": lock["prepared_at"], "effective_from": None}
    units.sort(key=lambda u: u["unit_id"])
    result = validate_bundle(meta, countries, units, source_hash=PDF_SHA256)
    if not result.ok:
        raise ValueError("Generated bundle failed preflight: " + ", ".join(f"{i.code} {i.location}" for i in result.errors[:8]))
    audit = {"format": "kg-entry-source-audit/1", "pdf_sha256": PDF_SHA256, "source_lock": deepcopy(lock),
             "derived_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
             "conversion_comparison": comparison, "bundle_hash": result.bundle_hash,
             "units": len(units), "by_kind": dict(sorted(Counter(u["kind"] for u in units).items())),
             "by_status": result.status_counts, "typed_values": sum(u["value"] is not None for u in units),
             "provenance": sorted(provenance, key=lambda p: p["unit_id"]),
             "publication_approved": False, "legal_review": "UNKNOWN", "source_coverage": {
                 "registration_rows": 9, "exemption_countries": len(exemptions), "service_fee_proposals": 11,
                 "processing_rows": 10, "deadline_rows": 22, "templates": 13, "stop_factors": 12,
                 "government_tariffs_12_1_to_12_5": "NOT_CONVERTED", "other_pdf_sections": "NOT_FULLY_CONVERTED"},
             "notes": ["All rules await review; no publication approval is inferred from the PDF",
                       "Korea in 2.10 mapped to KOR; DPRK is separately PRK and absent from list",
                       "Macedonia in 2.10 mapped to MKD, matching North Macedonia in B.5",
                       "No deadline, review period or pricing policy invented",
                       "All source exceptions/proposals retained under blocked_value"]}
    return {"meta.yaml": json_bytes(meta), "countries.yaml": json_bytes(countries), "units.yaml": json_bytes(units)}, audit


def write_or_check(output: Path, files: dict[str, bytes], audit: dict, *, check: bool) -> bool:
    audit_path = output.with_name(output.name + ".audit.json")
    expected = {output / name: content for name, content in files.items()}
    expected[audit_path] = json_bytes(audit)
    if output.exists() and (output.is_symlink() or not output.is_dir() or
                            {p.name for p in output.iterdir()} - set(files)):
        raise ValueError("Output directory contains unexpected entries; no files written")
    for path, data in expected.items():
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_bytes() != data)):
            if check:
                return False
            raise ValueError("Existing generated file differs; use a new output directory after review")
    if check:
        return all(path.exists() for path in expected)
    output.mkdir(parents=True, exist_ok=True)
    # Все данные проверены до первой записи. x исключает перезапись при гонке.
    for path, data in expected.items():
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(data)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="Compare source capture directly against this exact PDF")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--check", action="store_true", help="Read-only reproducibility check")
    args = parser.parse_args(argv)
    try:
        capture, aliases, catalog, lock = read_inputs()
        if args.pdf and extract_pdf(args.pdf) != capture:
            raise ValueError("PDF extraction differs from reviewed source capture")
        files, audit = build_bundle(capture, aliases, catalog, lock, DERIVED.read_text(encoding="utf-8"))
        ok = write_or_check(args.output, files, audit, check=args.check)
        print(json.dumps({"ok": ok, "mode": "check" if args.check else "build_draft", "units": audit["units"],
                          "source_pdf_compared": bool(args.pdf), "bundle_hash": audit["bundle_hash"],
                          "imported": False, "publication_approved": False}, indent=2))
        return 0 if ok else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
