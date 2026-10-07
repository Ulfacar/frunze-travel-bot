"""Versioned deterministic materialization of review data, never eligibility."""
from __future__ import annotations

import hashlib
import json

from .conditions import ConditionReview
from .country_index import CountryRuleIndex
from .review import canonical


def build_projection(bundle, catalog=None):
    args = (bundle["meta"], bundle["countries"], bundle["units"])
    source_hash = bundle["meta"]["source_hash"]
    country = CountryRuleIndex(*args, source_hash=source_hash).projection()
    catalog_hash = None
    if catalog is not None:
        ConditionReview(catalog, *args, source_hash=source_hash)
        catalog_hash = hashlib.sha256(canonical(catalog).encode("utf-8")).hexdigest()
    payload = {"format": "kg-review-projection/1", "country": country, "catalog": catalog}
    return {"projection_hash": hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest(),
            "catalog_hash": catalog_hash, "payload": json.loads(canonical(payload))}
