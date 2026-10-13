"""Explicit draft calendars and proposed deadline policy, without runtime approval."""
from .bundle_schema import BOOL, DATE, TEXT, array, enum, nullable, obj

# jsonschema's optional RFC3339 dependency may be absent. Keep the shapes
# disjoint and validate actual datetime fields in DeadlineReview as well.
AWARE_STAMP = {"type": "string", "format": "date-time", "pattern":
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"}

CALENDAR_DAY = obj({
    "date": DATE, "is_working": BOOL,
    "kind": enum("public_holiday", "floating_holiday", "transfer_rest", "transfer_working", "weekend_override"),
    "title": TEXT, "source_ref": TEXT,
})
CALENDAR = obj({
    "format": {"const": "kg-work-calendar/1"}, "jurisdiction": {"const": "KG"},
    "timezone": {"const": "Asia/Bishkek"}, "schedule_kind": {"const": "government"},
    "year": {"type": "integer", "minimum": 1, "maximum": 9999},
    "version": {"type": "integer", "minimum": 1, "maximum": 1000000},
    "status": {"const": "draft"}, "completeness": enum("complete", "provisional"),
    "provisional_note": nullable(TEXT), "source_ref": TEXT,
    "week_rest_days": array({"type": "integer", "minimum": 1, "maximum": 7}, maximum=7),
    "days": array(CALENDAR_DAY, maximum=366),
})
CALENDARS = obj({"format": {"const": "kg-work-calendars/1"}, "calendars": array(CALENDAR, maximum=10)})
DEADLINE_REQUEST = obj({
    "format": {"const": "kg-deadline-review-input/1"},
    "rule_unit_id": {"type": "string", "pattern": "^KG\\.DL\\.[A-Z0-9_]{1,64}$"},
    "anchor": obj({"name": TEXT, "value": {"oneOf": [DATE, AWARE_STAMP]}}),
    "policy": nullable(obj({
        "status": {"const": "proposed"}, "timezone": {"const": "Asia/Bishkek"},
        "count_anchor_day": nullable(BOOL), "month_end": enum("clamp", "reject", None),
        "hours_mode": enum("elapsed", None),
    })),
})
