"""CALC-03 arithmetic, explicit calendar provenance, missing data and readonly CLI."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
from zoneinfo import ZoneInfoNotFoundError

import pytest

from app.knowledge.deadlines import DeadlineError, DeadlineReview
from app.knowledge.work_calendar import CalendarError, WorkCalendars
from app.knowledge.validation import load_document
from tests.test_kg_entry_validation import SOURCE_HASH, bundle_data

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/kg_entry"
EMPTY = {"format": "kg-work-calendars/1", "calendars": []}


def calendars():
    return load_document(FIX / "synthetic_work_calendars.json")


def one_year(year=2026):
    result=deepcopy(calendars()["calendars"][0])
    result.update(year=year,days=[])
    return result


def calculator(unit="working_days", amount=3, direction="after", shift="none", calendar_data=None, boundary=True):
    data=bundle_data()
    rule=next(r for r in data[2] if r["unit_id"]=="KG.DL.TEST")
    rule["value"].update(unit=unit,value=amount,direction=direction,shift_from_nonworking=shift,boundary_inclusive=boundary)
    return DeadlineReview(*data,source_hash=SOURCE_HASH,calendars=calendars() if calendar_data is None else calendar_data)


def request(value="2026-10-08",unit="working_days",include=False,month_end="reject"):
    return {"format":"kg-deadline-review-input/1","rule_unit_id":"KG.DL.TEST",
            "anchor":{"name":"entry_date","value":value},
            "policy":{"status":"proposed","timezone":"Asia/Bishkek",
                      "count_anchor_day":include if unit in ("working_days","calendar_days") else None,
                      "month_end":month_end if unit=="months" else None,
                      "hours_mode":"elapsed" if unit=="hours" else None}}


def due(calc, req):
    result=calc.evaluate(req)
    assert result["arithmetic_status"]=="computed_scenario",result["blocked_by"]
    assert result["exact_deadline"] is None and result["may_quote"] is False
    assert result["publication_approved"] is False and not result["boundary_interpretation_approved"]
    return result["scenario"]["due"]


def test_calendar_overrides_pattern_without_using_office_schedule():
    book=WorkCalendars(calendars())
    assert book.day(date(2026,10,9))["is_working"] is False
    assert book.day(date(2026,10,10))["is_working"] is True
    assert book.day(date(2026,10,12))["is_working"] is False
    assert book.day(date(2026,10,13))["basis"]=="floating_holiday"
    assert book.day(date(2026,10,17))["is_working"] is False
    assert book.day(date(2026,10,14))["basis"]=="explicit_week_pattern"
    with pytest.raises(CalendarError,match="calendar_missing"): book.day(date(2028,1,1))


def test_calendar_snapshot_is_owned_and_order_independent():
    data=calendars()
    book=WorkCalendars(data)
    old_hash=book.content_hash
    data["calendars"].reverse()
    for year in data["calendars"]:
        year["days"].reverse()
        year["week_rest_days"].reverse()
    assert WorkCalendars(data).content_hash==old_hash
    data["calendars"][0]["version"]=2
    assert WorkCalendars(data).content_hash!=old_hash and book.content_hash==old_hash
    exported=book.describe()
    exported[0]["version"]=999
    day=book.day(date(2026,10,10))
    day["is_working"]=False
    assert book.describe()[0]["version"]==1 and book.day(date(2026,10,10))["is_working"] is True


@pytest.mark.parametrize("fault", ["duplicate_year","duplicate_day","other_year","bad_kind","bad_working","no_pattern",
    "weekday_bool","weekday_duplicate","unknown_type","official_status","wrong_timezone","office_schedule",
    "provisional_without_note","complete_with_note","bad_date","private_field","nan","cycle"])
def test_invalid_calendars_are_rejected(fault):
    data=calendars()
    year=data["calendars"][0]
    if fault=="duplicate_year": data["calendars"].append({**deepcopy(year),"version":2})
    elif fault=="duplicate_day": year["days"].append({**year["days"][0],"title":"another"})
    elif fault=="other_year": year["days"][0]["date"]="2027-10-09"
    elif fault=="bad_kind": year["days"][0]["kind"]="office_closed"
    elif fault=="bad_working": year["days"][0]["is_working"]=True
    elif fault=="no_pattern": del year["week_rest_days"]
    elif fault=="weekday_bool": year["week_rest_days"]=[True,7]
    elif fault=="weekday_duplicate": year["week_rest_days"]=[6,6]
    elif fault=="unknown_type": year["days"][0]["is_working"]=1
    elif fault=="official_status": year["status"]="active"
    elif fault=="wrong_timezone": year["timezone"]="UTC"
    elif fault=="office_schedule": year["schedule_kind"]="office"
    elif fault=="provisional_without_note": year["completeness"]="provisional"
    elif fault=="complete_with_note": year["provisional_note"]="unknown holiday"
    elif fault=="bad_date": year["days"][0]["date"]="2026-02-30"
    elif fault=="private_field": year["phone"]="PRIVATE"
    elif fault=="nan": year["version"]=float('nan')
    elif fault=="cycle": year["days"].append(year)
    with pytest.raises(CalendarError) as error: WorkCalendars(data)
    assert len(str(error.value))<80 and "PRIVATE" not in str(error.value)


def test_integral_json_calendar_fields_and_weekend_override():
    year=one_year()
    year.update(year=2026.0,version=1.0,week_rest_days=[6.0,7.0])
    year["days"]=[{"date":"2026-10-11","is_working":True,"kind":"weekend_override","title":"Synthetic","source_ref":"synthetic"}]
    book=WorkCalendars({"format":EMPTY["format"],"calendars":[year]})
    assert book.day(date(2026,10,11))["is_working"] is True
    assert type(book.describe()[0]["year"]) is int
    with pytest.raises(CalendarError,match="invalid_calendar_date"): book.day(datetime(2026,10,11))


@pytest.mark.parametrize("direction,anchor,include,expected", [
    ("after","2026-10-08",False,"2026-10-15"),("after","2026-10-08",True,"2026-10-14"),
    ("before","2026-10-15",False,"2026-10-08"),("before","2026-10-15",True,"2026-10-10"),
    ("after","2026-10-11",True,"2026-10-16"),("after","2026-10-11",False,"2026-10-16")])
def test_working_days_count_explicit_holidays_and_transfers(direction,anchor,include,expected):
    assert due(calculator(direction=direction),request(anchor,include=include))==expected


def test_trace_explains_counted_days_and_calendar_identity():
    result=calculator().evaluate(request())
    trace=result["scenario"]["calendar_trace"]
    assert [r["date"] for r in trace if r["counted"]]==["2026-10-10","2026-10-14","2026-10-15"]
    assert trace[0]["date"]=="2026-10-08" and trace[0]["counted"] is False
    assert all(r["calendar_hash"]==result["calendars"][0]["hash"] for r in trace)
    assert result["scenario"]["calendar_years_used"]==[2026]


@pytest.mark.parametrize("direction,anchor,expected", [("after","2026-12-31","2027-01-04"),
                                                       ("before","2027-01-04","2026-12-31")])
def test_cross_year_uses_each_supplied_version(direction,anchor,expected):
    calc=calculator(amount=2,direction=direction)
    result=calc.evaluate(request(anchor))
    assert result["scenario"]["due"]==expected
    assert result["scenario"]["calendar_years_used"]==[2026,2027]


@pytest.mark.parametrize("fault", ["missing","provisional","excluded_anchor_missing"])
def test_missing_or_provisional_calendar_discards_partial_work(fault):
    data=calendars()
    if fault=="missing": data["calendars"]=data["calendars"][:1]
    elif fault=="excluded_anchor_missing": data["calendars"]=data["calendars"][1:]
    else: data["calendars"][1].update(completeness="provisional",provisional_note="Synthetic unknown floating holiday")
    result=calculator(amount=2,calendar_data=data).evaluate(request("2026-12-31"))
    assert result["scenario"] is None and result["exact_deadline"] is None
    assert result["blocked_by"]==["calendar_provisional" if fault=="provisional" else "calendar_missing"]
    assert result["unavailable_calendar_year"]==(2026 if fault=="excluded_anchor_missing" else 2027)
    assert "calculation_hash" not in result


@pytest.mark.parametrize("shift,expected", [("none","2026-10-09"),("next_working","2026-10-10"),("previous_working","2026-10-08")])
def test_calendar_day_deadline_shift_uses_rule_and_transferred_saturday(shift,expected):
    calc=calculator(unit="calendar_days",amount=1,shift=shift)
    result=calc.evaluate(request(unit="calendar_days"))
    assert result["scenario"]["unshifted_due"]=="2026-10-09"
    assert result["scenario"]["due"]==expected


def test_shift_requires_calendar_even_for_calendar_day_rule_and_crosses_year():
    result=calculator(unit="calendar_days",amount=1,shift="next_working",calendar_data=EMPTY).evaluate(request(unit="calendar_days"))
    assert result["blocked_by"]==["calendar_missing"] and result["scenario"] is None
    result=calculator(unit="calendar_days",amount=1,shift="next_working").evaluate(request("2026-12-31",unit="calendar_days"))
    assert result["scenario"]["due"]=="2027-01-02"


@pytest.mark.parametrize("direction,include,expected", [("after",False,"2026-10-11"),("after",True,"2026-10-10"),
                                                       ("before",False,"2026-10-05"),("before",True,"2026-10-06")])
def test_calendar_days_do_not_need_work_calendar(direction,include,expected):
    assert due(calculator(unit="calendar_days",direction=direction,calendar_data=EMPTY),
               request(unit="calendar_days",include=include))==expected


@pytest.mark.parametrize("anchor,amount,direction,policy,expected", [
    ("2026-01-31",1,"after","clamp","2026-02-28"),("2024-01-31",1,"after","clamp","2024-02-29"),
    ("2026-01-31",2,"after","reject","2026-03-31"),("2026-03-31",1,"before","clamp","2026-02-28"),
    ("2026-12-15",2,"after","reject","2027-02-15"),("2026-03-01",1,"before","reject","2026-02-01")])
def test_months_are_anniversaries_not_thirty_days(anchor,amount,direction,policy,expected):
    assert due(calculator(unit="months",amount=amount,direction=direction,calendar_data=EMPTY),
               request(anchor,unit="months",month_end=policy))==expected


def test_month_end_reject_and_clamp_are_explicit():
    calc=calculator(unit="months",amount=1,calendar_data=EMPTY)
    result=calc.evaluate(request("2026-01-31",unit="months",month_end="reject"))
    assert result["scenario"] is None and result["blocked_by"]==["month_day_missing"]
    result=calc.evaluate(request("2026-01-31",unit="months",month_end="clamp"))
    assert result["scenario"]["month_end_clamped"] is True
    assert calculator(unit="months",amount=1,shift="next_working").evaluate(request("2026-01-31",unit="months",month_end="clamp"))["scenario"]["due"]=="2026-03-02"


@pytest.mark.parametrize("direction,anchor,expected", [("after","2026-12-30T20:30:00Z","2027-01-03T02:30:00+06:00"),
    ("before","2026-01-03T02:30:00+06:00","2025-12-31T02:30:00+06:00")])
def test_hours_are_elapsed_instants_with_explicit_timezone(direction,anchor,expected):
    calc=calculator(unit="hours",amount=72,direction=direction,calendar_data=EMPTY)
    result=calc.evaluate(request(anchor,unit="hours"))
    assert result["scenario"]["due"]==expected
    assert result["scenario"]["calendar_trace"]==[]
    a=datetime.fromisoformat(result["scenario"]["anchor_utc"])
    b=datetime.fromisoformat(result["scenario"]["due_utc"])
    assert abs((b-a).total_seconds())==72*3600


@pytest.mark.parametrize("anchor", ["2026-10-08","2026-10-08T12:00:00-00:00"])
def test_hours_never_guess_midnight_or_unknown_offset(anchor):
    output=calculator(unit="hours",amount=72).evaluate(request(anchor,unit="hours"))
    assert output["blocked_by"]==["aware_anchor_required"]


def test_hours_calendar_shift_is_explicitly_unsupported():
    output=calculator(unit="hours",shift="next_working").evaluate(request("2026-10-08T10:00:00Z",unit="hours"))
    assert output["blocked_by"]==["hour_calendar_shift_unsupported"] and output["scenario"] is None


def test_missing_timezone_data_has_no_fixed_offset_fallback(monkeypatch):
    def missing(name): raise ZoneInfoNotFoundError("private path")
    monkeypatch.setattr("app.knowledge.deadlines.ZoneInfo",missing)
    result=calculator(unit="hours").evaluate(request("2026-10-08T10:00:00Z",unit="hours"))
    assert result["blocked_by"]==["timezone_unavailable"] and "private" not in json.dumps(result)


def test_rule_source_boundary_does_not_implicitly_choose_counting_policy():
    a=calculator(boundary=True).evaluate(request())
    b=calculator(boundary=False).evaluate(request())
    assert a["scenario"]==b["scenario"] and a["bundle_hash"]!=b["bundle_hash"]
    assert a["source_boundary_inclusive"] is True and b["source_boundary_inclusive"] is False
    assert a["boundary_interpretation_approved"] is False


def test_policy_absence_or_anchor_mismatch_returns_no_date():
    for fault in ("policy","anchor"):
        data=request()
        if fault=="policy": data["policy"]=None
        else: data["anchor"]["name"]="wrong_event"
        result=calculator().evaluate(data)
        assert result["scenario"] is None and result["exact_deadline"] is None
        assert result["blocked_by"]==["counting_policy_missing" if fault=="policy" else "anchor_name_mismatch"]


@pytest.mark.parametrize("unit,changes", [("working_days",{"count_anchor_day":None}),
    ("working_days",{"month_end":"clamp"}),("calendar_days",{"hours_mode":"elapsed"}),
    ("months",{"count_anchor_day":True}),("months",{"month_end":None}),
    ("hours",{"hours_mode":None}),("hours",{"count_anchor_day":True})])
def test_incompatible_policy_is_not_silently_ignored(unit,changes):
    data=request("2026-10-08T10:00:00Z" if unit=="hours" else "2026-10-08",unit=unit)
    data["policy"].update(changes)
    result=calculator(unit=unit).evaluate(data)
    assert result["blocked_by"]==["incompatible_counting_policy"]


@pytest.mark.parametrize("unit,anchor,direction", [("calendar_days","9999-12-31","after"),
    ("calendar_days","0001-01-01","before"),("months","9999-12-31","after"),
    ("months","0001-01-01","before"),("hours","9999-12-31T23:00:00Z","after")])
def test_date_overflow_never_produces_partial_result(unit,anchor,direction):
    result=calculator(unit=unit,amount=1,direction=direction).evaluate(request(anchor,unit=unit))
    assert result["blocked_by"]==["date_range_exceeded"] and result["scenario"] is None


def test_working_day_at_date_extreme_and_scan_bound(monkeypatch):
    year=one_year(1)
    year["week_rest_days"]=[]
    calc=calculator(amount=1,direction="before",calendar_data={"format":EMPTY["format"],"calendars":[year]})
    assert due(calc,request("0001-01-01",include=True))=="0001-01-01"
    assert calc.evaluate(request("0001-01-01"))["blocked_by"]==["date_range_exceeded"]
    monkeypatch.setattr("app.knowledge.deadlines.MAX_SCAN_DAYS",7)
    year=one_year()
    year["week_rest_days"]=[1,2,3,4,5,6,7]
    result=calculator(amount=1,calendar_data={"format":EMPTY["format"],"calendars":[year]}).evaluate(request())
    assert result["blocked_by"]==["calendar_search_limit"]


@pytest.mark.parametrize("unit,amount", [("working_days",3661),("calendar_days",3661),("months",121),("hours",87841)])
def test_duration_limits(unit,amount):
    result=calculator(unit=unit,amount=amount).evaluate(request("2026-10-08T10:00:00Z" if unit=="hours" else "2026-10-08",unit=unit))
    assert result["blocked_by"]==["duration_limit"]


def test_integral_json_duration_is_supported():
    assert due(calculator(amount=3.0),request())=="2026-10-15"


@pytest.mark.parametrize("fault", ["private","bad_date","naive_stamp","wrong_policy","unknown_policy","extra_days",
    "cycle","unicode","nonfinite","wrong_timezone","boolean_day","unknown_rule"])
def test_bad_requests_are_bounded_errors(fault):
    data=request()
    if fault=="private": data["passport_number"]="PRIVATE"
    elif fault=="bad_date": data["anchor"]["value"]="2026-02-30"
    elif fault=="naive_stamp": data["anchor"]["value"]="2026-10-08T10:00:00"
    elif fault=="wrong_policy": data["policy"]["status"]="approved"
    elif fault=="unknown_policy": data["policy"]["month_end"]="roll_forward"
    elif fault=="extra_days": data["value"]=999
    elif fault=="cycle": data["anchor"]["value"]=data
    elif fault=="unicode": data["anchor"]["name"]="\ud800"
    elif fault=="nonfinite": data["policy"]["count_anchor_day"]=float('nan')
    elif fault=="wrong_timezone": data["policy"]["timezone"]="UTC"
    elif fault=="boolean_day": data["policy"]["count_anchor_day"]=1
    elif fault=="unknown_rule": data["rule_unit_id"]="KG.DL.MISSING"
    with pytest.raises(DeadlineError) as error: calculator().evaluate(data)
    assert len(str(error.value))<80 and "PRIVATE" not in str(error.value)


def test_timestamp_is_not_truncated_for_day_rule():
    output=calculator().evaluate(request("2026-10-08T10:00:00Z"))
    assert output["blocked_by"]==["local_date_anchor_required"]


@pytest.mark.parametrize("stamp", ["2026-02-30T10:00:00Z", "2026-10-08T24:00:00Z",
    "2026-10-08T10:00:60Z", "2026-10-08T10:00:00+24:00", "2026-10-08T10:00:00+06:60",
    "2026-10-08T10:00:00.1234567Z", "2026-10-08 10:00:00Z"])
def test_invalid_timestamp_fields_are_rejected_even_without_optional_format_checker(stamp, monkeypatch):
    from jsonschema import FormatChecker
    monkeypatch.delitem(FormatChecker.checkers, "date-time", raising=False)
    with pytest.raises(DeadlineError, match="invalid_request"):
        calculator(unit="hours").evaluate(request(stamp, unit="hours"))


def test_changed_calendar_version_or_day_changes_identity_and_date():
    data=calendars()
    first=calculator(calendar_data=data).evaluate(request())
    data["calendars"][0]["version"]=2
    data["calendars"][0]["days"]=[r for r in data["calendars"][0]["days"] if r["date"]!="2026-10-13"]
    second=calculator(calendar_data=data).evaluate(request())
    assert first["scenario"]["due"]=="2026-10-15" and second["scenario"]["due"]=="2026-10-14"
    assert first["calculation_hash"]!=second["calculation_hash"] and first["input_hash"]==second["input_hash"]


def test_randomized_independent_workday_sequence_oracle():
    rng=random.Random(20261008)
    base=date(2026,1,1)
    for _ in range(120):
        year=one_year()
        overrides={rng.randrange(365):rng.choice([True,False]) for _ in range(20)}
        year["days"]=[{"date":(base+timedelta(days=i)).isoformat(),"is_working":flag,"kind":"weekend_override",
                      "title":"Synthetic","source_ref":"synthetic"} for i,flag in overrides.items()]
        working=[i for i in range(365) if overrides.get(i,(base+timedelta(days=i)).isoweekday() not in (6,7))]
        anchor=rng.randint(80,250)
        amount=rng.randint(1,20)
        inclusive=rng.choice([True,False])
        direction=rng.choice(["before","after"])
        candidates=[i for i in working if i>=anchor+int(not inclusive)] if direction=="after" else [i for i in reversed(working) if i<=anchor-int(not inclusive)]
        expected=(base+timedelta(days=candidates[amount-1])).isoformat()
        calc=calculator(amount=amount,direction=direction,calendar_data={"format":EMPTY["format"],"calendars":[year]})
        assert due(calc,request((base+timedelta(days=anchor)).isoformat(),include=inclusive))==expected


def test_real_pdf_deadline_null_never_parses_numbers_from_evidence():
    directory=ROOT/"knowledge/kg_entry/draft-v1.1"
    data=[load_document(directory/f"{n}.yaml") for n in ("meta","countries","units")]
    calc=DeadlineReview(*data,source_hash=data[0]["source_hash"],calendars=EMPTY)
    for row in data[2]:
        if row["kind"]!="deadline": continue
        req=request()
        req["rule_unit_id"]=row["unit_id"]
        output=calc.evaluate(req)
        assert output["blocked_by"]==["rule_value_missing"] and output["scenario"] is None
        assert output["exact_deadline"] is None and output["may_quote"] is False


def test_cli_readonly_reproducible_and_private_error(tmp_path):
    req=tmp_path/"request.json"
    req.write_bytes((FIX/"synthetic_deadline_review.json").read_bytes())
    files=[req,FIX/"synthetic_work_calendars.json",FIX/"synthetic_source.txt",*(FIX/"synthetic_bundle").iterdir()]
    before={p:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in files}
    args=[sys.executable,"scripts/review_kg_deadline.py",str(FIX/"synthetic_bundle"),"--source",str(FIX/"synthetic_source.txt"),
          "--calendars",str(FIX/"synthetic_work_calendars.json"),"--request",str(req)]
    env={**os.environ,"PYTHONIOENCODING":"utf-8","ALEMBIC_DATABASE_URL":"postgresql://invalid.invalid/no"}
    a=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,encoding="utf-8",timeout=30)
    b=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert a.returncode==b.returncode==0 and a.stdout==b.stdout
    assert json.loads(a.stdout)["scenario"]["due"]=="2026-10-08"
    assert before=={p:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in files}
    req.write_text('{"phone":"PRIVATE-CUSTOMER"}',encoding="utf-8")
    bad=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert bad.returncode==1 and "PRIVATE" not in bad.stdout+bad.stderr


def test_pure_modules_do_not_import_runtime_database_or_network():
    import ast
    for filename in ("app/knowledge/deadlines.py","app/knowledge/work_calendar.py","app/knowledge/deadline_schema.py","scripts/review_kg_deadline.py"):
        tree=ast.parse((ROOT/filename).read_text(encoding="utf-8"))
        imports=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        imports += [alias.name for n in ast.walk(tree) if isinstance(n,ast.Import) for alias in n.names]
        assert not any(n.startswith(("app.config","app.domain","sqlalchemy","httpx","requests")) for n in imports)
