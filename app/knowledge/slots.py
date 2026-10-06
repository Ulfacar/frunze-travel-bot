"""Чистая проверка входной анкеты; сохранение и калькулятор реализуются отдельно."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

from .validation import InvalidDocument, Issue, Report, check_tree, schema_errors

_SCHEMA = json.loads((Path(__file__).parent / "schemas/kg-entry-slots-v1.json").read_text(encoding="utf-8"))
HANDOFF_REQUIRED = (
    "citizenship", "document_type", "current_location", "purpose", "entry_date", "exit_date",
    "client_type", "violations", "previous_refusals_kg", "family", "previous_visits", "inviting_party",
)


@dataclass(frozen=True)
class SlotContext:
    # Передаётся явно; никаких скрытых справочников или предположений об активной версии.
    countries: frozenset[str]
    today: date
    gcc_residence_countries: frozenset[str] | None = None
    longterm_visa_countries: frozenset[str] | None = None


@dataclass
class SlotReport(Report):
    prepared_slots: dict | None
    stop_factors: list[str]

    def summary(self) -> dict:
        # Даже успешный CLI не печатает контакт/анкету.
        return {**super().summary(), "stop_factors": self.stop_factors,
                "profile_only": True, "decision_calculated": False}


def slots_schema(profile: str = "collecting") -> dict:
    if profile not in {"collecting", "handoff"}:
        raise ValueError("Unknown slots profile")
    schema = deepcopy(_SCHEMA)
    if profile == "handoff":
        schema["required"] += list(HANDOFF_REQUIRED)
    return schema


def validate_slots(data, *, context: SlotContext, profile: str = "collecting") -> SlotReport:
    schema = slots_schema(profile)
    report = SlotReport([], [], None, [])
    try:
        check_tree(data)
    except InvalidDocument as exc:
        report.errors.append(exc.issue)
        return report
    report.errors += schema_errors(data, schema)
    if isinstance(data, dict):
        for field in ("decision", "stop_factors"):
            if field in data:
                report.errors.append(Issue("semantic.read_only", f"/{field}",
                                           "Computed fields are forbidden in input slots."))
    if report.errors:
        return report

    def error(code, path, message):
        report.errors.append(Issue(f"semantic.{code}", path, message))

    def known_date(value):
        return isinstance(value, str) and len(value) == 10 and value[4] == "-"

    def dates(start, end, path):
        if known_date(start) and known_date(end) and end < start:
            error("date_order", path, "End date precedes start date.")

    dates(data.get("entry_date"), data.get("exit_date"), "/exit_date")
    event = data.get("event_dates", {})
    dates(event.get("from"), event.get("to"), "/event_dates/to")
    citizenship = data.get("citizenship")
    passport = data.get("entry_passport_country")
    if isinstance(citizenship, list) and passport not in (None, "unknown", "not_applicable"):
        if passport not in citizenship:
            error("passport_citizenship", "/entry_passport_country", "Passport country must be a citizenship.")
    country_fields = [(f"/citizenship/{i}", v) for i, v in enumerate(citizenship or [])] if isinstance(citizenship, list) else []
    country_fields += [(f"/{key}", data.get(key)) for key in ("entry_passport_country", "residence_country")]
    visits = data.get("previous_visits", {})
    intervals = visits.get("intervals", [])
    for i, interval in enumerate(intervals):
        dates(interval["entry_date"], interval["exit_date"], f"/previous_visits/intervals/{i}/exit_date")
        country_fields.append((f"/previous_visits/intervals/{i}/passport_country", interval.get("passport_country")))
    if sum(i["exit_date"] == "open" for i in intervals) > 1:
        error("multiple_open_intervals", "/previous_visits/intervals", "Only one open interval is allowed.")
    for i, visa in enumerate(visits.get("previous_kg_visas", [])):
        dates(visa.get("valid_from"), visa.get("valid_to"), f"/previous_visits/previous_kg_visas/{i}/valid_to")
    for path, country in country_fields:
        if country not in (None, "unknown", "not_applicable") and country not in context.countries:
            error("unknown_country", path, "Country is absent from supplied registry.")
    if data.get("entry_point") == "other_land" and not data["entry_point_other"].strip():
        error("blank_entry_point", "/entry_point_other", "Border crossing name must not be blank.")
    expiry = data.get("passport_expiry")
    if known_date(expiry) and date.fromisoformat(expiry) < context.today:
        report.stop_factors.append("passport_expired")
    for field, allowed in (("gcc_or_brunei_residence", context.gcc_residence_countries),
                           ("longterm_us_uk_schengen_visa", context.longterm_visa_countries)):
        if field not in data or data[field] == "not_applicable":
            continue
        if allowed is None or not isinstance(citizenship, list):
            report.warnings.append(Issue("semantic.eligibility_unknown", f"/{field}",
                                         "Eligibility needs citizenship and versioned rule context."))
        elif not set(citizenship).intersection(allowed):
            report.warnings.append(Issue("semantic.eligibility_mismatch", f"/{field}",
                                         "Citizenship is outside supplied eligibility rule; value retained."))
    if report.ok:
        report.prepared_slots = deepcopy(data)
        report.prepared_slots.pop("contact", None)
    return report
