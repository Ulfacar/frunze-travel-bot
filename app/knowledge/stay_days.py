"""Проверочные сценарии CALC-02; арифметика не разрешает въезд и не утверждает нормы."""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from datetime import date
import hashlib

from .bundle import validate_bundle
from .review import canonical, review_findings
from .stay_schema import STAY_REQUEST
from .validation import InvalidDocument, check_tree, schema_errors

ALGORITHM = "kg-stay-arithmetic/1"
COUNT_RULE_IDS = ("KG.RULE.COUNT_ENTRY_DAY", "KG.RULE.COUNT_EXIT_DAY", "KG.RULE.WINDOW_ANCHOR")
MAX_PLAN_DAYS = 730
MAX_WINDOW_DAYS = 3660


class StayReviewError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _ordinal(value):
    return date.fromisoformat(value).toordinal()


def _iso(value):
    return date.fromordinal(value).isoformat()


def _digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _merge(intervals):
    """Inclusive integer intervals; adjacent pieces can share one prefix sum."""
    merged = []
    for start, end, ids in sorted(intervals):
        if start > end:
            continue
        if merged and start <= merged[-1][1] + 1:
            old_start, old_end, old_ids = merged[-1]
            merged[-1] = (old_start, max(old_end, end), sorted(set(old_ids) | set(ids)))
        else:
            merged.append((start, end, sorted(ids)))
    return merged


class _Union:
    def __init__(self, intervals):
        self.intervals = _merge(intervals)
        self.starts = [a for a, _, _ in self.intervals]
        self.prefix = [0]
        for a, b, _ in self.intervals:
            self.prefix.append(self.prefix[-1] + b - a + 1)

    def _through(self, day):
        i = bisect_right(self.starts, day) - 1
        if i < 0:
            return 0
        a, b, _ = self.intervals[i]
        return self.prefix[i] + min(day, b) - a + 1

    def between(self, start, end):
        return self._through(end) - self._through(start - 1)

    def summary(self):
        return [{"from": _iso(a), "to": _iso(b), "days": b - a + 1, "record_ids": ids}
                for a, b, ids in self.intervals]


