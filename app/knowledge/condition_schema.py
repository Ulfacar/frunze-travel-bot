"""Явный контракт draft-условий и минимальных фактов без контактных/паспортных данных."""
from .bundle_schema import BOOL, DATE, ISO3, POS, TEXT, array, enum, nullable, obj
from .country_index import DOCUMENT_TYPES

HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
CODES = {**array(ISO3), "minItems": 1}
TRI = nullable(BOOL)
OPTIONAL_CODE = {"anyOf": [ISO3, enum("unknown", None)]}
ISSUERS = enum("USA", "GBR", "SCHENGEN", "other", "unknown", None)


def predicate(name, **fields):
    return obj({"type": {"const": name}, **fields})


PREDICATE = {"oneOf": [
    predicate("passport_country_in", countries=CODES),
    predicate("document_type_is", value=enum(*sorted(DOCUMENT_TYPES - {"unknown"}))),
    predicate("permanent_residence_in", countries=CODES),
    predicate("residence_permit_in", countries=CODES),
    predicate("foreign_visa", issuers={**array(enum("USA", "GBR", "SCHENGEN")), "minItems": 1},
              validity_years_gt={"const": 3, "type": "integer"}),
    predicate("organized_tour_group", country=ISO3, minimum=POS, maximum=POS,
              petition_required={"const": True}),
    predicate("visa_type_is", value={"type": "string", "pattern": "^[A-Z0-9]{1,8}$"}),
    predicate("stay_within_months", maximum={"type": "integer", "const": 1}),
]}
OUTCOME = {**obj({
    "stay_days": POS, "window_days": POS, "reentry_after_days": {"type": "integer", "minimum": 0},
    "visa_inside_kg": BOOL, "visa_inside_exception": {"const": "force_majeure"},
    "work_permit_requirement": {"const": "unknown"},
    "visa_type": {"const": "TS"}, "max_stay_months": {"const": 1, "type": "integer"},
    "gknb_approval": BOOL,
}, []), "minProperties": 1}
RULE = obj({
    "unit_id": TEXT,
    "source_locations": {**array(obj({"page": {"type": "integer", "minimum": 1, "maximum": 94},
                                     "section": TEXT})), "minItems": 1},
    "all": {**array(PREDICATE, maximum=12), "minItems": 1},
    "source_outcome": OUTCOME,
    "unresolved": array(TEXT),
})
CATALOG_SCHEMA = obj({
    "format": {"const": "kg-entry-conditions/1"}, "status": {"const": "draft"},
    "source_hash": HASH, "bundle_hash": HASH, "source_capture_sha256": HASH,
    "source_date": DATE, "date_basis": {"const": "source_claim"},
    "publication_approved": {"const": False},
    "rules": {**array(RULE, maximum=50), "minItems": 1},
})
RESIDENCE_ITEM = obj({
    "country": OPTIONAL_CODE, "kind": enum("residence_permit", "resident_card", "other", "unknown", None),
    "permanent": TRI,
}, [])
VISA_ITEM = obj({"issuer": ISSUERS, "over_three_years_verified": TRI}, [])


def documents(item):
    return obj({"items": {"type": "array", "maxItems": 20, "items": item}, "complete": TRI}, ["items"])


FACTS_SCHEMA = obj({
    "schema_version": {"const": "kg-entry-condition-facts/1"},
    "entry_passport_country": OPTIONAL_CODE,
    "document_type": enum(*sorted(DOCUMENT_TYPES), None),
    "residence_documents": documents(RESIDENCE_ITEM), "foreign_visas": documents(VISA_ITEM),
    "tour_group": obj({"organized": TRI, "participants_count": {"anyOf": [
        {"type": "integer", "minimum": 1, "maximum": 10000}, {"type": "null"}]},
        "all_members_country": OPTIONAL_CODE, "tourism_authority_petition": TRI}, []),
    "requested_visa_type": {"anyOf": [{"type": "string", "pattern": "^[A-Z0-9]{1,8}$"}, enum("unknown", None)]},
    "stay_within_one_month_verified": TRI,
}, ["schema_version"])
