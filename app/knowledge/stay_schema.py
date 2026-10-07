"""Review-only history snapshot; no contacts, passport numbers or client decisions."""
from .bundle_schema import BOOL, DATE, ISO3, enum, nullable, obj

BASES = ("visa_free", "visa", "ep", "resident_card", "residence_permit", "registration_contract", "unknown")
ID = {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"}
POLICY = obj({
    "status": {"const": "proposed"}, "count_entry_day": BOOL, "count_exit_day": BOOL,
    "window_anchor": {"const": "each_day_backward_inclusive"}, "timezone": {"const": "Asia/Bishkek"},
})
INTERVAL = obj({
    "id": ID, "entry_date": DATE, "exit_date": nullable(DATE), "basis": enum(*BASES),
    "passport_country": nullable(ISO3), "passport_continuity": enum("same", "changed", "unknown"),
    "confirmed": BOOL,
})
STAY_REQUEST = obj({
    "schema_version": {"const": "kg-stay-review-input/1"},
    "rule_unit_id": {"type": "string", "pattern": "^KG\\.VF\\.[A-Z0-9_]{1,64}$"},
    "as_of": DATE, "history_complete": nullable(BOOL),
    "history": {"type": "array", "items": INTERVAL, "maxItems": 1000},
    "trip": obj({"mode": enum("new_entry", "continue_open"), "start_date": DATE, "end_date": DATE,
                 "passport_country": ISO3, "basis": enum(*BASES)}),
    "policy": nullable(POLICY),
})
