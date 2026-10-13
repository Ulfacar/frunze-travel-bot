"""Persist and verify draft review projections within their version transaction."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.domain.models import (DomainError, KnowledgeConditionLink, KnowledgeCountryLink,
                               KnowledgeProjection, KnowledgeSet)
from app.knowledge.conditions import ConditionReview
from app.knowledge.country_index import CountryRuleIndex
from app.knowledge.projection import build_projection
from app.knowledge.review import canonical


class ProjectionInvalid(DomainError):
    """Static diagnostics; no SQL or imported payload in errors."""


async def save_projection(session, version_id, projection):
    payload = projection["payload"]
    session.add(KnowledgeProjection(
        version_id=version_id, format_version=1, projection_hash=projection["projection_hash"],
        catalog_hash=projection["catalog_hash"], country_summary=payload["country"]["summary"],
        condition_catalog=payload["catalog"],
    ))
    await session.flush()
    session.add_all(KnowledgeCountryLink(version_id=version_id, **link) for link in payload["country"]["links"])
    session.add_all(KnowledgeConditionLink(version_id=version_id, unit_id=rule["unit_id"])
                    for rule in (payload["catalog"] or {}).get("rules", []))
    await session.flush()


async def verify_projection(session, version_id, expected):
    row = await session.get(KnowledgeProjection, version_id)
    if row is None:
        raise ProjectionInvalid("knowledge projection missing; explicit migration review required")
    links = (await session.scalars(select(KnowledgeCountryLink).where(
        KnowledgeCountryLink.version_id == version_id).order_by(
            KnowledgeCountryLink.country_iso3, KnowledgeCountryLink.unit_id))).all()
    conditions = (await session.scalars(select(KnowledgeConditionLink.unit_id).where(
        KnowledgeConditionLink.version_id == version_id).order_by(KnowledgeConditionLink.unit_id))).all()
    payload = expected["payload"]
    if (row.format_version != 1 or row.projection_hash != expected["projection_hash"] or
            row.catalog_hash != expected["catalog_hash"] or
            canonical(row.country_summary) != canonical(payload["country"]["summary"]) or
            canonical(row.condition_catalog) != canonical(payload["catalog"]) or
            [{"country_iso3": r.country_iso3, "unit_id": r.unit_id, "association": r.association}
             for r in links] != payload["country"]["links"] or
            list(conditions) != sorted(r["unit_id"] for r in (payload["catalog"] or {}).get("rules", []))):
        raise ProjectionInvalid("knowledge projection or catalog mismatch")


async def review_projection(engine, *, actor, set_id, version_id, country, document_type="ordinary", facts=None):
    """Read-only; validate stored bundle, materialization and catalog before returning."""
    from app.domain.knowledge_import import ImportUnavailable, _authorize, _sessions
    from app.domain.knowledge_review import _snapshot

    _authorize(actor)
    if any(type(value) is not int or value < 1 for value in (set_id, version_id)):
        raise DomainError("invalid knowledge projection identifier")
    try:
        async with _sessions(engine)() as session:
            target = await session.get(KnowledgeSet, set_id)
            if target is None or (target.code, target.jurisdiction, target.domain) != ("kg_entry", "KG", "entry"):
                raise DomainError("knowledge set unavailable for review")
            bundle, info = await _snapshot(session, set_id=set_id, version_id=version_id)
            row = await session.get(KnowledgeProjection, version_id)
            if row is None:
                raise ProjectionInvalid("knowledge projection missing; explicit migration review required")
            catalog = json.loads(canonical(row.condition_catalog))
            if facts is not None and catalog is None:
                raise ProjectionInvalid("condition catalog unavailable for profile review")
            expected = build_projection(bundle, catalog)
            await verify_projection(session, version_id, expected)
            args = (bundle["meta"], bundle["countries"], bundle["units"])
            source_hash = bundle["meta"]["source_hash"]
            lookup = CountryRuleIndex(*args, source_hash=source_hash).lookup(country, document_type=document_type)
            conditions = (ConditionReview(catalog, *args, source_hash=source_hash).evaluate(facts)
                          if facts is not None and catalog is not None else None)
            return {"set_id": set_id, "version": info, "projection_hash": expected["projection_hash"],
                    "catalog_hash": expected["catalog_hash"], "integrity_checked": True,
                    "catalog_status": "present" if catalog is not None else "absent",
                    "country": lookup, "conditions": conditions}
    except SQLAlchemyError:
        raise ImportUnavailable("knowledge projection storage unavailable") from None
    except DomainError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError):
        raise ProjectionInvalid("knowledge projection or review input invalid") from None
