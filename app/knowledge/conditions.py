"""Трёхзначная проверка профиля по draft-условиям, не разрешение въезда/публикации."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from .bundle import validate_bundle
from .condition_schema import CATALOG_SCHEMA, FACTS_SCHEMA
from .review import review_findings
from .validation import InvalidDocument, check_tree, schema_errors


class ConditionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _validated(data, schema, code):
    try:
        check_tree(data)
    except InvalidDocument:
        raise ConditionError(code) from None
    if schema_errors(data, schema):
        raise ConditionError(code)


def _test(value, expected, path):
    if value is None or value == "unknown":
        return "unknown", [path]
    return ("met" if expected(value) else "not_met"), []


def _all(results):
    if any(status == "not_met" for status, _ in results):
        return "not_met", []
    missing = sorted({path for status, paths in results if status == "unknown" for path in paths})
    return ("unknown", missing) if any(s == "unknown" for s, _ in results) else ("met", [])


def _any_document(facts, field, inspect):
    document_set = facts.get(field)
    if document_set is None:
        return "unknown", [field]
    results = [inspect(item, f"{field}.items[{i}]") for i, item in enumerate(document_set["items"])]
    if any(status == "met" for status, _ in results):
        return "met", []
    missing = {path for status, paths in results if status == "unknown" for path in paths}
    if document_set.get("complete") is not True:
        missing.add(f"{field}.complete")
    return ("unknown", sorted(missing)) if missing else ("not_met", [])


def _evaluate(clause, facts):
    kind = clause["type"]
    if kind == "passport_country_in":
        return _test(facts.get("entry_passport_country"), lambda v: v in clause["countries"], "entry_passport_country")
    if kind == "document_type_is":
        return _test(facts.get("document_type"), lambda v: v == clause["value"], "document_type")
    if kind == "visa_type_is":
        return _test(facts.get("requested_visa_type"), lambda v: v == clause["value"], "requested_visa_type")
    if kind == "stay_within_months":
        return _test(facts.get("stay_within_one_month_verified"), lambda v: v is True, "stay_within_one_month_verified")
    if kind in ("permanent_residence_in", "residence_permit_in"):
        def inspect(item, path):
            checks = [_test(item.get("country"), lambda v: v in clause["countries"], path + ".country")]
            if kind == "permanent_residence_in":
                checks.append(_test(item.get("permanent"), lambda v: v is True, path + ".permanent"))
            else:
                checks.append(_test(item.get("kind"), lambda v: v in ("residence_permit", "resident_card"), path + ".kind"))
            return _all(checks)
        return _any_document(facts, "residence_documents", inspect)
    if kind == "foreign_visa":
        def inspect(item, path):
            return _all([
                _test(item.get("issuer"), lambda v: v in clause["issuers"], path + ".issuer"),
                _test(item.get("over_three_years_verified"), lambda v: v is True, path + ".over_three_years_verified"),
            ])
        return _any_document(facts, "foreign_visas", inspect)
    if kind == "organized_tour_group":
        group = facts.get("tour_group", {})
        return _all([
            _test(group.get("organized"), lambda v: v is True, "tour_group.organized"),
            _test(group.get("participants_count"), lambda v: clause["minimum"] <= v <= clause["maximum"], "tour_group.participants_count"),
            _test(group.get("all_members_country"), lambda v: v == clause["country"], "tour_group.all_members_country"),
            _test(group.get("tourism_authority_petition"), lambda v: v is True, "tour_group.tourism_authority_petition"),
        ])
    raise ConditionError("unsupported_predicate")  # schema already rejects unknown types


class ConditionReview:
    def __init__(self, catalog, meta, countries, units, *, source_hash):
        report = validate_bundle(meta, countries, units, source_hash=source_hash)
        if not report.ok:
            raise ConditionError("invalid_bundle")
        _validated(catalog, CATALOG_SCHEMA, "invalid_catalog")
        if catalog["source_hash"] != source_hash or catalog["bundle_hash"] != report.bundle_hash:
            raise ConditionError("catalog_source_mismatch")
        snapshot = report.normalized_bundle
        known = frozenset(snapshot["countries"].values())
        self._units = {u["unit_id"]: u for u in snapshot["units"]}
        seen = set()
        for rule in catalog["rules"]:
            uid = rule["unit_id"]
            if uid in seen or uid not in self._units or self._units[uid]["kind"] not in (
                    "visa_free_regime", "visa_required_regime", "special_regime"):
                raise ConditionError("invalid_rule_reference")
            seen.add(uid)
            predicates = set()
            for clause in rule["all"]:
                if clause["type"] in predicates:
                    raise ConditionError("duplicate_predicate")
                predicates.add(clause["type"])
                codes = clause.get("countries", []) + ([clause["country"]] if "country" in clause else [])
                if any(code not in known for code in codes):
                    raise ConditionError("unknown_catalog_country")
                if clause["type"] == "organized_tour_group" and clause["minimum"] > clause["maximum"]:
                    raise ConditionError("invalid_group_range")
        self._catalog = deepcopy(catalog)
        self._catalog["rules"].sort(key=lambda r: r["unit_id"])
        self._known = known
        self._bundle_hash = report.bundle_hash
        self._version = snapshot["meta"]["version_label"]
        self._catalog_hash = hashlib.sha256(json.dumps(catalog, sort_keys=True, ensure_ascii=False,
                                                      separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

    def evaluate(self, facts):
        _validated(facts, FACTS_SCHEMA, "invalid_facts")
        country_values = [facts.get("entry_passport_country"), facts.get("tour_group", {}).get("all_members_country")]
        country_values += [item.get("country") for item in facts.get("residence_documents", {}).get("items", [])]
        if any(value not in (None, "unknown") and value not in self._known for value in country_values):
            raise ConditionError("unknown_fact_country")
        results = []
        for rule in self._catalog["rules"]:
            checks = []
            for clause in rule["all"]:
                status, missing = _evaluate(clause, facts)
                checks.append({"predicate": clause["type"], "status": status, "missing_facts": missing})
            status, missing = _all([(c["status"], c["missing_facts"]) for c in checks])
            unit = self._units[rule["unit_id"]]
            results.append({
                "unit_id": rule["unit_id"], "status": status, "checks": checks, "missing_facts": missing,
                "source_locations": deepcopy(rule["source_locations"]),
                "source_outcome": deepcopy(rule["source_outcome"]), "unresolved": list(rule["unresolved"]),
                "unit_confirmation_status": unit["confirmation_status"], "unit_value_present": unit["value"] is not None,
                "unit_findings": review_findings(unit), "may_quote": False,
            })
        return {"format": "kg-condition-review/1", "mode": "profile_conditions_only",
                "bundle_hash": self._bundle_hash, "catalog_hash": self._catalog_hash,
                "source_hash": self._catalog["source_hash"], "version_label": self._version,
                "source_date": self._catalog["source_date"], "date_basis": "source_claim",
                "publication_approved": False, "may_quote": False, "selected_regime": None,
                "entry_eligibility_evaluated": False, "stay_and_reentry_calculated": False,
                "document_authenticity_and_validity_checked": False, "rules": results}
