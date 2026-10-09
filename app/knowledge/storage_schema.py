"""Inputs for trusted admin storage; client slots and raw passport numbers are not accepted."""
from .bundle_schema import BOOL, DATE, ISO3, enum, nullable, obj
from .stay_schema import BASES, ID, STAY_REQUEST

PASSPORT_REF = nullable({"type": "string", "pattern": "^[a-f0-9]{32}$"})
HISTORY_INTERVAL = obj({
    "ref": ID, "entry_date": DATE, "exit_date": nullable(DATE), "basis": enum(*BASES),
    "passport_country": nullable(ISO3), "passport_ref": PASSPORT_REF,
    "evidence": enum("esuvm", "passport_stamp", "boarding_pass", "visa_document", "client_statement", "crm_record"),
    "confirmed": BOOL,
})
HISTORY = obj({
    "format": {"const": "kg-stay-history/1"}, "as_of": DATE, "history_complete": nullable(BOOL),
    "intervals": {"type": "array", "items": HISTORY_INTERVAL, "maxItems": 1000},
})
STORED_STAY_REQUEST = obj({
    **{key: STAY_REQUEST["properties"][key] for key in ("rule_unit_id", "trip", "policy")},
    "passport_ref": PASSPORT_REF,
})
