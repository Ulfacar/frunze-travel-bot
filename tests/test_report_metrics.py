from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.report_metrics import acquisition, conversion, period_bounds


@pytest.mark.parametrize("leads,sales,expected", [(0, 0, None), (0, 3, None),
                                                   (3, 0, 0), (2, 3, 150)])
def test_conversion(leads, sales, expected):
    assert conversion(leads, sales) == expected


def test_bishkek_boundary():
    now = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)
    assert period_bounds("today", now) == (now, now)
    assert period_bounds("fortnight", now)[0] == datetime(2026, 10, 23, 18, tzinfo=timezone.utc)
    assert period_bounds("30d", now)[0] == datetime(2026, 10, 7, 18, tzinfo=timezone.utc)


def test_source_without_leads_and_missing_source():
    dialogs = [SimpleNamespace(user_id="synthetic-a", source_type="post", source_id="creative"),
               SimpleNamespace(user_id="synthetic-b")]
    result = acquisition(dialogs, {"synthetic-b"}, {"synthetic-a"})
    assert sum(r["leads"] for r in result["channels"]) == 1
    assert sum(r["sales"] for r in result["channels"]) == 1
    assert result["creatives"][1]["conversion"] is None
    assert "synthetic" not in repr(result)


def test_2000_dialogs_and_boundary(capsys):
    from time import perf_counter
    from datetime import timedelta
    from app.core.pilot_summary import Dialog, compute
    now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    start, end = period_bounds("fortnight", now)
    dialogs = [Dialog("synthetic-" + str(i), "getvisa", "fixture-manager", start,
                      source="post", source_id="creative-" + str(i % 20)) for i in range(2000)]
    audit = [{"user_id": d.user_id, "action": "outcome", "detail": "won", "created_at": start}
             for d in dialogs[::5]]
    audit.append({"user_id": dialogs[1].user_id, "action": "outcome", "detail": "won", "created_at": end})
    t = perf_counter()
    result = compute(dialogs, audit, start, end, sla=30, sales_action="outcome")
    elapsed = perf_counter() - t
    assert result["totals"]["new"] == 2000
    assert result["totals"]["sales"] == 400
    assert result["conversion"] == 20
    assert elapsed < 5
    with capsys.disabled():
        print(f"\nreport benchmark: dialogs=2000 sales=400 conversion=20% seconds={elapsed:.6f}")
