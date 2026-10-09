"""Minimal partial interview, sharing slot types without names or free-text fields."""
from copy import deepcopy

from .bundle_schema import DATE, enum, obj
from .condition_schema import FACTS_SCHEMA
from .slots import slots_schema

_slots = slots_schema()
PROFILE_FIELDS = (
    "citizenship", "entry_passport_country", "document_type", "passport_expiry",
    "passport_pages_ok", "purpose", "current_location", "entry_date", "exit_date",
    "in_kg_since", "current_basis_in_kg", "current_visa_type", "current_basis_until",
    "registration_until", "violations", "previous_refusals_kg",
)
_profile = obj({k: deepcopy(_slots["properties"][k]) for k in PROFILE_FIELDS}, [])
# An incomplete interview is valid input; missing answers are explicit in the report.
_profile["properties"]["violations"]["required"] = []
_facts = deepcopy(FACTS_SCHEMA)
for _key in ("entry_passport_country", "document_type"):
    del _facts["properties"][_key]

REQUEST_SCHEMA = obj({
    "format": {"const": "kg-qualification-review-input/1"}, "as_of": DATE,
    "language": enum("ru", "en"), "profile": _profile, "condition_facts": _facts,
}, ["format", "as_of", "language", "profile"])
REQUEST_SCHEMA["$defs"] = deepcopy(_slots["$defs"])
