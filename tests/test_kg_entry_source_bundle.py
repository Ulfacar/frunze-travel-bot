"""Реальный PDF как источник данных; тесты не утверждают действительность норм."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

from app.knowledge.bundle import validate_bundle
from app.knowledge.validation import load_document
from scripts.build_kg_entry_bundle import (
    DERIVED, OUTPUT_DIR, SOURCE_DIR, build_bundle, main, read_inputs, write_or_check,
)
from scripts.kg_entry_source import (
    PDF_SHA256, compare_conversion, extract_pdf, json_bytes, normalize, source_yaml,
    strict_source_yaml, template_sections, validate_capture,
)


@pytest.fixture(scope="module")
def inputs():
    return (*read_inputs(), DERIVED.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def generated(inputs):
    return build_bundle(*inputs)


def unpack(generated):
    files, audit = generated
    return {name: json.loads(data) for name, data in files.items()}, audit


def index(generated):
    return {u["unit_id"]: u for u in json.loads(generated[0]["units.yaml"])}


def test_direct_pdf_capture_matches_selected_derived_inputs(inputs):
    capture, _, _, _, markdown = inputs
    report = compare_conversion(capture, markdown)
    assert [row["rows"] for row in report["tables"]] == [9, 11, 10, 22, 12]
    assert all(row["result"] == "PASS" for row in report["tables"])
    assert report["templates"] == {"count": 13, "result": "PASS"}
    assert report["legal_review"] == "UNKNOWN"
    # Отдельно PDF-перенос в начале стр.89: отступ не потерян при очистке страницы.
    assert capture["pages"]["89"].startswith("    limit:")
    original, _ = source_yaml(capture)
    assert original["visa_free"]["cis_bilateral"]["limit"] == {"days": 60, "window_days": 120}


def test_real_bundle_is_reproducible_and_passes_actual_file_parser(generated):
    files, audit = generated
    assert write_or_check(OUTPUT_DIR, files, audit, check=True)
    data = [load_document(OUTPUT_DIR / name, reject_inline_comments=name == "units.yaml")
            for name in ("meta.yaml", "countries.yaml", "units.yaml")]
    result = validate_bundle(*data, source_hash=PDF_SHA256)
    assert result.ok, result.errors
    assert result.bundle_hash == audit["bundle_hash"]
    assert len(data[2]) == 208
    assert audit["by_kind"] == {"deadline": 22, "escalation_trigger": 13, "processing_time": 10,
        "registration_default": 1, "registration_exemption": 93, "registration_term": 2,
        "rule_param": 14, "special_regime": 4, "tariff": 22, "template": 13,
        "visa_free_regime": 10, "visa_required_regime": 4}


def test_no_approval_or_governance_policy_invented(generated):
    units = index(generated).values()
    assert all(u["confirmation_status"] != "confirmed" for u in units)
    assert all(u["verified_at"] is None and u["verified_by"] is None for u in units)
    assert all(u["review_due_at"] is None and u["owner"] == "unassigned:DEC-07" for u in units)
    assert all(u["blocked_value"]["source"] for u in units)
    assert generated[1]["publication_approved"] is False


def test_moldova_conflict_cannot_be_bypassed_via_default(generated):
    units = index(generated)
    mda = units["KG.REG.EXEMPT.MDA"]
    assert mda["value"] is None and mda["confirmation_status"] == "blocked"
    assert mda["conflict_ref"] == "SRC-04"
    assert mda["blocked_value"]["source_value"] == 90
    assert "MDA" not in units["KG.REG.DEFAULT"]["value"]["not_in_list"]
    assert units["KG.REG.TERM.MDA"]["value"]["days"] == 90
    assert units["KG.REG.TERM.UZB"]["value"]["days"] == 60


def test_all_92_registration_countries_and_exceptions_survive(generated, inputs):
    units = index(generated)
    capture, aliases, *_ = inputs
    expected = {}
    for row in capture["tables"]["registration"][:-1]:
        days = int(row["cells"][0].split()[0])
        for name in row["cells"][1].split(","):
            code = aliases[name.strip()]
            expected[code] = days
    assert len(expected) == 92
    actual = {uid.rsplit(".", 1)[-1]: unit["value"]["days"]
              for uid, unit in units.items() if unit["kind"] == "registration_exemption" and unit["value"]}
    assert actual == expected
    assert actual["GRC"] == 90 and actual["CHL"] == 60
    assert actual["DMA"] == 21 and "DOM" not in actual
    assert actual["KOR"] == 30 and "PRK" not in actual


def test_full_country_registry_is_not_limited_to_current_rule_groups(generated):
    files, _ = generated
    countries = json.loads(files["countries.yaml"])
    assert len({v for v in countries.values()}) == 249
    assert countries["KGZ"] == "KGZ" and countries["ZWE"] == "ZWE"
    assert countries["КНДР"] == "PRK" and countries["Корея"] == "KOR"
    assert countries["Македония"] == countries["Северная Македония"] == "MKD"


@pytest.mark.parametrize("product,amount", [("TS", 50), ("B", 50), ("EP", 100)])
def test_source_claimed_approval_is_not_publication_approval(generated, product, amount):
    unit = index(generated)[f"KG.FEE.SERVICE.{product}"]
    assert unit["value"]["amount"] == amount
    assert unit["confirmation_status"] == "needs_verification"
    assert unit["blocked_value"]["approval_in_source"] is True
    assert unit["blocked_value"]["publication_approval"] == "UNKNOWN"


@pytest.mark.parametrize("product", ["SW1", "SW2", "RC_WORK"])
def test_conflicting_fees_preserve_both_sources(generated, product):
    fee = index(generated)[f"KG.FEE.SERVICE.{product}"]
    assert fee["confirmation_status"] == "decision_pending" and fee["value"] is None
    assert fee["label"] == "decision" and fee["conflict_ref"] == "SRC-03"
    evidence = fee["blocked_value"]
    assert len(evidence["source_locations"]) == 4
    assert set(evidence["conflicting_source_pages"]) == {"13", "15", "82"}
    assert "$100" in evidence["source"][1]


def test_unrepresentable_conditions_are_not_fabricated(generated):
    units = index(generated)
    for uid in ("KG.VF.GCC", "KG.VF.MDV", "KG.VF.MYS", "KG.VF.CUB", "KG.VF.PRK",
                "KG.RULE.OVERSTAY_BAN", "KG.RULE.NO_REG_LAST_DAYS", "KG.VR.SIMPLIFIED_GCC_RESIDENT_TS",
                "KG.SP.CHN_IND_LONGTERM_VISA", "KG.SP.HK_MACAO"):
        assert units[uid]["value"] is None
        assert units[uid]["blocked_value"]["source"]
    for unit in units.values():
        if unit["kind"] in {"deadline", "processing_time"}:
            assert unit["value"] is None
    assert "60 дней / 60 к.д." in units["KG.DL.EP_RC_CORRECTION"]["blocked_value"]["source"][1]
    assert "30 к.д." in units["KG.DL.VISA_CORRECTION"]["blocked_value"]["source"][1]
    assert "3 р.д." in units["KG.PT.REGISTRATION"]["blocked_value"]["source"][1]
    assert "60_90" in str(units["KG.RULE.NO_REG_LAST_DAYS"]["blocked_value"]["source"])


def test_all_templates_preserved_but_not_executable(generated, inputs):
    units = index(generated)
    for template in template_sections(inputs[0]):
        unit = units[f"KG.TPL.A{template['number']:02d}"]
        assert unit["value"] is None
        assert unit["blocked_value"]["source"] == template["text"]
    assert units["KG.TPL.A08"]["conflict_ref"] == "SRC-08"
    assert units["KG.TPL.A11"]["conflict_ref"] == "SRC-07"
    assert "30" in units["KG.TPL.A08"]["blocked_value"]["source"]
    assert "EN:" in units["KG.TPL.A07"]["blocked_value"]["source"]


def test_every_record_has_provenance_and_original_decision_labels(generated):
    records = generated[1]["provenance"]
    units = index(generated)
    assert len(records) == len(units) == len({r["unit_id"] for r in records})
    assert {r["unit_id"] for r in records} == set(units)
    assert all(r["pdf_pages"] and r["capture_selector"] for r in records)
    assert "[ПРОВЕРИТЬ]" in next(r for r in records if r["unit_id"] == "KG.VF.CIS_BILATERAL")["source_labels"]


@pytest.mark.parametrize("target", ["capture.json", "aliases.json", "iso3166.json"])
def test_changed_source_snapshot_rejected_before_conversion(tmp_path, target):
    directory = tmp_path / "source"
    shutil.copytree(SOURCE_DIR, directory)
    with (directory / target).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="snapshot changed"):
        read_inputs(directory)


def test_wrong_pdf_never_gets_parsed(tmp_path):
    pdf = tmp_path / "wrong.pdf"
    pdf.write_bytes(b"not the approved source PDF")
    with pytest.raises(ValueError, match="SHA-256"):
        extract_pdf(pdf)


@pytest.mark.parametrize("table", ["registration", "deadlines", "processing_times", "service_fees", "escalation"])
def test_lost_source_row_fails_closed(inputs, table):
    capture = deepcopy(inputs[0])
    capture["tables"][table].pop()
    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_capture(capture)


def test_changed_table_cell_in_derived_conversion_rejected(inputs):
    capture, _, _, _, markdown = inputs
    changed = markdown.replace("| 8 дней | Иран |", "| 80 дней | Иран |")
    assert changed != markdown
    with pytest.raises(ValueError, match="cell mismatch"):
        compare_conversion(capture, changed)


def test_lost_explicit_exception_in_derived_b5_rejected(inputs):
    capture, _, _, _, markdown = inputs
    changed = markdown.replace("registration_exempt_days_exceptions: {Греция: 90, Чили: 60}",
                               "registration_exempt_days_exceptions: {Греция: 30, Чили: 30}")
    assert changed != markdown
    with pytest.raises(ValueError, match="B.5 differs"):
        compare_conversion(capture, changed)


def test_changed_source_template_rejected(inputs):
    capture, _, _, _, markdown = inputs
    start = markdown.index("### А.11.")
    changed = markdown[:start] + markdown[start:].replace("Работать без разрешения нельзя", "Работать можно", 1)
    with pytest.raises(ValueError, match="template mismatch"):
        compare_conversion(capture, changed)


def test_duplicate_yaml_in_source_is_not_silently_overwritten():
    with pytest.raises(ValueError):
        strict_source_yaml("a: 1\na: 2\n")


@pytest.mark.parametrize("text", ['a: [broken', 'a: !!python/object/apply:os.system [whoami]', 'a: &x [*x]'])
def test_invalid_source_yaml_reports_error_without_executing(text):
    with pytest.raises(ValueError):
        strict_source_yaml(text)


def test_builder_cli_does_not_import_runtime_connections():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c", "import sys; import scripts.build_kg_entry_bundle; "
                             "assert not any(n in sys.modules for n in "
                             "('app.config', 'app.db', 'app.main', 'sqlalchemy', 'httpx', 'fitz', 'pycountry'))"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_write_check_idempotency_and_partial_recovery(tmp_path, generated):
    files, audit = generated
    out = tmp_path / "bundle"
    assert write_or_check(out, files, audit, check=True) is False
    assert not out.exists()
    # Прерванное создание пакета: повтор безопасно дополняет только отсутствующие файлы.
    out.mkdir()
    (out / "meta.yaml").write_bytes(files["meta.yaml"])
    assert write_or_check(out, files, audit, check=False)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    assert write_or_check(out, files, audit, check=False)
    assert write_or_check(out, files, audit, check=True)
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("filename", ["units.yaml", "notes.txt"])
def test_user_files_never_silently_overwritten(tmp_path, generated, filename):
    files, audit = generated
    out = tmp_path / "bundle"
    out.mkdir()
    protected = out / filename
    protected.write_text("USER CONTENT", encoding="utf-8")
    with pytest.raises(ValueError):
        write_or_check(out, files, audit, check=False)
    assert protected.read_text(encoding="utf-8") == "USER CONTENT"
    assert not (out / "meta.yaml").exists()
    assert not out.with_name(out.name + ".audit.json").exists()


def test_existing_audit_conflict_prevents_all_writes(tmp_path, generated):
    files, audit = generated
    out = tmp_path / "bundle"
    out.with_name(out.name + ".audit.json").write_text("USER CONTENT", encoding="utf-8")
    with pytest.raises(ValueError):
        write_or_check(out, files, audit, check=False)
    assert not out.exists()


def test_build_does_not_mutate_source_inputs(inputs):
    before = deepcopy(inputs)
    first = build_bundle(*inputs)
    second = build_bundle(*inputs)
    assert first == second and inputs == before


def test_cli_readonly_check_and_new_output(tmp_path, capsys):
    assert main(["--check"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] and not result["imported"] and not result["publication_approved"]
    out = tmp_path / "new"
    assert main(["--output", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["units"] == 208
    (out / "meta.yaml").write_bytes(b"changed")
    assert main(["--output", str(out), "--check"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
