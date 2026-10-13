"""CALC-02 scenarios: independent day-set oracle, incomplete data and no legal approval."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

import pytest

from app.knowledge.stay_days import StayDayReview, StayReviewError
from app.knowledge.validation import load_document
from tests.test_kg_entry_validation import SOURCE_HASH, bundle_data

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/kg_entry"


def policy(entry=True, exit=True):
    return {"status": "proposed", "count_entry_day": entry, "count_exit_day": exit,
            "window_anchor": "each_day_backward_inclusive", "timezone": "Asia/Bishkek"}


def interval(start, end, uid="visit", **extra):
    return {"id": uid, "entry_date": start, "exit_date": end, "basis": "visa_free",
            "passport_country": "RUS", "passport_continuity": "same", "confirmed": True, **extra}


def request(history=None, start="2026-03-01", end="2026-03-05", as_of="2026-02-28", **extra):
    return {"schema_version": "kg-stay-review-input/1", "rule_unit_id": "KG.VF.TEST", "as_of": as_of,
            "history_complete": True, "history": history or [], "policy": policy(),
            "trip": {"mode": "new_entry", "start_date": start, "end_date": end,
                     "passport_country": "RUS", "basis": "visa_free"}, **extra}


def calculator(limit=10, window=30):
    data = bundle_data()
    next(u for u in data[2] if u["unit_id"] == "KG.VF.TEST")["value"].update(days=limit, window_days=window)
    return StayDayReview(*data, source_hash=SOURCE_HASH)


@pytest.fixture(scope="module")
def calc():
    return calculator()


@pytest.fixture(scope="module")
def real():
    folder = ROOT / "knowledge/kg_entry/draft-v1.1"
    data = [load_document(folder / f"{n}.yaml") for n in ("meta", "countries", "units")]
    return StayDayReview(*data, source_hash=data[0]["source_hash"])


def days(output):
    return [r["scenario_presence_days"] for r in output["scenario"]["daily"]]


def test_empty_history_and_deterministic_hashes_are_scenario_only(calc):
    source = request()
    before = deepcopy(source)
    result = calc.evaluate(source)
    assert days(result) == [1, 2, 3, 4, 5]
    assert result["exact_remaining_days"] is None and result["may_quote"] is False
    assert not result["publication_approved"] and not result["entry_eligibility_evaluated"]
    assert result["selected_regime"] is None and result["arithmetic_status"] == "computed_scenario"
    assert result["scenario"]["first_exceeded_date"] is None and source == before
    assert result == calc.evaluate(source)
    result["policy"]["count_entry_day"] = False
    assert calc.evaluate(source)["policy"]["count_entry_day"] is True


def test_overlapping_adjacent_duplicate_and_unsorted_history_counts_union(calc):
    records = [interval("2026-02-19", "2026-02-20", "a"), interval("2026-02-18", "2026-02-19", "b"),
               interval("2026-02-18", "2026-02-19", "duplicate"), interval("2026-02-21", "2026-02-22", "c")]
    data = request(records)
    output = calc.evaluate(data)
    assert days(output) == [6, 7, 8, 9, 10]
    assert output["scenario"]["counted_intervals"][0] == {
        "from": "2026-02-18", "to": "2026-02-22", "days": 5, "record_ids": ["a", "b", "c", "duplicate"]}
    data["history"].reverse()
    assert calc.evaluate(data) == output
    assert output["scenario"]["first_at_limit_date"] == "2026-03-05"


@pytest.mark.parametrize("entry,exit,expected", [(True, True, [1,2,3]), (False,True,[0,1,2]),
                                               (True,False,[1,2,2]), (False,False,[0,1,1])])
def test_explicit_endpoint_policy(calc, entry, exit, expected):
    result = calc.evaluate(request(end="2026-03-03", policy=policy(entry, exit)))
    assert days(result) == expected


@pytest.mark.parametrize("entry,exit,expected", [(True, True, 1), (False, True, 0), (True,False,0), (False,False,0)])
def test_same_day_borders(calc, entry, exit, expected):
    assert days(calc.evaluate(request(end="2026-03-01", policy=policy(entry, exit)))) == [expected]


def test_rolling_window_excludes_left_minus_one_and_counts_left_day():
    calc = calculator(3, 5)
    data = request([interval("2026-01-01", "2026-01-02")], start="2026-01-06", end="2026-01-07", as_of="2026-01-05")
    result = calc.evaluate(data)
    assert days(result) == [2, 2]
    assert [r["window_start"] for r in result["scenario"]["daily"]] == ["2026-01-02", "2026-01-03"]
    assert [r["reported_history_days"] for r in result["scenario"]["daily"]] == [1, 0]


def test_final_date_only_would_miss_prior_excess_when_exit_day_excluded():
    calc = calculator(3, 5)
    data = request([interval("2026-01-01", "2026-01-03")], start="2026-01-04", end="2026-01-06", as_of="2026-01-03",
                   policy=policy(True, False))
    result = calc.evaluate(data)
    assert days(result) == [3, 4, 3]
    assert result["scenario"]["first_exceeded_date"] == "2026-01-05"
    assert result["scenario"]["daily"][-1]["limit_relation"] == "at_limit"


@pytest.mark.parametrize("start,end,as_of,expected", [("2024-02-28","2024-03-01","2024-02-27",[1,2,3]),
    ("2025-02-28","2025-03-01","2025-02-27",[1,2]), ("2026-12-31","2027-01-02","2026-12-30",[1,2,3]),
    ("9999-12-30","9999-12-31","9999-12-29",[1,2])])
def test_calendar_boundaries(calc,start,end,as_of,expected):
    assert days(calc.evaluate(request(start=start,end=end,as_of=as_of))) == expected


def test_open_stay_continuation_counts_actual_entry_once_and_not_cutoff_as_exit(calc):
    data = request([interval("2026-02-25", None)], start="2026-02-28", end="2026-03-02", as_of="2026-02-28", policy=policy(False,False))
    data["trip"]["mode"] = "continue_open"
    result = calc.evaluate(data)
    assert days(result) == [3,4,4]
    assert [r["reported_history_days"] for r in result["scenario"]["daily"]] == [3,3,3]
    assert result["scenario"]["counted_intervals"] == [{"from":"2026-02-26","to":"2026-03-01","days":4,"record_ids":["visit"]}]


def test_same_day_exit_scenario_does_not_create_false_observed_exit(calc):
    data = request([interval("2026-02-25",None)],start="2026-02-28",end="2026-02-28",as_of="2026-02-28",policy=policy(True,False))
    data["trip"]["mode"] = "continue_open"
    row = calc.evaluate(data)["scenario"]["daily"][0]
    assert row["reported_history_days"] == 4 and row["scenario_presence_days"] == 3


def test_same_day_closed_exit_and_new_open_entry_are_not_double_counted(calc):
    data = request([interval("2026-02-20","2026-02-25","closed"),interval("2026-02-25",None,"open")],
                   start="2026-02-28",end="2026-03-01",as_of="2026-02-28")
    data["trip"]["mode"] = "continue_open"
    assert days(calc.evaluate(data)) == [9,10]


@pytest.mark.parametrize("case,block", [("new_open","open_stay_requires_resolution"),
    ("continue_missing","continuation_requires_open_stay_at_as_of"), ("continue_future","continuation_requires_open_stay_at_as_of"),
    ("policy_missing","counting_policy_missing"), ("wrong_country","country_not_in_candidate_rule")])
def test_insufficient_scenario_context_is_not_a_zero_result(calc,case,block):
    data=request()
    if case in ("new_open","continue_future"):
        data["history"]=[interval("2026-02-20",None)]
    if case.startswith("continue"):
        data["trip"]["mode"]="continue_open"
    if case=="policy_missing": data["policy"]=None
    if case=="wrong_country": data["trip"]["passport_country"]="CHN"
    output=calc.evaluate(data)
    assert block in output["blocked_by"] and output["scenario"] is None
    assert output["exact_remaining_days"] is None


@pytest.mark.parametrize("complete", [False,None])
def test_incomplete_history_never_claims_exact_remainder(calc,complete):
    result=calc.evaluate(request(history_complete=complete))
    assert "history_incomplete" in result["findings"] and result["exact_remaining_days"] is None
    assert result["scenario"]["status"] == "unapproved_scenario"


@pytest.mark.parametrize("extra,finding", [({"confirmed":False},"history_unconfirmed"),
    ({"basis":"visa"},"basis_history_requires_review"), ({"basis":"unknown"},"basis_history_requires_review"),
    ({"passport_country":"CHN"},"passport_history_requires_review"),
    ({"passport_country":None},"passport_history_requires_review"),
    ({"passport_continuity":"changed"},"passport_history_requires_review"),
    ({"passport_continuity":"unknown"},"passport_history_requires_review")])
def test_basis_and_passport_uncertainty_are_not_silently_filtered(calc,extra,finding):
    output=calc.evaluate(request([interval("2026-02-20","2026-02-21",**extra)]))
    assert finding in output["findings"] and days(output)[0]==3
    assert output["exact_remaining_days"] is None and not output["may_quote"]


@pytest.mark.parametrize("case", ["reversed","future_history","future_exit","before_as_of","reversed_plan","long_plan",
    "two_open","open_then_closed","duplicate_id","unknown_country","bad_date","bool_policy","approved_policy",
    "missing_boundary","wrong_timezone","wrong_anchor","private_field","counter_from_slots","nonfinite","null_request"])
def test_invalid_inputs_fail_with_bounded_diagnostics(calc,case):
    data=request()
    if case=="reversed": data["history"]=[interval("2026-02-22","2026-02-20")]
    elif case=="future_history": data["history"]=[interval("2026-03-01",None)]
    elif case=="future_exit": data["history"]=[interval("2026-02-20","2026-03-01")]
    elif case=="before_as_of": data["trip"]["start_date"]="2026-02-27"
    elif case=="reversed_plan": data["trip"]["end_date"]="2026-02-28"
    elif case=="long_plan": data["trip"]["end_date"]="2029-01-01"
    elif case=="two_open": data["history"]=[interval("2026-02-20",None,"a"),interval("2026-02-21",None,"b")]
    elif case=="open_then_closed": data["history"]=[interval("2026-02-20",None,"a"),interval("2026-02-21","2026-02-22","b")]
    elif case=="duplicate_id": data["history"]=[interval("2026-02-20","2026-02-21")]*2
    elif case=="unknown_country": data["trip"]["passport_country"]="ZZZ"
    elif case=="bad_date": data["as_of"]="2026-02-30"
    elif case=="bool_policy": data["policy"]["count_entry_day"]=1
    elif case=="approved_policy": data["policy"]["status"]="approved"
    elif case=="missing_boundary": del data["policy"]["count_exit_day"]
    elif case=="wrong_timezone": data["policy"]["timezone"]="UTC"
    elif case=="wrong_anchor": data["policy"]["window_anchor"]="last_day_only"
    elif case=="private_field": data["phone"]="PRIVATE"
    elif case=="counter_from_slots": data["days_in_window"]=3
    elif case=="nonfinite": data["history_complete"]=float('nan')
    elif case=="null_request": data=None
    with pytest.raises(StayReviewError) as error: calc.evaluate(data)
    assert "PRIVATE" not in str(error.value) and len(str(error.value))<80


def test_window_bounds_and_date_underflow_rejected():
    with pytest.raises(StayReviewError,match="unsupported_window"):
        calculator(window=3661).evaluate(request())
    with pytest.raises(StayReviewError,match="unsupported_window"):
        calculator().evaluate(request(start="0001-01-02",end="0001-01-03",as_of="0001-01-01"))


def test_schema_valid_integral_json_numbers_are_normalized_for_date_arithmetic():
    output=calculator(3.0,5.0).evaluate(request())
    assert days(output)==[1,2,3,4,5]
    assert type(output["scenario"]["window_days"]) is int
    assert output["scenario"]["first_exceeded_date"]=="2026-03-04"


def test_bounded_history(calc):
    data=request([interval("2026-02-01","2026-02-02",str(i)) for i in range(1001)])
    with pytest.raises(StayReviewError,match="invalid_request"): calc.evaluate(data)


def test_input_and_rule_changes_change_reproducible_identity(calc):
    data=request()
    first=calc.evaluate(data)
    data["policy"]["count_exit_day"]=False
    second=calc.evaluate(data)
    assert first["input_hash"]!=second["input_hash"] and first["calculation_hash"]!=second["calculation_hash"]
    third=calculator(limit=11).evaluate(data)
    assert third["bundle_hash"]!=second["bundle_hash"] and third["calculation_hash"]!=second["calculation_hash"]


def test_real_pending_rules_are_never_approved_by_explicit_scenario(real):
    data=load_document(FIX/"synthetic_stay_review.json")
    result=real.evaluate(data)
    assert days(result)==[31,31,31,31]
    assert result["scenario"]["first_exceeded_date"]=="2026-04-29"
    assert {r["confirmation_status"] for r in result["counting_rules"]}=={"decision_pending"}
    assert result["may_quote"] is False and result["exact_remaining_days"] is None
    data["policy"]=None
    assert real.evaluate(data)["scenario"] is None


def test_null_rule_does_not_resurrect_blocked_evidence(real):
    data=load_document(FIX/"synthetic_stay_review.json")
    data["rule_unit_id"]="KG.VF.GCC"
    data["trip"]["passport_country"]="SAU"
    output=real.evaluate(data)
    assert "rule_value_missing" in output["blocked_by"] and output["scenario"] is None


def test_randomized_day_set_oracle_covers_merging_windows_and_all_endpoint_policies():
    rng=random.Random(20261007)
    base=date(2024,1,1)
    def iso(n): return (base+timedelta(days=n)).isoformat()
    for _ in range(200):
        limit,window=rng.randint(1,15),rng.randint(15,40)
        calc=calculator(limit,window)
        entry,exit=rng.choice([False,True]),rng.choice([False,True])
        records=[]
        expected=set()
        for i in range(rng.randrange(0,12)):
            a=rng.randrange(0,60)
            b=rng.randrange(a,61)
            records.append(interval(iso(a),iso(b),str(i)))
            expected.update(range(a+int(not entry),b+1-int(not exit)))
        start,end=rng.randint(61,70),rng.randint(71,90)
        expected.update(range(start+int(not entry),end+1-int(not exit)))
        result=calc.evaluate(request(records,start=iso(start),end=iso(end),as_of=iso(60),policy=policy(entry,exit)))
        assert days(result)==[len(expected.intersection(range(d-window+1,d+1))) for d in range(start,end+1)]


def test_cli_is_readonly_ignores_dsn_and_does_not_leak_invalid_request(tmp_path):
    data=request()
    path=tmp_path/"request.json"
    path.write_text(json.dumps(data),encoding="utf-8")
    source=FIX/"synthetic_source.txt"
    bundle=FIX/"synthetic_bundle"
    files=[path,source,*bundle.iterdir()]
    before={p:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in files}
    args=[sys.executable,"scripts/review_kg_stay_days.py",str(bundle),"--source",str(source),"--request",str(path)]
    env={**os.environ,"ALEMBIC_DATABASE_URL":"postgresql://invalid.invalid/no","PYTHONIOENCODING":"utf-8"}
    output=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert output.returncode==0,output.stdout+output.stderr
    assert json.loads(output.stdout)["arithmetic_status"]=="computed_scenario"
    assert before=={p:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in files}
    path.write_text('{"phone":"PRIVATE-CUSTOMER"}',encoding="utf-8")
    bad=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert bad.returncode==1 and "PRIVATE" not in bad.stdout+bad.stderr


def test_module_has_no_database_runtime_or_network_imports():
    import ast
    for path in (ROOT/"app/knowledge/stay_days.py",ROOT/"app/knowledge/stay_schema.py",ROOT/"scripts/review_kg_stay_days.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"))
        imports=[node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
        assert not any(name.startswith(("app.config","app.domain","sqlalchemy","httpx","requests")) for name in imports)


EXAMPLES = json.loads((FIX/"stay_review_examples.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("example", EXAMPLES["examples"], ids=lambda r:r["id"])
def test_proposed_examples_bound_to_real_bundle_remain_unapproved(real,example):
    records=[interval(a,b,f"synthetic-{i}",passport_country=example["country"]) for i,(a,b) in enumerate(example["history"])]
    data=request(records,start=example["start"],end=example["end"],as_of=example["as_of"],rule_unit_id=example["rule"])
    data["trip"].update(passport_country=example["country"],mode=example.get("mode","new_entry"))
    output=real.evaluate(data)
    expected=example["expected"]
    assert output["bundle_hash"]==EXAMPLES["bundle_hash"] and output["source_hash"]==EXAMPLES["source_hash"]
    assert [days(output)[0],days(output)[-1],output["scenario"]["max_presence_days"]]==[expected["first"],expected["last"],expected["max"]]
    assert output["scenario"]["first_at_limit_date"]==expected["at_limit"]
    assert output["scenario"]["first_exceeded_date"]==expected["exceeded"]
    assert EXAMPLES["status"]=="proposed_not_approved" and output["exact_remaining_days"] is None


def test_invalid_source_bundle_and_unknown_rule_are_rejected(calc):
    with pytest.raises(StayReviewError,match="invalid_bundle"):
        StayDayReview(*bundle_data(),source_hash="0"*64)
    data=request(rule_unit_id="KG.VF.MISSING")
    with pytest.raises(StayReviewError,match="unknown_visa_free_rule"): calc.evaluate(data)


@pytest.mark.parametrize("start,end,as_of,entry,exit", [("2026-03-01","2028-02-28","2026-02-28",True,True),
    ("9999-12-31","9999-12-31","9999-12-30",False,False),
    ("0001-01-01","0001-01-01","0001-01-01",True,True)])
def test_supported_arithmetic_limits_do_not_overflow(start,end,as_of,entry,exit):
    calc=calculator(1,1)
    output=calc.evaluate(request(start=start,end=end,as_of=as_of,policy=policy(entry,exit)))
    assert len(days(output))==(date.fromisoformat(end)-date.fromisoformat(start)).days+1
    assert all(0<=n<=1 for n in days(output))


@pytest.mark.parametrize("fault", ["timestamp","unicode","cycles","extra_policy_override"])
def test_additional_adversarial_requests(calc,fault):
    data=request()
    if fault=="timestamp": data["as_of"]="2026-02-28T23:59:59+06:00"
    elif fault=="unicode": data["history"]=[interval("2026-02-01","2026-02-02","\ud800")]
    elif fault=="cycles": data["history"].append(data)
    elif fault=="extra_policy_override": data["policy"]["limit_days"]=9999
    with pytest.raises(StayReviewError,match="invalid_request"): calc.evaluate(data)
