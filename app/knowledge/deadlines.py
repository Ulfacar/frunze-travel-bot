"""CALC-03: разные единицы времени и явный календарь, только review-сценарии."""
from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .bundle import validate_bundle
from .deadline_schema import DEADLINE_REQUEST
from .review import canonical, review_findings
from .validation import InvalidDocument, check_tree, schema_errors
from .work_calendar import CalendarError, WorkCalendars

ALGORITHM = "kg-deadline-arithmetic/1"
MAX_SCAN_DAYS = 3660


class DeadlineError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _hash(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _move(day, step):
    try:
        return date.fromordinal(day.toordinal() + step)
    except ValueError:
        raise DeadlineError("date_range_exceeded") from None


def _working_deadline(calendars, anchor, amount, direction, include_anchor, trace):
    day, remaining = anchor, amount
    for offset in range(MAX_SCAN_DAYS + 1):
        info = calendars.day(day)  # Even excluded anchor must have explicit year coverage.
        counted = info["is_working"] and (offset > 0 or include_anchor)
        trace.append({**info, "phase": "count", "counted": counted})
        remaining -= int(counted)
        if remaining == 0:
            return day
        if offset < MAX_SCAN_DAYS:
            day = _move(day, direction)
    raise DeadlineError("calendar_search_limit")


def _shift(calendars, candidate, rule, trace):
    if rule == "none":
        return candidate
    direction = 1 if rule == "next_working" else -1
    day = candidate
    for offset in range(MAX_SCAN_DAYS + 1):
        info = calendars.day(day)
        trace.append({**info, "phase": "shift", "counted": False})
        if info["is_working"]:
            return day
        if offset < MAX_SCAN_DAYS:
            day = _move(day, direction)
    raise DeadlineError("calendar_search_limit")


def _month_date(anchor, offset, end_policy):
    index = (anchor.year - 1) * 12 + anchor.month - 1 + offset
    year, month = index // 12 + 1, index % 12 + 1
    if not 1 <= year <= 9999:
        raise DeadlineError("date_range_exceeded")
    last_day = monthrange(year, month)[1]
    if anchor.day > last_day and end_policy == "reject":
        raise DeadlineError("month_day_missing")
    return date(year, month, min(anchor.day, last_day))


def _calculate(rule, anchor_value, policy, calendars):
    unit, amount = rule["unit"], int(rule["value"])
    direction = 1 if rule["direction"] == "after" else -1
    bound = 120 if unit == "months" else MAX_SCAN_DAYS * 24 if unit == "hours" else MAX_SCAN_DAYS
    if amount > bound:
        raise DeadlineError("duration_limit")
    trace = []
    if unit == "hours":
        if policy["hours_mode"] != "elapsed" or policy["count_anchor_day"] is not None or policy["month_end"] is not None:
            raise DeadlineError("incompatible_counting_policy")
        if rule["shift_from_nonworking"] != "none":
            raise DeadlineError("hour_calendar_shift_unsupported")
        if len(anchor_value) == 10 or anchor_value.endswith("-00:00"):
            raise DeadlineError("aware_anchor_required")
        try:
            anchor = datetime.fromisoformat(anchor_value.upper().replace("Z", "+00:00"))
            if anchor.utcoffset() is None:
                raise DeadlineError("aware_anchor_required")
            local_zone = ZoneInfo("Asia/Bishkek")
            utc_anchor = anchor.astimezone(timezone.utc)
            due = utc_anchor + timedelta(hours=direction * amount)
            return {"unit": unit, "amount": amount, "direction": rule["direction"],
                    "anchor_utc": utc_anchor.isoformat(), "anchor_local": anchor.astimezone(local_zone).isoformat(),
                    "unshifted_due": due.astimezone(local_zone).isoformat(),
                    "due": due.astimezone(local_zone).isoformat(), "due_utc": due.isoformat(),
                    "calendar_trace": [], "calendar_years_used": [], "month_end_clamped": False}
        except DeadlineError:
            raise
        except (ValueError, OverflowError):
            raise DeadlineError("date_range_exceeded") from None
        except ZoneInfoNotFoundError:
            raise DeadlineError("timezone_unavailable") from None
    if len(anchor_value) != 10:
        raise DeadlineError("local_date_anchor_required")
    anchor = date.fromisoformat(anchor_value)
    if policy["hours_mode"] is not None:
        raise DeadlineError("incompatible_counting_policy")
    if unit == "months":
        if policy["month_end"] is None or policy["count_anchor_day"] is not None:
            raise DeadlineError("incompatible_counting_policy")
        candidate = _month_date(anchor, direction * amount, policy["month_end"])
    else:
        if policy["month_end"] is not None or type(policy["count_anchor_day"]) is not bool:
            raise DeadlineError("incompatible_counting_policy")
        if unit == "calendar_days":
            candidate = _move(anchor, direction * (amount - int(policy["count_anchor_day"])))
        else:
            candidate = _working_deadline(calendars, anchor, amount, direction, policy["count_anchor_day"], trace)
    due = _shift(calendars, candidate, rule["shift_from_nonworking"], trace)
    return {"unit": unit, "amount": amount, "direction": rule["direction"], "anchor_local": anchor.isoformat(),
            "unshifted_due": candidate.isoformat(), "due": due.isoformat(), "due_utc": None,
            "calendar_trace": trace, "calendar_years_used": sorted({row["calendar_year"] for row in trace}),
            "month_end_clamped": unit == "months" and candidate.day != anchor.day}


class DeadlineReview:
    def __init__(self, meta, countries, units, *, source_hash, calendars):
        report = validate_bundle(meta, countries, units, source_hash=source_hash)
        if not report.ok:
            raise DeadlineError("invalid_bundle")
        self._bundle = report.normalized_bundle
        self._bundle_hash = report.bundle_hash
        self._units = {row["unit_id"]: row for row in self._bundle["units"]}
        self._calendars = WorkCalendars(calendars)

    def evaluate(self, request):
        try:
            check_tree(request)
        except InvalidDocument:
            raise DeadlineError("invalid_request") from None
        if schema_errors(request, DEADLINE_REQUEST):
            raise DeadlineError("invalid_request")
        try:
            anchor_value = request["anchor"]["value"]
            if len(anchor_value) == 10:
                date.fromisoformat(anchor_value)
            else:
                datetime.fromisoformat(anchor_value.replace("Z", "+00:00"))
        except ValueError:
            raise DeadlineError("invalid_request") from None
        request = deepcopy(request)
        row = self._units.get(request["rule_unit_id"])
        if row is None or row["kind"] != "deadline":
            raise DeadlineError("unknown_deadline_rule")
        value = row["value"]
        blocked = []
        if value is None:
            blocked.append("rule_value_missing")
        if request["policy"] is None:
            blocked.append("counting_policy_missing")
        if value is not None and request["anchor"]["name"] != value["anchor"]:
            blocked.append("anchor_name_mismatch")
        result = {"format": "kg-deadline-review/1", "mode": "review_only", "algorithm_version": ALGORITHM,
                  "source_hash": self._bundle["meta"]["source_hash"], "bundle_hash": self._bundle_hash,
                  "version_label": self._bundle["meta"]["version_label"], "input_hash": _hash(request),
                  "rule_unit_id": row["unit_id"], "rule_findings": review_findings(row),
                  "calendar_set_hash": self._calendars.content_hash, "calendars": self._calendars.describe(),
                  "policy": request["policy"], "source_boundary_inclusive": value["boundary_inclusive"] if value else None,
                  "boundary_interpretation_approved": False, "publication_approved": False, "may_quote": False,
                  "exact_deadline": None, "arithmetic_status": "needs_input", "blocked_by": blocked, "scenario": None}
        if blocked:
            return result
        try:
            scenario = _calculate(value, request["anchor"]["value"], request["policy"], self._calendars)
        except (CalendarError, DeadlineError) as exc:
            result["blocked_by"] = [exc.code]
            if isinstance(exc, CalendarError) and exc.year is not None:
                result["unavailable_calendar_year"] = exc.year
            return result  # Never return a partially calculated date or trace.
        scenario["status"] = "unapproved_scenario"
        result.update(arithmetic_status="computed_scenario", scenario=scenario)
        # Includes resolved offsets/result: tzdata changes cannot silently retain the same result fingerprint.
        result["calculation_hash"] = _hash({"algorithm": ALGORITHM, "bundle_hash": self._bundle_hash,
            "calendars": self._calendars.content_hash, "request": request, "scenario": scenario})
        return result
