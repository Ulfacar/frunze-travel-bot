"""Country review lookup: provenance, incomplete facts, isolation and safe CLI."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.knowledge.country_index import CountryIndexError, CountryRuleIndex
from app.knowledge.validation import load_document
from tests.test_kg_entry_validation import SOURCE_HASH, bundle_data, unit

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/kg_entry"


def build(data=None):
    return CountryRuleIndex(*(data or bundle_data()), source_hash=SOURCE_HASH)


def by_kind(result, kind):
    return result["country_links"][kind]


@pytest.fixture(scope="module")
def real():
    directory = ROOT / "knowledge/kg_entry/draft-v1.1"
    data = [load_document(directory / f"{name}.yaml") for name in ("meta", "countries", "units")]
    # Отдельный CLI smoke ниже проверяет фактический PDF; здесь проверяем сам снимок.
    return CountryRuleIndex(*data, source_hash=data[0]["source_hash"])


@pytest.mark.parametrize("query", ["RUS", "rus", " rUs ", "ＲＵＳ", "Russia", "  RUSSIA\t"])
def test_codes_and_explicit_aliases_share_bundle_normalization(query):
    result = build().lookup(query)
    assert result["country_iso3"] == "RUS" and result["status"] == "found"
    assert by_kind(result, "visa_free_regime")[0]["value"]["days"] == 10
    assert result["source_hash"] == SOURCE_HASH and result["version_label"] == "test-only"
    assert result["selected_regime"] is None and result["may_quote"] is False


def test_real_russian_alias_moldova_conflict_and_registration_term_are_separate(real):
    result = real.lookup("  мОлДоВа ")
    assert result["country_iso3"] == "MDA"
    assert by_kind(result, "visa_free_regime")[0]["value"]["days"] == 90
    exemption = by_kind(result, "registration_exemption")[0]
    assert exemption["value"] is None and exemption["conflict_ref"] == "SRC-04"
    assert exemption["confirmation_status"] == "blocked" and "source_conflict" in exemption["findings"]
    assert by_kind(result, "registration_term")[0]["value"] == {"days": 90}
    assert by_kind(result, "registration_default") == []
    for query, days in (("Греция", 90), ("Чили", 60)):
        found = real.lookup(query)
        assert by_kind(found, "registration_exemption")[0]["value"]["days"] == days
        assert by_kind(found, "visa_free_regime")[0]["value"]["days"] == 30


def test_default_registration_is_only_explicit_country_membership():
    index = build()
    assert by_kind(index.lookup("RUS"), "registration_default")[0]["association"] == "explicit_not_in_list"
    result = index.lookup("IND")
    assert by_kind(result, "registration_default") == []
    assert "registration_coverage_missing" in result["findings"]
    assert result["source_fallbacks"][0]["unit_id"] == "KG.VR.GENERAL"
    assert result["selected_regime"] is None


@pytest.mark.parametrize("query", ["ZZZ", "RU", "Rusia", "Republic not supplied", "Роcсия"])
def test_unknown_input_does_not_fall_back_or_fuzzy_match(query):
    result = build().lookup(query)
    assert result["status"] == "unknown_country" and result["country_iso3"] is None
    assert not any(result["country_links"].values())
    assert result["source_fallbacks"] == [] and result["country_independent"] == []


@pytest.mark.parametrize("query", [None, [], "", " \t", "x" * 201, "\ud800"])
def test_bad_query_has_bounded_error(query):
    with pytest.raises(CountryIndexError, match="^invalid_country_query$"):
        build().lookup(query)


@pytest.mark.parametrize("document", ["diplomatic", "service", "un_lp", "stateless", "unknown"])
def test_document_is_not_treated_as_ordinary_eligibility(document):
    result = build().lookup("RUS", document_type=document)
    assert result["document_type"] == document
    assert "document_review_required" in result["findings"]
    assert result["applicability_evaluated"] is False and result["selected_regime"] is None
    assert all(not u["may_quote"] for rows in result["country_links"].values() for u in rows)


@pytest.mark.parametrize("document", [[], None, "invented"])
def test_unknown_document_enum_is_rejected(document):
    with pytest.raises(CountryIndexError, match="^invalid_document_type$"):
        build().lookup("RUS", document_type=document)


def test_real_unresolved_country_hints_never_restore_blocked_values(real):
    for code in ("CUB", "MYS", "MDV", "PRK"):
        ref = by_kind(real.lookup(code), "visa_free_regime")[0]
        assert ref["evidence_only"] is True and ref["value"] is None
        assert "value_missing" in ref["findings"]
    ref = by_kind(real.lookup("PAK"), "visa_required_regime")[0]
    assert ref["evidence_only"] is True and ref["value"] is None
    assert "blocked_value" not in ref  # нельзя спутать candidate с рабочим value
    assert "KG.SP.CHN_TOUR_GROUP" in real.summary()["unmapped_unit_ids"]
    assert "KG.VF.GCC" in real.summary()["unmapped_unit_ids"]


def test_special_conditions_are_kept_and_country_independent_is_not_all_countries():
    data = bundle_data()
    special = next(u for u in data[2] if u["kind"] == "special_regime")
    special["value"]["applies_to"]["condition"] = "explicit additional evidence required"
    data[2].append(unit("KG.SP.DOC", "special_regime", {"days": 5, "applies_to": {"document_type": "un_lp"}}))
    index = build(data)
    found = index.lookup("CHN")
    assert by_kind(found, "special_regime")[0]["value"]["applies_to"]["condition"] == "explicit additional evidence required"
    assert found["country_independent"][0]["value"]["applies_to"] == {"document_type": "un_lp"}
    assert by_kind(index.lookup("IND"), "special_regime") == []


def test_multiple_candidates_are_preserved_without_last_write_wins():
    data = bundle_data()
    for suffix, scope in (("A", "all_types"), ("B", "business_tourist")):
        data[2].append(unit(f"KG.VR.{suffix}", "visa_required_regime", {
            "countries": ["CHN"], "procedure": "simplified", "scope": scope, "gknb_approval": False}))
    rows = by_kind(build(data).lookup("CHN"), "visa_required_regime")
    assert [r["unit_id"] for r in rows] == ["KG.VR.A", "KG.VR.B"]


def test_snapshot_is_order_independent_and_mutation_isolated():
    data = bundle_data()
    saved = deepcopy(data)
    index = build(data)
    expected = index.lookup("RUS")
    assert data == saved
    rearranged = (data[0], dict(reversed(list(data[1].items()))), list(reversed(data[2])))
    assert build(rearranged).lookup("RUS") == expected
    data[0]["version_label"] = "changed"
    data[1]["Russia"] = "CHN"
    data[2][0]["value"]["days"] = 999
    output = index.lookup("RUS")
    by_kind(output, "visa_free_regime")[0]["value"]["countries"].clear()
    index.summary()["by_kind"].clear()
    assert index.lookup("RUS") == expected


def test_invalid_bundle_alias_overlap_and_source_never_produce_partial_index():
    data = bundle_data()
    with pytest.raises(CountryIndexError, match="invalid_bundle"):
        CountryRuleIndex(*data, source_hash="0" * 64)
    data[1]["  RUSSIA "] = "CHN"
    with pytest.raises(CountryIndexError, match="invalid_bundle"):
        build(data)
    data = bundle_data()
    data[2].append(deepcopy(data[2][0]))
    data[2][-1]["unit_id"] = "KG.VF.OVERLAP"
    with pytest.raises(CountryIndexError, match="invalid_bundle"):
        build(data)


@pytest.mark.parametrize("hint,code", [(["ZZZ"], "invalid_evidence_country"), ([], "invalid_evidence_country"),
                                        (["RUS", "Russia"], "duplicate_evidence_country"),
                                        ("all_others", "invalid_evidence_country"), ([True], "invalid_evidence_country")])
def test_evidence_hints_are_checked_even_though_bundle_evidence_is_open(hint, code):
    data = bundle_data()
    data[2].append(unit("KG.VR.PENDING", "visa_required_regime", None,
                       confirmation_status="needs_verification", blocked_value={"candidate": {"countries": hint}}))
    with pytest.raises(CountryIndexError, match=code):
        build(data)


def test_real_index_accounts_for_every_country_related_unit_once_or_more(real):
    summary = real.summary()
    assert summary["countries"] == 249 and summary["country_units"] == 114
    assert summary["other_units"] == 94
    covered = set(summary["unmapped_unit_ids"] + summary["source_fallback_ids"] + summary["country_independent_ids"])
    countries = json.loads((ROOT / "knowledge/kg_entry/draft-v1.1/countries.yaml").read_text(encoding="utf-8"))
    for code in set(countries.values()):
        result = real.lookup(code)
        assert result["may_quote"] is False and result["publication_approved"] is False
        covered.update(u["unit_id"] for rows in result["country_links"].values() for u in rows)
    assert len(covered) == 114


def test_conflicting_evidence_country_hints_are_not_silently_prioritized():
    data = bundle_data()
    pending = unit("KG.VR.PENDING", "visa_required_regime", None,
                   confirmation_status="needs_verification",
                   blocked_value={"country_iso3": "CHN", "candidate": {"countries": ["IND"]}})
    data[2].append(pending)
    with pytest.raises(CountryIndexError, match="^conflicting_evidence_countries$"):
        build(data)
    pending["blocked_value"]["candidate"]["countries"] = ["China"]
    refs = by_kind(build(data).lookup("CHN"), "visa_required_regime")
    assert len(refs) == 1 and refs[0]["value"] is None and refs[0]["evidence_only"] is True


def invoke(*args):
    return subprocess.run([sys.executable, "-X", "utf8", "scripts/review_kg_country.py", *map(str, args)],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)


def test_cli_read_only_repeatable_and_wrong_source(tmp_path):
    directory, source = FIX / "synthetic_bundle", FIX / "synthetic_source.txt"
    before = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in [*directory.iterdir(), source]}
    args = (directory, "--source", source, "--country", "MDA")
    result = invoke(*args)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "found"
    assert invoke(*args).stdout == result.stdout
    assert invoke(directory, "--source", source, "--summary").returncode == 0
    bad = tmp_path / "wrong.txt"
    bad.write_bytes(b"wrong source")
    failed = invoke(directory, "--source", bad, "--country", "MDA")
    assert failed.returncode == 1 and json.loads(failed.stdout)["ok"] is False
    assert {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in before} == before


def test_cli_real_pdf_when_available():
    pdf = ROOT.parent / "Kyrgyzstan-visa-knowledge-base-v1.1.pdf"
    if not pdf.is_file():
        pytest.skip("Original PDF outside repository")
    result = invoke(ROOT / "knowledge/kg_entry/draft-v1.1", "--source", pdf, "--summary")
    assert result.returncode == 0 and json.loads(result.stdout)["country_units"] == 114


def test_module_does_not_import_runtime_database_or_network():
    command = "import sys; import app.knowledge.country_index; assert not any(n in sys.modules for n in ['app.config','sqlalchemy','httpx','requests','fitz'])"
    result = subprocess.run([sys.executable, "-c", command], cwd=ROOT, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
