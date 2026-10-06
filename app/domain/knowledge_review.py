"""E5-02C: read-only сравнение сохранённых версий одного набора.

Перед выдачей отчёта сверяем hash и проекции. Это контроль согласованности, не
подпись/юридическая верификация: privileged SQL может переписать и данные, и hash.
"""
from __future__ import annotations

from datetime import date, datetime
import json

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.knowledge_import import ImportUnavailable, _authorize, _sessions
from app.domain.models import DomainError, KnowledgeSet, KnowledgeUnit, KnowledgeVersion
from app.domain.permissions import Actor
from app.knowledge.bundle import validate_bundle
from app.knowledge.bundle_schema import UNIT_SCHEMA
from app.knowledge.review import canonical, compare_snapshots


class SnapshotInvalid(DomainError):
    """Повреждение снимка не раскрывает payload/SQL и не выглядит как нормальный diff."""


def _plain(value):
    # _ServiceJSON заморожен; deepcopy пытается вызвать запрещённые mutable методы.
    return json.loads(canonical(value))


def _matches(actual, expected, field):
    if field in {"effective_from", "effective_to"} and expected is not None:
        return actual == date.fromisoformat(expected)
    if field in {"verified_at", "review_due_at"} and expected is not None:
        expected = datetime.fromisoformat(expected.upper().replace("Z", "+00:00"))
        # SQLite DateTime не сохраняет offset, но сохраняет переданное wall time;
        # PostgreSQL timestamptz возвращает aware instant (может иметь другой offset).
        if actual is not None and actual.tzinfo is None:
            expected = expected.replace(tzinfo=None)
        return actual == expected
    return canonical(actual) == canonical(expected)


async def _snapshot(session, *, set_id, version_id):
    version = await session.scalar(select(KnowledgeVersion).where(
        KnowledgeVersion.id == version_id, KnowledgeVersion.set_id == set_id))
    if version is None:
        raise DomainError("knowledge version unavailable in this set")
    rows = (await session.scalars(select(KnowledgeUnit).where(
        KnowledgeUnit.version_id == version_id).order_by(KnowledgeUnit.unit_id).limit(5001))).all()
    try:
        meta, countries = _plain(version.bundle_meta), _plain(version.country_aliases)
        units = [_plain(row.source_record) for row in rows]
        checked = validate_bundle(meta, countries, units, source_hash=version.source_hash)
        if not checked.ok or checked.bundle_hash != version.bundle_hash:
            raise SnapshotInvalid("knowledge snapshot integrity check failed")
        for row, record in zip(rows, units):
            if any(not _matches(getattr(row, field), record.get(field), field)
                   for field in UNIT_SCHEMA["properties"]):
                raise SnapshotInvalid("knowledge unit projection integrity check failed")
        for column, key in (("source_document", "source_document"), ("source_hash", "source_hash"),
                            ("source_prepared_by", "prepared_by"), ("effective_from", "effective_from")):
            if not _matches(getattr(version, column), meta.get(key), key):
                raise SnapshotInvalid("knowledge version metadata integrity check failed")
    except (TypeError, ValueError, KeyError, AttributeError):
        raise SnapshotInvalid("knowledge snapshot integrity check failed") from None
    return checked.normalized_bundle, {"id": version.id, "number": version.version,
                                       "status": version.status, "bundle_hash": version.bundle_hash}


async def review_versions(engine: AsyncEngine, *, actor: Actor, set_id: int,
                          candidate_id: int, baseline_id: int | None = None) -> dict:
    """baseline_id=None выбирает active pointer один раз. Нет active — baseline=None.

    Результат содержит выбранные ID/hash, чтобы отчёт не обещал следовать за
    будущим переключением active. Ни commit, ни flush, ни SQL writes здесь нет.
    """
    _authorize(actor)
    if any(type(value) is not int or value < 1 for value in (set_id, candidate_id)) or (
            baseline_id is not None and (type(baseline_id) is not int or baseline_id < 1)):
        raise DomainError("invalid knowledge review identifier")
    try:
        async with _sessions(engine)() as session:
            target = await session.get(KnowledgeSet, set_id)
            if target is None or (target.code, target.jurisdiction, target.domain) != ("kg_entry", "KG", "entry"):
                raise DomainError("knowledge set unavailable for review")
            chosen_id = target.active_version_id if baseline_id is None else baseline_id
            candidate, candidate_info = await _snapshot(session, set_id=set_id, version_id=candidate_id)
            baseline, baseline_info = (None, None) if chosen_id is None else await _snapshot(
                session, set_id=set_id, version_id=chosen_id)
            if baseline_id is None and baseline_info is not None and baseline_info["status"] != "active":
                raise SnapshotInvalid("active knowledge pointer and status disagree")
            result = compare_snapshots(baseline, candidate)
            return {"set_id": set_id, "candidate": candidate_info, "baseline": baseline_info, **result}
    except SQLAlchemyError:
        raise ImportUnavailable("knowledge review storage unavailable") from None
    except DomainError:
        raise
    except (TypeError, ValueError):
        # Result processors can fail before _snapshot's validation (e.g. a raw
        # SQLite Date containing arbitrary text). Never return that text as an error.
        raise SnapshotInvalid("knowledge snapshot decoding failed") from None