class StayDayReview:
    def __init__(self, meta, countries, units, *, source_hash):
        report = validate_bundle(meta, countries, units, source_hash=source_hash)
        if not report.ok:
            raise StayReviewError("invalid_bundle")
        self._bundle = report.normalized_bundle
        self._hash = report.bundle_hash
        self._units = {u["unit_id"]: u for u in self._bundle["units"]}
        self._countries = frozenset(self._bundle["countries"].values())

    def evaluate(self, request):
        try:
            check_tree(request)
        except InvalidDocument:
            raise StayReviewError("invalid_request") from None
        if schema_errors(request, STAY_REQUEST):
            raise StayReviewError("invalid_request")
        data = deepcopy(request)
        data["history"].sort(key=lambda r: r["id"])
        history, trip, policy = data["history"], data["trip"], data["policy"]
        as_of, start, end = map(_ordinal, (data["as_of"], trip["start_date"], trip["end_date"]))
        if start < as_of or end < start or end - start + 1 > MAX_PLAN_DAYS:
            raise StayReviewError("invalid_plan_dates")
        if len({r["id"] for r in history}) != len(history):
            raise StayReviewError("duplicate_record_id")
        if any(code is not None and code not in self._countries for code in
               [trip["passport_country"]] + [r["passport_country"] for r in history]):
            raise StayReviewError("unknown_country")
        opened = []
        for row in history:
            a = _ordinal(row["entry_date"])
            b = _ordinal(row["exit_date"]) if row["exit_date"] is not None else None
            if a > as_of or (b is not None and (b < a or b > as_of)):
                raise StayReviewError("invalid_history_dates")
            if b is None:
                opened.append(row)
        if len(opened) > 1:
            raise StayReviewError("multiple_open_intervals")
        # An open stay cannot coexist with a later separate visit in the snapshot.
        if opened and any(r["exit_date"] is not None and _ordinal(r["exit_date"]) > _ordinal(opened[0]["entry_date"])
                          for r in history):
            raise StayReviewError("conflicting_open_history")
        rule = self._units.get(data["rule_unit_id"])
        if rule is None or rule["kind"] != "visa_free_regime":
            raise StayReviewError("unknown_visa_free_rule")

        findings = {"review_only", "counting_policy_not_approved", "rule_selection_not_evaluated"}
        if data["history_complete"] is not True:
            findings.add("history_incomplete")
        if any(r["confirmed"] is not True for r in history):
            findings.add("history_unconfirmed")
        if any(r["passport_country"] != trip["passport_country"] or r["passport_continuity"] != "same" for r in history):
            findings.add("passport_history_requires_review")
        if trip["basis"] != "visa_free" or any(r["basis"] != "visa_free" for r in history):
            findings.add("basis_history_requires_review")
        if review_findings(rule):
            findings.add("candidate_rule_requires_review")
        parameters = [{"unit_id": uid, "present": uid in self._units,
                       "confirmation_status": self._units[uid]["confirmation_status"] if uid in self._units else None}
                      for uid in COUNT_RULE_IDS]
        blocked = []
        if policy is None:
            blocked.append("counting_policy_missing")
        if rule["value"] is None:
            blocked.append("rule_value_missing")
        elif trip["passport_country"] not in rule["value"]["countries"]:
            blocked.append("country_not_in_candidate_rule")
        if trip["mode"] == "new_entry" and opened:
            blocked.append("open_stay_requires_resolution")
        if trip["mode"] == "continue_open" and (not opened or start != as_of):
            blocked.append("continuation_requires_open_stay_at_as_of")
        result = {"format": "kg-stay-review/1", "mode": "review_only", "algorithm_version": ALGORITHM,
                  "source_hash": self._bundle["meta"]["source_hash"], "bundle_hash": self._hash,
                  "version_label": self._bundle["meta"]["version_label"], "input_hash": _digest(data),
                  "rule_unit_id": rule["unit_id"], "rule_findings": review_findings(rule),
                  "counting_rules": parameters, "policy": policy,
                  "publication_approved": False, "may_quote": False, "entry_eligibility_evaluated": False,
                  "exact_remaining_days": None, "selected_regime": None,
                  "arithmetic_status": "needs_input" if blocked else "computed_scenario",
                  "blocked_by": blocked, "findings": sorted(findings), "scenario": None}
        if blocked:
            return result
        # JSON Schema integer admits integral JSON numbers such as 30.0. They
        # are validated above; ordinal arithmetic needs actual Python integers.
        limit, window = int(rule["value"]["days"]), int(rule["value"]["window_days"])
        if window > MAX_WINDOW_DAYS or limit > window or start - window + 1 < 1:
            raise StayReviewError("unsupported_window")
        entry_shift, exit_shift = int(not policy["count_entry_day"]), int(not policy["count_exit_day"])
        observed, projected = [], []
        for row in history:
            a = _ordinal(row["entry_date"]) + entry_shift
            # as_of is an observation cutoff, never a fictional border exit.
            b = as_of if row["exit_date"] is None else _ordinal(row["exit_date"]) - exit_shift
            observed.append((a, b, [row["id"]]))
            projected.append((a, end - exit_shift if row["exit_date"] is None else b, [row["id"]]))
        if trip["mode"] == "new_entry":
            projected.append((start + entry_shift, end - exit_shift, ["@planned_trip"]))
        known, scenario = _Union(observed), _Union(projected)
        daily = []
        for day in range(start, end + 1):
            left = day - window + 1
            used = scenario.between(left, day)
            daily.append({"date": _iso(day), "window_start": _iso(left), "window_end": _iso(day),
                          "reported_history_days": known.between(left, day), "scenario_presence_days": used,
                          "scenario_headroom": limit - used,
                          "limit_relation": "exceeded" if used > limit else "at_limit" if used == limit else "below_limit"})
        result["scenario"] = {
            "status": "unapproved_scenario", "unit": "calendar_days", "limit_days": limit, "window_days": window,
            "record_ids": [r["id"] for r in history], "counted_intervals": scenario.summary(),
            "daily": daily, "max_presence_days": max(r["scenario_presence_days"] for r in daily),
            "first_exceeded_date": next((r["date"] for r in daily if r["limit_relation"] == "exceeded"), None),
            "first_at_limit_date": next((r["date"] for r in daily if r["limit_relation"] == "at_limit"), None),
        }
        result["calculation_hash"] = _digest({"algorithm": ALGORITHM, "bundle_hash": self._hash, "input": data})
        return result
