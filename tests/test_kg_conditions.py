"""Draft profile predicates: no permission decision, no mixing evidence across documents."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.knowledge.conditions import ConditionError, ConditionReview
from app.knowledge.validation import load_document
from scripts.build_kg_entry_conditions import OUTPUT, build_catalog, main as build_main
from scripts.build_kg_entry_bundle import OUTPUT_DIR, read_inputs
from scripts.kg_entry_source import json_bytes, source_yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = {"schema_version": "kg-entry-condition-facts/1"}
PREFIX = "KG.SP."


@pytest.fixture(scope="module")
def data():
    return {name: load_document(OUTPUT_DIR / f"{name}.yaml") for name in ("meta", "countries", "units")}


@pytest.fixture(scope="module")
def catalog():
    return build_catalog()


@pytest.fixture(scope="module")
def review(data, catalog):
    return ConditionReview(catalog, **data, source_hash=data["meta"]["source_hash"])


def result(review, uid, **facts):
    return next(row for row in review.evaluate({**BASE, **facts})["rules"] if row["unit_id"] == uid)


def foreign(items, complete=True):
    return {"items": items, "complete": complete}


def group(count=5, **extra):
    return {"organized": True, "participants_count": count, "all_members_country": "CHN",
            "tourism_authority_petition": True, **extra}


def gcc(**extra):
    return {"entry_passport_country": "IND", "requested_visa_type": "TS", "stay_within_one_month_verified": True,
            "residence_documents": foreign([{"country": "ARE", "kind": "resident_card"}]), **extra}


def test_catalog_reproduces_pinned_source_without_changing_bundle(catalog, data):
    assert json_bytes(catalog) == OUTPUT.read_bytes()
    assert len(catalog["rules"]) == 6 and catalog["publication_approved"] is False
    original, _ = source_yaml(read_inputs()[0])
    rules = {row["unit_id"]: row for row in catalog["rules"]}
    source = original["special"]
    assert rules[PREFIX + "UN_LP"]["source_outcome"]["stay_days"] == source["un_laissez_passer"]["days"]
    assert rules[PREFIX + "CHN_TOUR_GROUP"]["source_outcome"]["visa_inside_exception"] == "force_majeure"
    assert rules["KG.VF.GCC"]["source_outcome"]["window_days"] == original["visa_free"]["gcc"]["limit"]["window_days"]
    assert rules["KG.VF.GCC"]["source_outcome"]["work_permit_requirement"] == "unknown"
    selected = {r["unit_id"] for r in catalog["rules"]}
    assert all(u["value"] is None for u in data["units"] if u["unit_id"] in selected)


def test_empty_profile_is_unknown_for_every_rule_and_no_approval(review):
    output = review.evaluate(BASE)
    assert {r["status"] for r in output["rules"]} == {"unknown"}
    assert all(r["missing_facts"] and not r["may_quote"] for r in output["rules"])
    assert output["may_quote"] is False and output["selected_regime"] is None
    assert output["entry_eligibility_evaluated"] is False


@pytest.mark.parametrize("count,status", [(4, "not_met"), (5, "met"), (25, "met"), (26, "not_met"), (None, "unknown")])
def test_group_boundaries(review, count, status):
    row = result(review, PREFIX + "CHN_TOUR_GROUP", entry_passport_country="CHN", tour_group=group(count))
    assert row["status"] == status and row["may_quote"] is False


@pytest.mark.parametrize("extra,status", [({"organized": False}, "not_met"),
    ({"tourism_authority_petition": False}, "not_met"), ({"tourism_authority_petition": None}, "unknown"),
    ({"all_members_country": "IND"}, "not_met"), ({"all_members_country": "unknown"}, "unknown")])
def test_group_requires_organization_membership_and_petition(review, extra, status):
    assert result(review, PREFIX + "CHN_TOUR_GROUP", entry_passport_country="CHN", tour_group=group(**extra))["status"] == status


def test_country_rejection_is_distinct_from_missing_profile_fields(review):
    row = result(review, PREFIX + "CHN_TOUR_GROUP", entry_passport_country="IND")
    assert row["status"] == "not_met" and row["missing_facts"] == []
    assert next(c for c in row["checks"] if c["predicate"] == "organized_tour_group")["status"] == "unknown"


@pytest.mark.parametrize("issuer", ["USA", "GBR", "SCHENGEN"])
def test_foreign_visa_explicit_verified_threshold(review, issuer):
    row = result(review, PREFIX + "CHN_IND_LONGTERM_VISA", entry_passport_country="IND",
                 foreign_visas=foreign([{"issuer": issuer, "over_three_years_verified": True}]))
    assert row["status"] == "met" and "three_year_duration_basis_needs_review" in row["unresolved"]


def test_visa_issuer_and_duration_cannot_be_taken_from_different_visas(review):
    items = [{"issuer": "USA", "over_three_years_verified": False},
             {"issuer": "other", "over_three_years_verified": True}]
    row = result(review, PREFIX + "CHN_IND_LONGTERM_VISA", entry_passport_country="CHN", foreign_visas=foreign(items))
    assert row["status"] == "not_met"


@pytest.mark.parametrize("items,complete,status", [([], True, "not_met"), ([], False, "unknown"),
    ([], None, "unknown"), ([{"issuer": "USA"}], True, "unknown"),
    ([{"issuer": "USA", "over_three_years_verified": True}], False, "met"),
    ([{"issuer": "USA", "over_three_years_verified": False}], False, "unknown")])
def test_incomplete_document_list_has_three_valued_semantics(review, items, complete, status):
    row = result(review, PREFIX + "CHN_IND_LONGTERM_VISA", entry_passport_country="CHN", foreign_visas=foreign(items, complete))
    assert row["status"] == status
    assert bool(row["missing_facts"]) == (status == "unknown")


def test_hk_macao_permanent_residence_is_not_nationality(review):
    row = result(review, PREFIX + "HK_MACAO", entry_passport_country="CHN",
                 residence_documents=foreign([{"country": "HKG", "permanent": True}]))
    assert row["status"] == "met"
    row = result(review, PREFIX + "HK_MACAO", entry_passport_country="HKG",
                 residence_documents=foreign([{"country": "HKG", "permanent": False},
                                              {"country": "CHN", "permanent": True}]))
    assert row["status"] == "not_met"


def test_gcc_resident_and_citizen_are_distinct(review):
    facts = gcc()
    assert result(review, "KG.VR.SIMPLIFIED_GCC_RESIDENT_TS", **facts)["status"] == "met"
    assert result(review, "KG.VF.GCC", **facts)["status"] == "not_met"
    assert result(review, "KG.VF.GCC", entry_passport_country="ARE")["status"] == "met"
    assert result(review, "KG.VR.SIMPLIFIED_GCC_RESIDENT_TS", **gcc(entry_passport_country="ARE"))["status"] == "not_met"


@pytest.mark.parametrize("country", ["ARE", "SAU", "KWT", "QAT", "BRN", "OMN", "BHR"])
def test_explicit_residence_countries_include_brunei(review, country):
    facts = gcc(residence_documents=foreign([{"country": country, "kind": "residence_permit"}]))
    assert result(review, "KG.VR.SIMPLIFIED_GCC_RESIDENT_TS", **facts)["status"] == "met"


def test_residence_country_and_kind_cannot_be_taken_from_different_documents(review):
    docs = [{"country": "ARE", "kind": "other"}, {"country": "USA", "kind": "resident_card"}]
    assert result(review, "KG.VR.SIMPLIFIED_GCC_RESIDENT_TS", **gcc(residence_documents=foreign(docs)))["status"] == "not_met"


@pytest.mark.parametrize("extra,status", [({"requested_visa_type": "B"}, "not_met"),
    ({"stay_within_one_month_verified": False}, "not_met"), ({"stay_within_one_month_verified": None}, "unknown")])
def test_tourist_visa_and_month_limit_are_both_required(review, extra, status):
    assert result(review, "KG.VR.SIMPLIFIED_GCC_RESIDENT_TS", **gcc(**extra))["status"] == status


def test_un_document_does_not_need_invented_nationality(review):
    assert result(review, PREFIX + "UN_LP", document_type="un_lp")["status"] == "met"
    assert result(review, PREFIX + "UN_LP", document_type="ordinary")["status"] == "not_met"


@pytest.mark.parametrize("facts", [
    {"tour_group": {"participants_count": True}}, {"tour_group": {"participants_count": 5.5}},
    {"tour_group": {"organized": 1}}, {"foreign_visas": {"items": [{"over_three_years_verified": "yes"}]}},
    {"residence_documents": {"items": [], "complete": 1}}, {"stay_days": 30},
    {"stay_within_one_month_verified": 1}, {"passport_number": "DO_NOT_ECHO_PRIVATE_INPUT"},
    {"document_type": "unrecognized-new-document"},
])
def test_bad_facts_are_refused_without_echoing_input(review, facts):
    with pytest.raises(ConditionError, match="^invalid_facts$"):
        review.evaluate({**BASE, **facts})


def test_unknown_country_cannot_silently_be_used_as_a_nonmatch(review):
    for facts in ({"entry_passport_country": "ZZZ"}, {"residence_documents": foreign([{"country": "ZZZ"}])}):
        with pytest.raises(ConditionError, match="^unknown_fact_country$"):
            review.evaluate({**BASE, **facts})


@pytest.mark.parametrize("change,code", [
    (lambda c: c.update(bundle_hash="0" * 64), "catalog_source_mismatch"),
    (lambda c: c.update(source_hash="0" * 64), "catalog_source_mismatch"),
    (lambda c: c.update(publication_approved=True), "invalid_catalog"),
    (lambda c: c["rules"][0].update(unit_id="KG.SP.DOES_NOT_EXIST"), "invalid_rule_reference"),
    (lambda c: c["rules"][0]["all"][0].update(type="execute_code"), "invalid_catalog"),
    (lambda c: c["rules"][0]["all"][0].update(countries=["ZZZ"]), "unknown_catalog_country"),
])
def test_bad_catalog_cannot_run(data, catalog, change, code):
    changed = deepcopy(catalog)
    change(changed)
    with pytest.raises(ConditionError, match=code):
        ConditionReview(changed, **data, source_hash=data["meta"]["source_hash"])


def test_duplicate_rule_reference_and_inverted_group_bounds(data, catalog):
    changed = deepcopy(catalog)
    other = deepcopy(changed["rules"][0])
    other["unresolved"].append("different_record_same_id")
    changed["rules"].append(other)
    with pytest.raises(ConditionError, match="invalid_rule_reference"):
        ConditionReview(changed, **data, source_hash=data["meta"]["source_hash"])
    changed = deepcopy(catalog)
    clause = next(c for r in changed["rules"] for c in r["all"] if c["type"] == "organized_tour_group")
    clause["minimum"] = 26
    with pytest.raises(ConditionError, match="invalid_group_range"):
        ConditionReview(changed, **data, source_hash=data["meta"]["source_hash"])


def test_input_and_output_are_isolated(data, catalog):
    mutable_data, mutable_catalog = deepcopy(data), deepcopy(catalog)
    review = ConditionReview(mutable_catalog, **mutable_data, source_hash=data["meta"]["source_hash"])
    facts = {**BASE, "document_type": "un_lp"}
    expected = review.evaluate(facts)
    mutable_catalog["rules"].clear()
    mutable_data["units"].clear()
    reply = review.evaluate(facts)
    reply["rules"][0]["source_outcome"].clear()
    reply["rules"][0]["checks"].clear()
    assert review.evaluate(facts) == expected and facts == {**BASE, "document_type": "un_lp"}


def test_builder_check_refuses_changed_output_and_never_writes_on_check(tmp_path, capsys):
    target = tmp_path / "new" / "conditions.json"
    assert build_main(["--check", "--output", str(target)]) == 1 and not target.parent.exists()
    assert build_main(["--output", str(target)]) == 0
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    assert build_main(["--check", "--output", str(target)]) == 0
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    target.write_bytes(b"changed by user")
    assert build_main(["--output", str(target)]) == 1 and target.read_bytes() == b"changed by user"
    capsys.readouterr()


def test_cli_actual_pdf_read_only_and_private_error(tmp_path):
    pdf = ROOT.parent / "Kyrgyzstan-visa-knowledge-base-v1.1.pdf"
    if not pdf.is_file():
        pytest.skip("Original PDF outside repository")
    facts = ROOT / "tests/fixtures/kg_entry/synthetic_condition_facts.json"
    paths = [OUTPUT, facts, *OUTPUT_DIR.iterdir()]
    before = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths}
    def invoke(path, source=pdf):
        return subprocess.run([sys.executable, "-X", "utf8", "scripts/review_kg_conditions.py", str(OUTPUT_DIR),
                               "--source", str(source), "--facts", str(path)], cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", timeout=30)
    first = invoke(facts)
    assert first.returncode == 0 and invoke(facts).stdout == first.stdout
    states = {r["status"] for r in json.loads(first.stdout)["rules"]}
    assert states == {"met", "not_met", "unknown"}
    private = tmp_path / "bad.json"
    private.write_text(json.dumps({**BASE, "passport_number": "DO_NOT_ECHO_PRIVATE_INPUT"}), encoding="utf-8")
    failed = invoke(private)
    assert failed.returncode == 1 and "DO_NOT_ECHO_PRIVATE_INPUT" not in failed.stdout + failed.stderr
    assert json.loads(failed.stdout)["code"] == "invalid_facts"
    wrong = tmp_path / "wrong.pdf"
    wrong.write_bytes(b"wrong source")
    assert invoke(facts, wrong).returncode == 1
    assert {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in paths} == before


def test_evaluator_has_no_runtime_database_network_or_pdf_imports():
    code = "import sys; import app.knowledge.conditions; assert not any(n in sys.modules for n in ['app.config','sqlalchemy','httpx','requests','fitz'])"
    ran = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, timeout=30)
    assert ran.returncode == 0, ran.stderr
