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

# Preserve v1 validation for immutable historical snapshots. New intake is explicit v2.
LEGACY_REQUEST_SCHEMA = deepcopy(REQUEST_SCHEMA)
V2_REQUEST_SCHEMA = deepcopy(REQUEST_SCHEMA)
V2_REQUEST_SCHEMA["properties"]["format"] = {"const": "kg-qualification-review-input/2"}
INTAKE_FIELDS = (
    "client_type", "applicants_count", "purpose_details", "multiple_entries_needed",
    "entry_point", "entry_point_other", "tickets_bought", "urgency_deadline", "event_dates",
    "in_kg_entry_point", "purpose_declared_at_border", "previous_refusals_details", "family",
)
_v2_profile = V2_REQUEST_SCHEMA["properties"]["profile"]["properties"]
_v2_profile.update({k: deepcopy(_slots["properties"][k]) for k in INTAKE_FIELDS})
# No names, tax identifiers or contact details in this stage's invitation profile.
_v2_profile["inviting_party"] = obj({k: deepcopy(_slots["properties"]["inviting_party"]["properties"][k])
    for k in ("exists", "type", "has_portal_cabinet", "can_issue_letter", "tax_debts_absent")}, [])
_v2_profile["requested_process"] = enum("visa", "unified_permit", "resident_card", "residence_permit", "regularization", "unknown")
_v2_profile["escalation"] = obj({k: deepcopy(_slots["$defs"]["tri_bool"])
    for k in ("complaint", "refund_question", "legal_question", "conflicting_answers")}, [])
REQUEST_SCHEMA = {"oneOf": [LEGACY_REQUEST_SCHEMA, V2_REQUEST_SCHEMA], "$defs": deepcopy(_slots["$defs"])}
