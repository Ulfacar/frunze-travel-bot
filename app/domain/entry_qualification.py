"""Admin read-only qualification over pinned, integrity-checked DB sources."""
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.domain.entry_calculations import _bundle
from app.domain.entry_storage import (EntryStorageInvalid, EntryStorageUnavailable, _authorize,
                                      _history, _id, _plain)
from app.domain.knowledge_import import _sessions
from app.domain.knowledge_projection import ProjectionInvalid, verify_projection
from app.domain.models import Contact, DomainError, KnowledgeProjection
from app.knowledge.projection import build_projection
from app.knowledge.qualification import QualificationReview


async def _qualification_sources(session, contact_id, knowledge_version_id, history_id):
    """Load pinned sources in the caller's transaction, without evaluating a request."""
    if await session.scalar(select(Contact.id).where(Contact.id == contact_id)) is None:
        raise EntryStorageInvalid("contact_unavailable")
    bundle = await _bundle(session, knowledge_version_id)
    projection = await session.get(KnowledgeProjection, knowledge_version_id)
    if projection is None:
        raise ProjectionInvalid("knowledge_projection_missing")
    catalog = _plain(projection.condition_catalog)
    expected = build_projection(bundle, catalog)
    await verify_projection(session, knowledge_version_id, expected)
    review = QualificationReview(**bundle, source_hash=bundle["meta"]["source_hash"], catalog=catalog)
    context = {"contact_id": contact_id, "knowledge_version_id": knowledge_version_id,
               "projection_hash": expected["projection_hash"], "history": {"status": "not_attached"},
               "blockers": []}
    if history_id is not None:
        row, doc, intervals = await _history(session, contact_id, history_id)
        context["history"] = {"status": "integrity_checked", "history_id": row.id, "revision": row.revision,
            "snapshot_hash": row.snapshot_hash, "as_of": doc["as_of"], "history_complete": doc["history_complete"],
            "interval_count": len(intervals), "unconfirmed_count": sum(not r.confirmed for r in intervals),
            "passport_continuity": "not_evaluated"}
        if doc["history_complete"] is not True:
            context["blockers"].append("history_incomplete")
        if any(not r.confirmed for r in intervals):
            context["blockers"].append("history_unconfirmed")
    else:
        context["blockers"].append("history_not_attached")
    return review, context


def _evaluate_qualification(review, context, request):
    report = review.evaluate(request)
    report["source"].update({key: context[key] for key in ("knowledge_version_id", "projection_hash")})
    report["contact_id"] = context["contact_id"]
    report["history"] = _plain(context["history"])
    report["blockers"].extend(context["blockers"])
    if context["history"].get("as_of", report["as_of"]) != report["as_of"]:
        report["blockers"].append("history_cutoff_differs")
    return report


async def review_qualification(engine, *, actor, contact_id, knowledge_version_id, request, history_id=None):
    """Does not save facts, claim scoped manager access, calculate or publish rules."""
    _authorize(actor)
    _id(contact_id)
    _id(knowledge_version_id)
    if history_id is not None:
        _id(history_id)
    try:
        async with _sessions(engine)() as session:
            review, context = await _qualification_sources(session, contact_id, knowledge_version_id, history_id)
            return _evaluate_qualification(review, context, request)
    except DomainError:
        raise
    except SQLAlchemyError:
        raise EntryStorageUnavailable("qualification_storage_unavailable") from None
    except (TypeError, ValueError, KeyError, AttributeError):
        raise EntryStorageInvalid("qualification_data_invalid") from None
