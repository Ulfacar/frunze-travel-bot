"""One review route for PDF 2.1; no draft rule becomes a client eligibility decision."""
from copy import deepcopy
from datetime import date
import hashlib

from .bundle import validate_bundle
from .conditions import ConditionReview
from .country_index import CountryRuleIndex
from .qualification_schema import REQUEST_SCHEMA
from .review import canonical, review_findings
from .validation import InvalidDocument, check_tree, schema_errors

ALGORITHM = "kg-qualification-review/1"
REGIMES = ("visa_free_regime", "visa_required_regime", "special_regime")
UNKNOWN = (None, "unknown", "not_applicable")
# Questions collect facts, never ask the applicant to approve legal interpretations.
QUESTIONS = {
    "citizenship": (1, "Какие у вас гражданства?", "What citizenships do you hold?"),
    "entry_passport_country": (1, "По паспорту какой страны вы будете въезжать?", "Which country's passport will you use to enter?"),
    "document_type": (2, "Какой у вас тип проездного документа?", "What type of travel document do you hold?"),
    "passport_expiry": (2, "Когда истекает срок действия этого документа?", "When does that document expire?"),
    "passport_pages_ok": (2, "Есть ли в документе свободные страницы?", "Does the document have blank pages?"),
    "purpose": (3, "Какова фактическая цель поездки?", "What is the actual purpose of your trip?"),
    "current_location": (3, "Вы сейчас в Кыргызстане или за его пределами?", "Are you currently in Kyrgyzstan or abroad?"),
    "entry_date": (5, "На какую дату планируется въезд?", "What is your planned entry date?"),
    "exit_date": (5, "На какую дату планируется выезд?", "What is your planned departure date?"),
    "in_kg_since": (5, "Когда вы въехали в Кыргызстан?", "When did you enter Kyrgyzstan?"),
    "current_basis_in_kg": (5, "На каком основании вы сейчас пребываете в Кыргызстане?", "What is your current basis of stay in Kyrgyzstan?"),
    "current_visa_type": (5, "Какой тип действующей визы у вас указан?", "What type is shown on your current visa?"),
    "current_basis_until": (5, "До какой даты действует ваше нынешнее основание пребывания?", "Until what date is your current basis of stay valid?"),
    "violations.overstay": (6, "Были ли нарушения срока пребывания?", "Have you previously overstayed?"),
    "violations.deportation_or_ban": (6, "Были ли депортация или запрет на въезд?", "Have you had a deportation or entry ban?"),
    "previous_refusals_kg": (6, "Были ли отказы по Кыргызстану?", "Have you had refusals relating to Kyrgyzstan?"),
    "registration_until": (7, "До какой даты у вас оформлена регистрация?", "Until what date is your registration valid?"),
}


class QualificationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _hash(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _get(profile, path):
    value = profile
    for key in path.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _known(value):
    return value not in UNKNOWN


def _day(value):
    return date.fromisoformat(value) if _known(value) else None


class QualificationReview:
    def __init__(self, meta, countries, units, *, source_hash, catalog=None):
        checked = validate_bundle(meta, countries, units, source_hash=source_hash)
        if not checked.ok:
            raise QualificationError("invalid_bundle")
        bundle = checked.normalized_bundle
        self._index = CountryRuleIndex(**bundle, source_hash=source_hash)
        self._conditions = ConditionReview(catalog, **bundle, source_hash=source_hash) if catalog is not None else None
        self._known = frozenset(bundle["countries"].values())
        self._units = {u["unit_id"]: u for u in bundle["units"]}
        self._source = {"source_hash": source_hash, "bundle_hash": checked.bundle_hash,
                        "catalog_hash": _hash(catalog) if catalog is not None else None,
                        "version_label": bundle["meta"]["version_label"]}

    def evaluate(self, request):
        try:
            check_tree(request)
            if schema_errors(request, REQUEST_SCHEMA):
                raise QualificationError("invalid_qualification_request")
        except InvalidDocument:
            raise QualificationError("invalid_qualification_request") from None
        request = deepcopy(request)
        p = request["profile"]
        today = date.fromisoformat(request["as_of"])
        citizenship = p.get("citizenship")
        country, document = p.get("entry_passport_country"), p.get("document_type")
        codes = (citizenship if isinstance(citizenship, list) else []) + ([country] if _known(country) else [])
        if any(c not in self._known for c in codes):
            raise QualificationError("unknown_profile_country")
        if _known(country) and isinstance(citizenship, list) and country not in citizenship:
            raise QualificationError("passport_citizenship_mismatch")
        start, end = _day(p.get("entry_date")), _day(p.get("exit_date"))
        if start and end and end < start:
            raise QualificationError("trip_date_order")
        if p.get("current_location") == "in_kg" and _day(p.get("in_kg_since")) and _day(p["in_kg_since"]) > today:
            raise QualificationError("future_actual_entry")
        if p.get("current_location") == "abroad" and any(_known(p.get(k)) for k in (
                "in_kg_since", "current_basis_in_kg", "current_basis_until", "registration_until", "current_visa_type")):
            raise QualificationError("location_basis_conflict")

        required = [k for k in QUESTIONS if k not in ("in_kg_since", "current_basis_in_kg",
                    "current_visa_type", "current_basis_until", "registration_until")]
        if p.get("current_location") == "in_kg":
            required += ["in_kg_since", "current_basis_in_kg", "current_basis_until", "registration_until"]
            if p.get("current_basis_in_kg") == "visa":
                required.append("current_visa_type")
        missing = sorted((k for k in required if not _known(_get(p, k))), key=lambda k: (QUESTIONS[k][0], list(QUESTIONS).index(k)))
        stops = []
        if _known(document) and document != "ordinary":
            stops.append("special_document_review")
        if p.get("purpose") in ("work_hire", "work_individual_employer", "entrepreneur"):
            stops.append("work_purpose_review")
        if _day(p.get("passport_expiry")) and _day(p["passport_expiry"]) < today:
            stops.append("passport_expired")
        if p.get("passport_pages_ok") is False:
            stops.append("passport_pages_review")
        for key, code in (("violations.overstay", "reported_overstay"), ("violations.deportation_or_ban", "reported_deportation_or_ban"),
                          ("previous_refusals_kg", "reported_refusal")):
            if _get(p, key) is True:
                stops.append(code)
        if p.get("current_location") == "in_kg":
            if p.get("current_basis_in_kg") == "none":
                stops.append("current_basis_missing")
            for field in ("current_basis_until", "registration_until"):
                if _day(p.get(field)) and _day(p[field]) < today:
                    stops.append(field + "_passed")
        if p.get("current_location") == "abroad" and start and start < today:
            stops.append("planned_entry_in_past")

        facts = deepcopy(request.get("condition_facts", {"schema_version": "kg-entry-condition-facts/1"}))
        facts.update(entry_passport_country=country if _known(country) else None,
                     document_type=document if _known(document) else None)
        condition_countries = [r.get("country") for r in facts.get("residence_documents", {}).get("items", [])]
        condition_countries.append(facts.get("tour_group", {}).get("all_members_country"))
        if any(_known(c) and c not in self._known for c in condition_countries):
            raise QualificationError("unknown_profile_country")
        condition_result = self._conditions.evaluate(facts) if self._conditions else None
        conditions = {r["unit_id"]: r for r in condition_result["rules"]} if condition_result else {}
        lookup = self._index.lookup(country, document_type=document or "unknown") if _known(country) else None
        candidates, registration, fallback = {}, [], []

        def reference(uid, association, condition=None):
            u = self._units[uid]
            return {"unit_id": uid, "kind": u["kind"], "association": association,
                    "profile_match": condition["status"] if condition else "not_evaluated",
                    "missing_facts": condition["missing_facts"] if condition else [],
                    "unresolved": condition["unresolved"] if condition else [],
                    "findings": review_findings(u), "source": {"page": u["page"], "section": u["section"], "source_ref": u["source_ref"]},
                    "may_quote": False}

        if lookup:
            for kind, rows in lookup["country_links"].items():
                for row in rows:
                    ref = reference(row["unit_id"], row["association"], conditions.get(row["unit_id"]))
                    if kind in REGIMES:
                        if ref["profile_match"] != "not_met":
                            candidates[row["unit_id"]] = ref
                    else:
                        registration.append(ref)
            fallback = [{"unit_id": r["unit_id"], "reason": "all_others_not_automatically_applicable"} for r in lookup["source_fallbacks"]]
            for row in lookup["country_independent"] + lookup["unmapped_country_rules"]:
                if row["kind"] in REGIMES and row["unit_id"] not in conditions:
                    candidates[row["unit_id"]] = reference(row["unit_id"], row["association"])
        for uid, row in conditions.items():
            if row["status"] != "not_met":
                candidates[uid] = reference(uid, "profile_condition", row)

        blockers = ["publication_not_approved", "eligibility_not_evaluated", "stay_calculation_required", "registration_review_required"]
        if not self._conditions:
            blockers.append("condition_catalog_missing")
        if len(candidates) > 1:
            blockers.append("multiple_candidates_require_review")
        if any("source_conflict" in r["findings"] for r in list(candidates.values()) + registration):
            blockers.append("source_conflict")
        if not candidates:
            blockers.append("no_candidate_resolved")
        questions = [{"path": "profile." + k, "step": QUESTIONS[k][0],
                      "text": QUESTIONS[k][1 if request["language"] == "ru" else 2]} for k in missing]
        condition_missing = sorted({f for r in candidates.values() for f in r["missing_facts"]
                                    if f not in ("entry_passport_country", "document_type")})
        return {"format": ALGORITHM, "mode": "review_only", "source": deepcopy(self._source),
                "request_hash": _hash(request), "as_of": request["as_of"],
                "status": "manager_review" if stops else "needs_input" if missing else "knowledge_review",
                "stop_reasons": stops, "missing_facts": [q["path"] for q in questions],
                "next_questions": [] if stops else questions[:3], "specialist_missing_facts": condition_missing,
                "candidate_rules": [candidates[k] for k in sorted(candidates)],
                "excluded_condition_rules": sorted(k for k, r in conditions.items() if r["status"] == "not_met"),
                "registration_rules": sorted(registration, key=lambda r: r["unit_id"]), "withheld_fallbacks": fallback,
                "blockers": blockers, "selected_regime": None, "visa_required": None,
                "exact_remaining_days": None, "exact_deadline": None, "publication_approved": False,
                "may_quote": False, "entry_eligibility_evaluated": False,
                "history": {"status": "not_attached"}, "calculations_performed": False}
