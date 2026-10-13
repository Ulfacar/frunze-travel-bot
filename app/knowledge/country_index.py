"""Индекс ссылок для проверки страны. Не выбирает применимый режим или право въезда.

Сборка валидирует bundle и сохраняет собственный снимок. Запрос обращается к готовым
спискам ссылок, не ищет страну в JSON каждой единицы. Публикация всегда запрещена.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from types import MappingProxyType

from .bundle import _alias, country_registry, validate_bundle
from .review import review_findings

COUNTRY_KINDS = (
    "visa_free_regime", "visa_required_regime", "special_regime",
    "registration_exemption", "registration_default", "registration_term",
)
DOCUMENT_TYPES = frozenset((
    "ordinary", "diplomatic", "service", "un_lp", "stateless", "refugee", "other",
    "id_card", "internal", "unrecognized", "unknown",
))


class CountryIndexError(ValueError):
    """Код ошибки не содержит исходный ввод/персональные данные."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class CountryRuleIndex:
    def __init__(self, meta, countries, units, *, source_hash: str):
        report = validate_bundle(meta, countries, units, source_hash=source_hash)
        if not report.ok:
            raise CountryIndexError("invalid_bundle")
        snapshot = report.normalized_bundle
        aliases, known = country_registry(snapshot["countries"])
        self._aliases = MappingProxyType(aliases)
        self._meta = deepcopy(snapshot["meta"])
        self._bundle_hash = report.bundle_hash
        self._units = {u["unit_id"]: u for u in snapshot["units"] if u["kind"] in COUNTRY_KINDS}
        self._ignored_count = len(snapshot["units"]) - len(self._units)
        links = {code: [] for code in sorted(known)}
        fallback, independent, unmapped = [], [], []

        def resolve_codes(codes):
            # Evidence-only hints имеют открытый формат в bundle: проверяем отдельно.
            if not isinstance(codes, list) or not codes:
                raise CountryIndexError("invalid_evidence_country")
            resolved = []
            for code in codes:
                if not isinstance(code, str) or len(code) > 200 or _alias(code) not in aliases:
                    raise CountryIndexError("invalid_evidence_country")
                resolved.append(aliases[_alias(code)])
            if len(set(resolved)) != len(resolved):
                raise CountryIndexError("duplicate_evidence_country")
            return sorted(resolved)

        def add(codes, uid, basis):
            for code in resolve_codes(codes):
                links[code].append((uid, basis))

        for uid, unit in self._units.items():
            kind, value = unit["kind"], unit["value"]
            if kind in ("registration_exemption", "registration_term"):
                add([uid.rsplit(".", 1)[1]], uid, "unit_id_country")
            elif value is None:
                # Не угадываем по тексту или суффиксу VF ID и не оживляем candidate.value.
                evidence = unit.get("blocked_value") or {}
                hint = evidence.get("country_iso3")
                candidate = evidence.get("candidate")
                if hint is not None:
                    if (isinstance(candidate, dict) and "countries" in candidate and
                            resolve_codes([hint]) != resolve_codes(candidate["countries"])):
                        raise CountryIndexError("conflicting_evidence_countries")
                    add([hint], uid, "evidence_country")
                elif isinstance(candidate, dict) and "countries" in candidate:
                    add(candidate["countries"], uid, "evidence_country")
                else:
                    unmapped.append(uid)
            elif kind == "registration_default":
                if value["not_in_list"]:
                    add(value["not_in_list"], uid, "explicit_not_in_list")
                else:
                    unmapped.append(uid)
            elif kind == "special_regime":
                applies = value["applies_to"]
                if "countries" in applies:
                    add(applies["countries"], uid, "value_country")
                else:
                    independent.append(uid)
            elif value["countries"] == "all_others":
                fallback.append(uid)
            else:
                add(value["countries"], uid, "value_country")

        self._links = MappingProxyType({code: tuple(sorted(rows)) for code, rows in links.items()})
        self._fallback = tuple(sorted(fallback))
        self._independent = tuple(sorted(independent))
        self._unmapped = tuple(sorted(unmapped))

    def _header(self):
        return {
            "format": "kg-country-review/1", "mode": "review_only",
            "version_label": self._meta["version_label"], "bundle_hash": self._bundle_hash,
            "source_document": self._meta["source_document"], "source_hash": self._meta["source_hash"],
            "publication_approved": False, "may_quote": False,
            "applicability_evaluated": False, "selected_regime": None,
        }

    def _reference(self, uid, basis):
        unit = self._units[uid]
        fields = ("unit_id", "kind", "title", "section", "page", "source_ref", "label",
                  "confirmation_status", "value", "conflict_ref", "effective_from", "effective_to",
                  "verified_at", "review_due_at")
        return {**deepcopy({key: unit.get(key) for key in fields}),
                "association": basis, "evidence_only": basis == "evidence_country",
                "findings": review_findings(unit), "may_quote": False}

    def lookup(self, country: str, *, document_type: str = "ordinary") -> dict:
        if not isinstance(country, str) or not country.strip() or len(country) > 200:
            raise CountryIndexError("invalid_country_query")
        try:
            country.encode("utf-8")
        except UnicodeEncodeError:
            raise CountryIndexError("invalid_country_query") from None
        if not isinstance(document_type, str) or document_type not in DOCUMENT_TYPES:
            raise CountryIndexError("invalid_document_type")
        code = self._aliases.get(_alias(country))
        result = {**self._header(), "status": "found" if code else "unknown_country",
                  "country_iso3": code, "document_type": document_type,
                  "country_links": {kind: [] for kind in COUNTRY_KINDS},
                  "source_fallbacks": [], "country_independent": [], "unmapped_country_rules": [],
                  "findings": []}
        if code is None:
            result["findings"] = ["unknown_country"]
            return result
        for uid, basis in self._links[code]:
            result["country_links"][self._units[uid]["kind"]].append(self._reference(uid, basis))
        result["source_fallbacks"] = [self._reference(uid, "source_all_others") for uid in self._fallback]
        result["country_independent"] = [self._reference(uid, "no_country_filter") for uid in self._independent]
        result["unmapped_country_rules"] = [self._reference(uid, "unmapped") for uid in self._unmapped]
        findings = ["applicability_not_evaluated", "publication_not_evaluated"]
        if document_type != "ordinary":
            findings.append("document_review_required")
        if not self._links[code]:
            findings.append("no_explicit_country_links")
        if not any(self._units[uid]["kind"].startswith("registration_") and
                   self._units[uid]["kind"] != "registration_term" for uid, _ in self._links[code]):
            findings.append("registration_coverage_missing")
        if self._unmapped:
            findings.append("unmapped_country_rules_present")
        result["findings"] = findings
        return result

    def projection(self) -> dict:
        """Owned deterministic persistence payload; format /1 must stay reproducible."""
        return {"format": "kg-country-projection/1", "summary": self.summary(),
                "links": [{"country_iso3": code, "unit_id": uid, "association": basis}
                          for code, rows in sorted(self._links.items()) for uid, basis in rows]}

    def summary(self) -> dict:
        return {**self._header(), "countries": len(self._links), "aliases": len(self._aliases),
                "country_units": len(self._units), "other_units": self._ignored_count,
                "linked_countries": sum(bool(rows) for rows in self._links.values()),
                "country_links": sum(len(rows) for rows in self._links.values()),
                "evidence_only_links": sum(basis == "evidence_country" for rows in self._links.values() for _, basis in rows),
                "source_fallback_ids": list(self._fallback), "country_independent_ids": list(self._independent),
                "unmapped_unit_ids": list(self._unmapped),
                "by_kind": dict(sorted(Counter(u["kind"] for u in self._units.values()).items())),
                "by_status": dict(sorted(Counter(u["confirmation_status"] for u in self._units.values()).items()))}
