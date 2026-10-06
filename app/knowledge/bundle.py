"""Preflight в памяти: проверяет будущий импорт, но ничего не публикует/сохраняет."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from .bundle_schema import COUNTRIES_SCHEMA, ID_PATTERNS, META_SCHEMA, UNITS_SCHEMA, VALUE_SCHEMAS
from .validation import InvalidDocument, Issue, Report, check_tree, fail, load_document, schema_errors


def _alias(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def country_registry(data) -> tuple[dict[str, str], frozenset[str]]:
    errors = schema_errors(data, COUNTRIES_SCHEMA, "countries.yaml")
    if errors:
        raise InvalidDocument(errors[0])
    known = frozenset(data.values())
    aliases = {_alias(code): code for code in known}
    for alias, country in data.items():
        key = _alias(alias)
        if not key or (key in aliases and aliases[key] != country):
            fail("semantic.country_alias", "countries.yaml", "Blank or conflicting normalized country alias.")
        aliases[key] = country
    return aliases, known


@dataclass
class BundleReport(Report):
    bundle_hash: str | None = None
    status_counts: dict | None = None
    normalized_bundle: dict | None = None

    def summary(self) -> dict:
        return {**super().summary(), "mode": "preflight_only", "imported": False,
                "bundle_hash": self.bundle_hash, "status_counts": self.status_counts or {}}


def validate_bundle(meta, countries, units, *, source_hash: str) -> BundleReport:
    report = BundleReport([], [])
    try:
        check_tree({"meta": meta, "countries": countries, "units": units})
    except InvalidDocument as exc:
        report.errors.append(exc.issue)
        return report
    for data, schema, name in ((meta, META_SCHEMA, "meta.yaml"),
                               (countries, COUNTRIES_SCHEMA, "countries.yaml"),
                               (units, UNITS_SCHEMA, "units.yaml")):
        report.errors += schema_errors(data, schema, name)
    if report.errors:
        return report
    try:
        aliases, known = country_registry(countries)
    except InvalidDocument as exc:
        report.errors.append(exc.issue)
        return report
    if meta["source_hash"] != source_hash:
        report.errors.append(Issue("semantic.source_hash", "meta.yaml/source_hash", "Source SHA-256 mismatch."))
    units = deepcopy(units)
    ids = set()
    free_countries = set()
    free_owner = {}
    exemptions = set()
    not_in_list = set()

    def error(code, path, message):
        report.errors.append(Issue(f"semantic.{code}", path, message))

    def country(code, path):
        resolved = aliases.get(_alias(code))
        if resolved is None:
            error("unknown_country", path, "Country is absent from supplied registry.")
        return resolved

    for index, unit in enumerate(units):
        path = f"units.yaml/{index}"
        uid, kind, status, value = (unit[k] for k in ("unit_id", "kind", "confirmation_status", "value"))
        if uid in ids:
            error("duplicate_unit", path + "/unit_id", "Duplicate stable unit ID.")
        ids.add(uid)
        if not re.fullmatch(ID_PATTERNS[kind], uid):
            error("unit_id", path + "/unit_id", "Unit ID does not match kind.")
        if kind in {"registration_exemption", "registration_term"}:
            code = uid.rsplit(".", 1)[-1]
            if code not in known:
                error("unknown_country", path + "/unit_id", "Country suffix is absent from supplied registry.")
            if kind == "registration_exemption":
                exemptions.add(code)
        blocked = unit.get("blocked_value")
        conflict = unit.get("conflict_ref")
        if status in {"blocked", "decision_pending"}:
            if value is not None or not blocked or (status == "blocked" and not conflict):
                error("blocked_value", path, "Blocked/pending units need null value and preserved evidence; blocked needs conflict_ref.")
        elif value is None and not (status == "needs_verification" and blocked):
            error("missing_value", path + "/value", "Unknown value needs preserved evidence and unconfirmed status.")
        if status == "confirmed" and (blocked or conflict or unit["label"] in {"verify", "decision"}):
            error("confirmation_conflict", path, "Confirmed unit still carries unresolved evidence or label.")
        if (unit["label"] == "verify" and status not in {"needs_verification", "blocked"}) or (
                unit["label"] == "decision" and status not in {"decision_pending", "blocked"}):
            error("label_status", path + "/label", "Label and confirmation status conflict.")
        if bool(unit.get("verified_at")) != bool(unit.get("verified_by")):
            error("verification_pair", path, "Verification timestamp and author must be supplied together.")
        if unit.get("effective_from") and unit.get("effective_to") and unit["effective_to"] < unit["effective_from"]:
            error("date_order", path + "/effective_to", "Effective end precedes start.")
        if value is None:
            continue
        errors = schema_errors(value, VALUE_SCHEMAS[kind], path + "/value")
        report.errors += errors
        if errors:
            continue
        # Алиасы допустимы только в явных списках стран; на выходе — ISO3.
        lists = []
        if isinstance(value.get("countries"), list):
            lists.append((value, "countries"))
        if "not_in_list" in value:
            lists.append((value, "not_in_list"))
        if "countries" in value.get("applies_to", {}):
            lists.append((value["applies_to"], "countries"))
        for container, key in lists:
            resolved = [country(code, path + f"/value/{key}/{i}") for i, code in enumerate(container[key])]
            if None not in resolved:
                if len(set(resolved)) != len(resolved):
                    error("duplicate_country", path + f"/value/{key}", "Multiple aliases refer to the same country.")
                container[key] = sorted(resolved)
        if kind == "visa_free_regime":
            if value["days"] > value["window_days"]:
                error("window", path + "/value/days", "Stay limit exceeds rolling window.")
            for code in value["countries"]:
                free_countries.add(code)
                if code in free_owner:
                    error("regime_overlap", path + "/value/countries", "Country appears in multiple ordinary visa-free regimes.")
                free_owner[code] = uid
        elif kind == "registration_default":
            not_in_list.update(value["not_in_list"])
        elif kind == "rule_param":
            v, u = value["value"], value["unit"]
            valid = (type(v) is bool if u == "bool" else
                     isinstance(v, list) and all(isinstance(i, str) and i.strip() for i in v) if u == "list" else
                     type(v) is int and v >= 0)
            if not valid:
                error("parameter_type", path + "/value/value", "Parameter value does not match unit.")
        elif kind == "template":
            declared = set(value["placeholders"])
            found = set(re.findall(r"\{([a-z_][a-z0-9_]*)\}", value["text"]))
            rest = re.sub(r"\{[a-z_][a-z0-9_]*\}", "", value["text"])
            if declared != found or "{" in rest or "}" in rest or re.search(r"(?<!\w)\d", value["text"]):
                error("template_literals", path + "/value/text", "Use declared placeholders for variable numbers.")
    for code in sorted(free_countries - exemptions - not_in_list):
        error("registration_missing", "units.yaml", f"Missing explicit registration coverage for {code if code in known else 'unknown country'}.")
    if exemptions.intersection(not_in_list):
        error("registration_conflict", "units.yaml", "Country has both an exemption unit and not_in_list status.")
    report.status_counts = dict(sorted(Counter(u["confirmation_status"] for u in units).items()))
    report.warnings.append(Issue("preflight.not_approval", "", "Structure check only; source accuracy, completeness and publication are not approved."))
    if report.ok:
        normalized = {"meta": deepcopy(meta), "countries": dict(sorted(aliases.items())),
                      "units": sorted(units, key=lambda u: u["unit_id"])}
        encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        report.bundle_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        report.normalized_bundle = normalized
    return report


def preflight_bundle(directory: Path, source: Path) -> BundleReport:
    """Вычисляет хеш именно переданного исходника, не доверяя имени/URL из meta."""
    try:
        expected = {"meta.yaml", "countries.yaml", "units.yaml"}
        if {p.name for p in directory.iterdir()} != expected:
            fail("syntax.bundle_files", "bundle", "Bundle must contain exactly meta.yaml, countries.yaml and units.yaml.")
        if any((directory / n).is_symlink() or not (directory / n).is_file() for n in expected):
            fail("syntax.bundle_files", "bundle", "Bundle entries must be regular files.")
        meta = load_document(directory / "meta.yaml")
        countries = load_document(directory / "countries.yaml")
        units = load_document(directory / "units.yaml", reject_inline_comments=True)
        hasher = hashlib.sha256()
        size = 0
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                if size > 128 * 1024 * 1024:
                    fail("syntax.source_size", "source", "Source exceeds 128 MiB.")
                hasher.update(chunk)
        return validate_bundle(meta, countries, units, source_hash=hasher.hexdigest())
    except InvalidDocument as exc:
        return BundleReport([exc.issue], [])
    except OSError:
        return BundleReport([Issue("syntax.read", "bundle/source", "Cannot read bundle or source file.")], [])
