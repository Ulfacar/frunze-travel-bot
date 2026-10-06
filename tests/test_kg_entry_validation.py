"""E5-02A: синтетические правила, не визовая консультация/утверждённая база."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
import yaml

from app.knowledge.bundle import country_registry, preflight_bundle, validate_bundle
from app.knowledge.bundle_schema import META_SCHEMA, UNITS_SCHEMA, VALUE_SCHEMAS
from app.knowledge.slots import SlotContext, slots_schema, validate_slots
from app.knowledge.validation import InvalidDocument, load_document
from scripts.validate_kg_entry import main

COUNTRIES = {"Russia": "RUS", "Greece": "GRC", "Chile": "CHL", "Moldova": "MDA", "China": "CHN", "India": "IND"}
CONTEXT = SlotContext(frozenset(COUNTRIES.values()), date(2026, 10, 6))
SOURCE = b"SYNTHETIC FIXTURE ONLY. Not a legal source.\n"
SOURCE_HASH = hashlib.sha256(SOURCE).hexdigest()


def questionnaire(**extra):
    return {"schema_version": "kg-entry-slots/1", **extra}


def handoff():
    return questionnaire(citizenship=["RUS"], document_type="ordinary", current_location="abroad",
                         purpose="tourism", entry_date="2026-11-01", exit_date="2026-11-10", client_type="b2c",
                         violations={"overstay": False, "deportation_or_ban": False}, previous_refusals_kg="unknown",
                         family="not_applicable", previous_visits={"was_in_kg": False, "intervals": []},
                         inviting_party={"exists": "not_applicable"})


def unit(uid, kind, value, **extra):
    return {"unit_id": uid, "kind": kind, "title": "Synthetic test rule", "section": "TEST", "page": "1",
            "source_ref": "Synthetic fixture, unverified", "label": "none", "confirmation_status": "confirmed",
            "value": value, "value_schema_version": 1, "owner": "test-author", **extra}


def bundle_data():
    meta = {"schema_version": "kg-entry-bundle/1", "set_code": "kg_entry", "version_label": "test-only",
            "source_document": "synthetic_source.txt", "source_hash": SOURCE_HASH,
            "prepared_by": "test-author", "prepared_at": "2026-10-06T12:00:00+06:00"}
    units = [
        unit("KG.VF.TEST", "visa_free_regime", {"days": 10, "window_days": 30,
             "work_needs_unified_permit": True, "countries": ["RUS", "GRC", "CHL", "MDA"]}),
        unit("KG.REG.DEFAULT", "registration_default", {"deadline_working_days_from_border": 4, "not_in_list": ["RUS"]}),
        unit("KG.REG.EXEMPT.GRC", "registration_exemption", {"days": 17}),
        unit("KG.REG.EXEMPT.CHL", "registration_exemption", {"days": 12}),
        unit("KG.REG.EXEMPT.MDA", "registration_exemption", None, confirmation_status="blocked",
             blocked_value={"source_value": {"days": 99}, "note": "Synthetic conflict"}, conflict_ref="TEST-SRC-04"),
        unit("KG.REG.TERM.MDA", "registration_term", {"days": 21}),
        unit("KG.SP.TEST", "special_regime", {"days": 8, "applies_to": {"countries": ["CHN"]}}),
        unit("KG.VR.GENERAL", "visa_required_regime", {"procedure": "general", "scope": None,
                                                     "gknb_approval": True, "countries": "all_others"}),
        unit("KG.RULE.TEST", "rule_param", {"value": False, "unit": "bool"}),
        unit("KG.DL.TEST", "deadline", {"value": 3, "unit": "working_days", "anchor": "entry_date",
             "direction": "before", "timezone": "Asia/Bishkek", "boundary_inclusive": True, "shift_from_nonworking": "none"}),
        unit("KG.PT.TEST", "processing_time", {"standard_wd": 7, "anchor": "full_package"}),
        unit("KG.FEE.SERVICE.TEST", "tariff", None, label="decision", confirmation_status="decision_pending",
             blocked_value={"amount": 123, "source_locations": ["TEST-A", "TEST-B"]}),
        unit("KG.TPL.TEST", "template", {"lang": "ru", "text": "Stay: {days}", "placeholders": ["days"]}),
        unit("KG.ESC.TEST", "escalation_trigger", {"condition": "passport_expired", "action": "manager_review"}),
    ]
    return meta, deepcopy(COUNTRIES), units


def validate_data(data):
    return validate_bundle(*data, source_hash=SOURCE_HASH)


def find_unit(data, kind):
    return next(u for u in data[2] if u["kind"] == kind)


def write_bundle(tmp_path):
    meta, countries, units = bundle_data()
    root = tmp_path / "bundle"
    root.mkdir()
    for name, data in (("meta", meta), ("countries", countries), ("units", units)):
        (root / f"{name}.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    source = tmp_path / "source.txt"
    source.write_bytes(SOURCE)
    return root, source


def codes(report):
    return {i.code for i in report.errors}


def test_schema_drafts_valid():
    for schema in [slots_schema(), slots_schema("handoff"), META_SCHEMA, UNITS_SCHEMA, *VALUE_SCHEMAS.values()]:
        Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("value", [False, True, "unknown", "not_applicable"])
def test_four_state_values_preserved(value):
    data = questionnaire(tickets_bought=value)
    result = validate_slots(data, context=CONTEXT)
    assert result.ok
    assert result.prepared_slots["tickets_bought"] == value


def test_collecting_vs_handoff_and_no_input_mutation():
    minimal = questionnaire()
    assert validate_slots(minimal, context=CONTEXT).prepared_slots == minimal
    assert not validate_slots(minimal, context=CONTEXT, profile="handoff").ok
    assert validate_slots(handoff(), context=CONTEXT, profile="handoff").ok
    data = handoff()
    data["contact"] = {"name": "PRIVATE_NAME", "phone": "+996555000111"}
    original = deepcopy(data)
    result = validate_slots(data, context=CONTEXT)
    assert result.ok and "contact" not in result.prepared_slots
    assert data == original
    assert "PRIVATE_NAME" not in json.dumps(result.summary())
    result.prepared_slots["citizenship"].append("GRC")
    assert data == original


@pytest.mark.parametrize("fields", [
    {"tickets_bought": None}, {"citizenship": None}, {"tickets_bought": 0}, {"tickets_bought": "false"},
    {"entry_date": "2026-02-30"}, {"entry_date": "2026-2-01"}, {"contact": {"phone": "PRIVATE_PHONE"}},
    {"schema_version": "wrong"}, {"citizenship": ["RUS", "RUS"]}, {"citizenship": ["RU"]},
    {"citizenship": ["RUS", "GRC"]}, {"current_location": "in_kg"},
    {"current_location": "abroad", "in_kg_since": "2026-01-01"},
    {"current_basis_in_kg": "visa"}, {"entry_point": "other_land"},
    {"previous_visits": {"was_in_kg": True}},
    {"previous_visits": {"was_in_kg": False, "intervals": [{"entry_date": "2026-01-01", "exit_date": "open"}]}},
    {"violations": {"overstay": False, "deportation_or_ban": True}},
    {"inviting_party": {"exists": True}}, {"inviting_party": {"exists": False, "name": "PRIVATE_NAME"}},
    {"purpose": "work_hire"}, {"purpose": "investor"}, {"extra_field": "PRIVATE_SECRET"},
    {"stop_factors": []}, {"decision": {}},
])
def test_invalid_questionnaires(fields):
    result = validate_slots(questionnaire(**fields), context=CONTEXT)
    assert not result.ok
    assert result.prepared_slots is None
    assert "PRIVATE_" not in json.dumps(result.summary())


@pytest.mark.parametrize("fields,expected", [
    ({"entry_date": "2026-11-10", "exit_date": "2026-11-09"}, "semantic.date_order"),
    ({"citizenship": ["RUS"], "entry_passport_country": "GRC"}, "semantic.passport_citizenship"),
    ({"citizenship": ["ZZZ"]}, "semantic.unknown_country"),
    ({"residence_country": "ZZZ"}, "semantic.unknown_country"),
    ({"entry_point": "other_land", "entry_point_other": "   "}, "semantic.blank_entry_point"),
    ({"previous_visits": {"was_in_kg": True, "history_complete": False,
      "intervals": [{"entry_date": "2026-10-01", "exit_date": "2026-09-30"}]}}, "semantic.date_order"),
    ({"previous_visits": {"was_in_kg": True, "history_complete": True, "intervals": [
        {"entry_date": "2026-01-01", "exit_date": "open"},
        {"entry_date": "2026-02-01", "exit_date": "open"}]}}, "semantic.multiple_open_intervals"),
])
def test_semantic_slot_rejection(fields, expected):
    assert expected in codes(validate_slots(questionnaire(**fields), context=CONTEXT))


def test_expiry_is_computed_flag_not_rejection_and_today_is_explicit():
    old = validate_slots(questionnaire(passport_expiry="2026-10-05"), context=CONTEXT)
    current = validate_slots(questionnaire(passport_expiry="2026-10-06"), context=CONTEXT)
    assert old.ok and old.stop_factors == ["passport_expired"]
    assert current.ok and current.stop_factors == []
    assert "stop_factors" not in old.prepared_slots


def test_eligibility_warning_retains_value_without_inventing_rule():
    data = questionnaire(citizenship=["RUS"], gcc_or_brunei_residence=False)
    result = validate_slots(data, context=CONTEXT)
    assert result.ok and result.warnings[0].code == "semantic.eligibility_unknown"
    assert result.prepared_slots["gcc_or_brunei_residence"] is False
    result = validate_slots(data, context=SlotContext(CONTEXT.countries, CONTEXT.today, frozenset({"CHN"})))
    assert result.ok and result.warnings[0].code == "semantic.eligibility_mismatch"


def test_valid_bundle_all_kinds_preserves_blocked_values_and_stable_hash():
    data = bundle_data()
    before = deepcopy(data)
    result = validate_data(data)
    assert result.ok, result.errors
    assert data == before
    assert result.status_counts == {"blocked": 1, "confirmed": 12, "decision_pending": 1}
    assert result.summary()["imported"] is False
    assert len(result.bundle_hash) == 64
    reverse = deepcopy(data)
    reverse[2].reverse()
    find_unit(reverse, "visa_free_regime")["value"]["countries"].reverse()
    assert validate_data(reverse).bundle_hash == result.bundle_hash
    indexed = {u["unit_id"]: u for u in result.normalized_bundle["units"]}
    assert indexed["KG.REG.EXEMPT.MDA"]["value"] is None
    assert indexed["KG.REG.EXEMPT.MDA"]["blocked_value"]["source_value"]["days"] == 99
    assert indexed["KG.REG.EXEMPT.GRC"]["value"]["days"] == 17
    assert indexed["KG.REG.EXEMPT.CHL"]["value"]["days"] == 12


def test_alias_resolution_and_registry_collision():
    data = bundle_data()
    find_unit(data, "visa_free_regime")["value"]["countries"][0] = "  russia  "
    assert validate_data(data).bundle_hash == validate_data(bundle_data()).bundle_hash
    data[1][" RUSSIA "] = "GRC"
    assert "semantic.country_alias" in codes(validate_data(data))
    with pytest.raises(InvalidDocument):
        country_registry({"RUS": "GRC", "Russia": "RUS"})


@pytest.mark.parametrize("kind,field,value,expected", [
    ("visa_free_regime", "days", True, "schema.type"),
    ("visa_free_regime", "days", 31, "semantic.window"),
    ("visa_free_regime", "countries", ["ZZZ"], "semantic.unknown_country"),
    ("visa_free_regime", "countries", ["RUS", "Russia"], "semantic.duplicate_country"),
    ("visa_free_regime", "registration_exempt_days", 30, "schema.additionalProperties"),
    ("registration_default", "not_in_list", [], "semantic.registration_missing"),
    ("registration_default", "not_in_list", ["RUS", "MDA"], "semantic.registration_conflict"),
    ("deadline", "timezone", "UTC", "schema.const"),
    ("deadline", "value", 0, "schema.minimum"),
    ("deadline", "anchor", None, "schema.type"),
    ("processing_time", "standard_wd", -1, "schema.minimum"),
    ("template", "text", "Stay: 30 days", "semantic.template_literals"),
    ("template", "placeholders", ["other"], "semantic.template_literals"),
    ("rule_param", "value", 1, "semantic.parameter_type"),
])
def test_value_schema_and_coverage_errors(kind, field, value, expected):
    data = bundle_data()
    find_unit(data, kind)["value"][field] = value
    assert expected in codes(validate_data(data))


@pytest.mark.parametrize("unit_name,field,value,expected", [
    ("KG.VF.TEST", "value", None, "semantic.missing_value"),
    ("KG.VF.TEST", "label", "verify", "semantic.confirmation_conflict"),
    ("KG.VF.TEST", "unit_id", "KG.SP.WRONG", "semantic.unit_id"),
    ("KG.REG.EXEMPT.MDA", "value", {"days": 90}, "semantic.blocked_value"),
    ("KG.REG.EXEMPT.MDA", "blocked_value", None, "semantic.blocked_value"),
    ("KG.REG.EXEMPT.MDA", "conflict_ref", None, "semantic.blocked_value"),
    ("KG.REG.EXEMPT.MDA", "confirmation_status", "confirmed", "semantic.confirmation_conflict"),
    ("KG.FEE.SERVICE.TEST", "value", {"amount": 100, "currency": "USD", "per": "person", "component": "service"}, "semantic.blocked_value"),
    ("KG.FEE.SERVICE.TEST", "confirmation_status", "confirmed", "semantic.confirmation_conflict"),
    ("KG.VF.TEST", "verified_by", "test-reviewer", "semantic.verification_pair"),
])
def test_status_metadata_contradictions(unit_name, field, value, expected):
    data = bundle_data()
    next(u for u in data[2] if u["unit_id"] == unit_name)[field] = value
    result = validate_data(data)
    assert expected in codes(result)
    assert result.normalized_bundle is None and result.bundle_hash is None


def test_duplicate_ids_overlap_dates_hash_and_missing_exception():
    data = bundle_data()
    data[2].append(deepcopy(data[2][0]))
    assert {"semantic.duplicate_unit", "semantic.regime_overlap"} <= codes(validate_data(data))
    data = bundle_data()
    data[2][:] = [u for u in data[2] if u["unit_id"] != "KG.REG.EXEMPT.GRC"]
    assert "semantic.registration_missing" in codes(validate_data(data))
    data = bundle_data()
    data[2][0].update(effective_from="2026-10-06", effective_to="2026-10-05")
    assert "semantic.date_order" in codes(validate_data(data))
    assert "semantic.source_hash" in codes(validate_bundle(*bundle_data(), source_hash="0" * 64))


@pytest.mark.parametrize("text,code", [
    ('a: 1\na: 2\n', "syntax.duplicate_key"),
    ('{"a": 1, "a": 2}', "syntax.duplicate_key"),
    ('a: &x [1]\nb: *x\n', "syntax.reference"),
    ('a: !!python/object/apply:os.system [whoami]\n', "syntax.reference"),
    ('a: .nan\n', "syntax.non_finite"),
    ('a: .inf\n', "syntax.non_finite"),
    ('a: 1 # exception: 90\n', "syntax.inline_comment"),
    ('a: "# literal" # exception\n', "syntax.inline_comment"),
    ('a: | # exception\n  content\n', "syntax.inline_comment"),
    ('a: >- # exception\n  content\n', "syntax.inline_comment"),
    ('---\na: 1\n---\na: 2\n', "syntax.yaml"),
    ('1: wrong key\n', "syntax.key_type"),
    ('a: [broken\n', "syntax.yaml"),
    ('[' * 40 + '0' + ']' * 40, "syntax.limit"),
])
def test_strict_parser_rejects_lossy_or_unsafe_inputs(tmp_path, text, code):
    path = tmp_path / "units.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(InvalidDocument) as caught:
        load_document(path, reject_inline_comments=True)
    assert caught.value.issue.code == code
    assert caught.value.issue.location.startswith("units.yaml")


@pytest.mark.parametrize("text,expected", [
    ('# comment\na: "# literal"\nb: abc#literal\n', {"a": "# literal", "b": "abc#literal"}),
    ('a: |\n  Text # part of scalar\n', {"a": "Text # part of scalar\n"}),
    ('a: 2026-10-06\nb: false\nc: unknown\nd: on\n', {"a": "2026-10-06", "b": False, "c": "unknown", "d": "on"}),
    ('a: 012\nb: 0x10\nc: 1:20\nd: 1e2\n', {"a": "012", "b": "0x10", "c": "1:20", "d": 100.0}),
    ('{"a": true, "b": null}', {"a": True, "b": None}),
])
def test_strict_parser_preserves_data(tmp_path, text, expected):
    path = tmp_path / "units.yaml"
    path.write_text(text, encoding="utf-8")
    assert load_document(path, reject_inline_comments=True) == expected


def test_limits_and_python_api_invalid_types(tmp_path):
    path = tmp_path / "huge.yaml"
    path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(InvalidDocument) as caught:
        load_document(path)
    assert caught.value.issue.code == "syntax.size"
    assert "syntax.non_finite" in codes(validate_slots(questionnaire(applicants_count=float("nan")), context=CONTEXT))
    cycle = []
    cycle.append(cycle)
    assert "syntax.limit" in codes(validate_slots(questionnaire(family=cycle), context=CONTEXT))


def test_cli_file_preflight_is_read_only_and_exit_codes(tmp_path, capsys):
    root, source = write_bundle(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert preflight_bundle(root, source).ok
    assert main(["bundle", str(root), "--source", str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] and result["imported"] is False and result["mode"] == "preflight_only"
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    source.write_bytes(b"modified")
    assert main(["bundle", str(root), "--source", str(source)]) == 1
    assert json.loads(capsys.readouterr().out)["errors"][0]["code"] == "semantic.source_hash"
    (root / "extra.yaml").write_text("unused", encoding="utf-8")
    assert "syntax.bundle_files" in codes(preflight_bundle(root, source))


def test_cli_slots_and_unreadable_files(tmp_path, capsys):
    root, _ = write_bundle(tmp_path)
    path = tmp_path / "slots.json"
    path.write_text(json.dumps(handoff()), encoding="utf-8")
    args = ["slots", str(path), "--countries", str(root / "countries.yaml"), "--profile", "handoff", "--today", "2026-10-06"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["decision_calculated"] is False
    path.write_text('{"contact": {"name": "PRIVATE_PERSON"}, "schema_version": "WRONG"}', encoding="utf-8")
    assert main(args) == 1
    assert "PRIVATE_PERSON" not in capsys.readouterr().out
    assert main(["slots", str(tmp_path / "absent"), "--countries", str(root / "countries.yaml")]) == 1
    assert json.loads(capsys.readouterr().out)["errors"][0]["code"] == "syntax.read"


@pytest.mark.parametrize("source", ['a: 1', '{"a": 1,}', '{"a": NaN}', '{"a": 1, "a": 2}', '# comment\n{}'])
def test_json_requires_json_grammar(tmp_path, source):
    path = tmp_path / "slots.json"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(InvalidDocument):
        load_document(path)


@pytest.mark.parametrize("value,kind", [(False, "bool"), (["manas", "osh"], "list"), (0, "working_days"), (3, "calendar_days")])
def test_rule_parameter_types(value, kind):
    data = bundle_data()
    find_unit(data, "rule_param")["value"] = {"value": value, "unit": kind}
    assert validate_data(data).ok


@pytest.mark.parametrize("amount,accepted", [(0, True), (10.5, True), (-1, False), (True, False), ("100", False)])
def test_tariff_value_schema_without_treating_it_as_approval(amount, accepted):
    data = bundle_data()
    price = find_unit(data, "tariff")
    price.update(confirmation_status="needs_verification", label="verify", blocked_value=None,
                 value={"amount": amount, "currency": "USD", "per": "person", "component": "service"})
    result = validate_data(data)
    assert result.ok is accepted
    assert result.summary()["imported"] is False


def test_no_module_db_or_client_imports_in_separate_process():
    # Отдельный процесс: pytest/conftest уже импортирует настройки основного приложения.
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "-c", "import sys; import scripts.validate_kg_entry; "
                             "assert not any(n in sys.modules for n in "
                             "('app.config', 'app.db', 'app.main', 'sqlalchemy', 'httpx'))"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("payload", [None, [], "text", 42])
def test_invalid_top_level_payloads_do_not_crash(payload):
    assert not validate_slots(payload, context=CONTEXT).ok
    assert not validate_bundle(payload, payload, payload, source_hash=SOURCE_HASH).ok


def test_schema_export_is_copy_and_external_refs_in_input_are_rejected():
    exported = slots_schema()
    exported["properties"].clear()
    assert len(slots_schema()["properties"]) == 50
    result = validate_slots(questionnaire(**{"$ref": "https://invalid.example/remote-schema"}), context=CONTEXT)
    assert not result.ok


def test_registration_term_does_not_replace_exemption():
    data = bundle_data()
    data[2][:] = [u for u in data[2] if u["unit_id"] != "KG.REG.EXEMPT.MDA"]
    assert "semantic.registration_missing" in codes(validate_data(data))


@pytest.mark.parametrize("text", ["Stay: {{days}}", "Stay: {days.__class__}", "Stay: {missing}", "Stay: 3.5 days"])
def test_template_must_use_declared_simple_placeholders(text):
    data = bundle_data()
    find_unit(data, "template")["value"]["text"] = text
    assert "semantic.template_literals" in codes(validate_data(data))


def test_checked_in_cli_examples(tmp_path, capsys):
    root = Path(__file__).parent / "fixtures/kg_entry"
    assert main(["bundle", str(root / "synthetic_bundle"), "--source", str(root / "synthetic_source.txt")]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "preflight_only"
    assert main(["slots", str(root / "synthetic_slots.json"), "--countries",
                 str(root / "synthetic_bundle/countries.yaml"), "--profile", "handoff", "--today", "2026-10-06"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


@pytest.mark.parametrize("suffix,source", [
    ("json", '{"a": ' + '9' * 5000 + '}'),
    ("yaml", 'a: ' + '9' * 5000),
    ("json", '{"a": "\\ud800"}'),
    ("json", '{"\\ud800": "a"}'),
])
def test_parser_scalar_extremes_are_reported_without_crashing(tmp_path, suffix, source):
    path = tmp_path / f"data.{suffix}"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(InvalidDocument):
        load_document(path)


def test_python_extreme_values_are_rejected_before_hashing():
    data = bundle_data()
    find_unit(data, "rule_param")["value"]["value"] = 10 ** 600
    assert "syntax.limit" in codes(validate_data(data))
    data = bundle_data()
    data[2][0]["title"] = "\ud800"
    assert "syntax.unicode" in codes(validate_data(data))
