"""Контракт preflight kg-entry-bundle/1. Все поля перечислены явно."""


def obj(properties, required=None):
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties) if required is None else required}


def enum(*values):
    return {"enum": list(values)}


def array(items, maximum=1000):
    return {"type": "array", "items": items, "uniqueItems": True, "maxItems": maximum}


TEXT = {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": r"\S"}
POS = {"type": "integer", "minimum": 1}
NONNEG = {"type": "number", "minimum": 0}
BOOL = {"type": "boolean"}
DATE = {"type": "string", "format": "date", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
STAMP = {"type": "string", "format": "date-time"}
ISO3 = {"type": "string", "pattern": "^[A-Z]{3}$"}
COUNTRIES = {**array(TEXT), "minItems": 1}


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


META_SCHEMA = obj({
    "schema_version": {"const": "kg-entry-bundle/1"}, "set_code": {"const": "kg_entry"},
    "version_label": TEXT, "source_document": TEXT,
    "source_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "prepared_by": TEXT, "prepared_at": STAMP, "effective_from": nullable(DATE),
}, ["schema_version", "set_code", "version_label", "source_document", "source_hash", "prepared_by", "prepared_at"])
COUNTRIES_SCHEMA = {"type": "object", "minProperties": 1, "maxProperties": 2000,
                    "propertyNames": {"type": "string", "minLength": 1, "maxLength": 200},
                    "additionalProperties": ISO3}

VALUE_SCHEMAS = {
    "visa_free_regime": obj({"days": POS, "window_days": POS,
                             "work_needs_unified_permit": BOOL, "countries": COUNTRIES}),
    "registration_exemption": obj({"days": POS}),
    "registration_default": obj({"deadline_working_days_from_border": POS,
                                  "not_in_list": array(TEXT)}, ["deadline_working_days_from_border", "not_in_list"]),
    "registration_term": obj({"days": POS}),
    "special_regime": obj({"days": POS, "reentry_after_days": {"type": "integer", "minimum": 0},
                           "visa_inside_kg": BOOL, "requires": TEXT,
                           "applies_to": {**obj({"countries": COUNTRIES, "document_type": TEXT, "condition": TEXT}, []),
                                          "minProperties": 1}}, ["days", "applies_to"]),
    "visa_required_regime": obj({"procedure": enum("simplified", "general"),
                                 "scope": enum("all_types", "business_tourist", "tourist_gcc_resident", None),
                                 "gknb_approval": BOOL,
                                 "countries": {"anyOf": [COUNTRIES, {"const": "all_others"}]}}),
    "rule_param": obj({"value": {}, "unit": enum("days", "working_days", "calendar_days", "bool", "list"),
                       "anchor": TEXT, "inclusive": BOOL}, ["value", "unit"]),
    "deadline": obj({"value": POS, "unit": enum("hours", "calendar_days", "working_days", "months"),
                     "anchor": TEXT, "direction": enum("before", "after"), "timezone": {"const": "Asia/Bishkek"},
                     "boundary_inclusive": BOOL, "shift_from_nonworking": enum("none", "next_working", "previous_working")}),
    "processing_time": obj({"standard_wd": POS, "urgent_wd": POS,
                            "urgent_multiplier": {"type": "number", "exclusiveMinimum": 0},
                            "anchor": {"const": "full_package"}}, ["standard_wd", "anchor"]),
    "tariff": obj({"amount": NONNEG, "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
                   "per": enum("person", "application"), "component": enum("service", "government", "bank", "partner")}),
    "template": obj({"lang": {"type": "string", "pattern": "^[a-z]{2}$"},
                     "text": {"type": "string", "minLength": 1, "maxLength": 20000},
                     "placeholders": array({"type": "string", "pattern": "^[a-z_][a-z0-9_]*$"})}),
    "escalation_trigger": obj({"condition": TEXT, "action": TEXT}),
}
ID_PATTERNS = {
    "visa_free_regime": r"KG\.VF\.[A-Z0-9_]+", "registration_exemption": r"KG\.REG\.EXEMPT\.[A-Z]{3}",
    "registration_default": r"KG\.REG\.DEFAULT", "registration_term": r"KG\.REG\.TERM\.[A-Z]{3}",
    "special_regime": r"KG\.SP\.[A-Z0-9_]+", "visa_required_regime": r"KG\.VR\.[A-Z0-9_]+",
    "rule_param": r"KG\.(RULE|WATCH)\.[A-Z0-9_]+", "deadline": r"KG\.DL\.[A-Z0-9_]+",
    "processing_time": r"KG\.PT\.[A-Z0-9_]+", "tariff": r"KG\.FEE\.[A-Z0-9_]+\.[A-Z0-9_]+",
    "template": r"KG\.TPL\.[A-Z0-9_]+", "escalation_trigger": r"KG\.ESC\.[A-Z0-9_]+",
}
UNIT_SCHEMA = obj({
    "unit_id": TEXT, "kind": enum(*VALUE_SCHEMAS), "title": TEXT, "section": TEXT, "page": TEXT,
    "source_ref": TEXT, "source_text": nullable(TEXT), "label": enum("none", "verify", "practice", "decision"),
    "confirmation_status": enum("confirmed", "needs_verification", "blocked", "decision_pending"),
    "value": nullable({"type": "object"}), "value_schema_version": {"const": 1},
    "blocked_value": nullable({"type": "object", "minProperties": 1}), "conflict_ref": nullable(TEXT),
    "effective_from": nullable(DATE), "effective_to": nullable(DATE), "verified_at": nullable(STAMP),
    "verified_by": nullable(TEXT), "review_due_at": nullable(STAMP), "owner": TEXT,
}, ["unit_id", "kind", "title", "section", "page", "source_ref", "label", "confirmation_status",
    "value", "value_schema_version", "owner"])
UNITS_SCHEMA = {"type": "array", "minItems": 1, "maxItems": 5000, "items": UNIT_SCHEMA}
