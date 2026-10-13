"""Read a pinned KG qualification in a checked service-case context; no writes."""
from sqlalchemy import select

from app.domain.entry_storage import EntryStorageInvalid, _authorize, _history, _id, _transaction
from app.domain.models import KnowledgeVersion, Product, ServiceCase
from app.domain.qualification_storage import _latest, _read, _report


async def read_qualification_card(engine, *, actor, case_id, qualification_id):
    # A card URL is not an authorization capability, including for scoped managers.
    _authorize(actor)
    _id(case_id)
    _id(qualification_id)

    async def read(session):
        pair = (await session.execute(select(ServiceCase, Product).join(
            Product, ServiceCase.product_id == Product.id).where(
                ServiceCase.id == case_id, Product.direction == "visa"))).first()
        if pair is None:
            raise EntryStorageInvalid("qualification_card_unavailable")
        case, product = pair
        row, *_ = await _read(session, case.contact_id, qualification_id)
        latest = await _latest(session, case.contact_id)
        version = await session.get(KnowledgeVersion, row.knowledge_version_id)
        history = None
        if row.history_id is not None:
            history_row, history_document, _ = await _history(session, case.contact_id, row.history_id)
            history = {'history_id': history_row.id, 'revision': history_row.revision, 'document': history_document}
        return {
            "case": {"id": case.id, "contact_id": case.contact_id, "title": product.name,
                     "owner_login": case.owner_login},
            "saved": _report(row),
            "latest_id": latest.id,
            "is_latest": latest.id == row.id,
            "countries": dict(version.country_aliases),
            "stay_history": history,
        }

    return await _transaction(engine, read)
