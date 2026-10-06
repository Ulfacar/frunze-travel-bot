"""E5-02B: импорт файлового пакета в неизменяемый draft.

Граница авторизации — trusted Actor от серверного auth, как у service_cases.
HTTP/бот/публикация не подключены. Сервис владеет сессиями: успешный снимок и
accepted journal коммитятся вместе; rejected journal — после rollback отдельно.
Не передавайте sessionmaker, привязанный к внешней Connection/транзакции.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.domain.models import (
    DomainError, KnowledgeImport, KnowledgeSet, KnowledgeUnit, KnowledgeVersion, _now,
)
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge.bundle import BundleReport, preflight_bundle
from app.knowledge.validation import Issue


class ImportUnavailable(DomainError):
    """БД/журнал недоступны: результат попытки не подтверждён, требуется сверка."""


@dataclass(frozen=True)
class ImportResult:
    accepted: bool
    import_id: int
    version_id: int | None
    bundle_hash: str | None
    reused: bool
    report: dict


def _authorize(actor: Actor):
    if (not isinstance(actor, Actor) or actor.is_full_admin is not True
            or not isinstance(actor.manager_id, str) or not actor.manager_id.strip()
            or len(actor.manager_id) > 64 or actor.manager_id.strip().lower() in {"system", "bot"}):
        raise PermissionDenied("knowledge import requires a named full administrator")


def _sessions(engine: AsyncEngine):
    if not isinstance(engine, AsyncEngine):
        raise TypeError("knowledge import requires its own AsyncEngine sessions")
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_kg_entry_set(engine: AsyncEngine, *, actor: Actor) -> int:
    """Явная регистрация набора; нет seed в миграции и нет придуманного review_period."""
    _authorize(actor)
    sessions = _sessions(engine)
    for attempt in range(3):
        try:
            async with sessions.begin() as session:
                found = await session.scalar(select(KnowledgeSet.id).where(KnowledgeSet.code == "kg_entry"))
                if found is not None:
                    return found
                row = KnowledgeSet(code="kg_entry", jurisdiction="KG", domain="entry", name="Въезд в Кыргызстан")
                session.add(row)
                await session.flush()
                return row.id
        except (IntegrityError, OperationalError):
            if attempt < 2:
                await asyncio.sleep(0.05 * (attempt + 1))
        except SQLAlchemyError:
            break
    raise ImportUnavailable("knowledge set registration unavailable") from None


def _summary(report: BundleReport, *, reused=False) -> dict:
    return {**report.summary(), "mode": "draft_import", "imported": report.ok, "reused": reused,
            "activated": False, "country_index_built": False}


def _journal(session, *, set_id, actor, started, report, version_id=None, reused=False):
    first = report.errors[0] if report.errors else None
    row = KnowledgeImport(
        set_id=set_id, bundle_hash=report.bundle_hash, filename="kg-entry-bundle/1",
        started_by=actor.manager_id, started_at=started, finished_at=max(started, _now()),
        result="rejected" if first else "accepted", version_id=version_id,
        error_stage=first.code.split(".", 1)[0] if first else None,
        error_location=first.location if first else None, error_message=first.message if first else None,
        report=_summary(report, reused=reused),
    )
    session.add(row)
    return row


def _unit(record, version_id):
    fields = dict(record)
    for key in ("effective_from", "effective_to"):
        if fields.get(key) is not None:
            fields[key] = date.fromisoformat(fields[key])
    for key in ("verified_at", "review_due_at"):
        if fields.get(key) is not None:
            fields[key] = datetime.fromisoformat(fields[key].upper().replace("Z", "+00:00"))
    return KnowledgeUnit(version_id=version_id, source_record=record, **fields)


async def import_bundle(engine: AsyncEngine, *, actor: Actor, set_id: int,
                        directory: Path, source: Path) -> ImportResult:
    """После return журнал закоммичен. ImportUnavailable = не обещаем наличие записи.

    Повтор возвращает только существующий draft с тем же normalized hash. Версия
    другого статуса не размножается и не переводится назад в draft. При потере связи
    на COMMIT исход неизвестен; повторный запрос сверяет hash и возвращает draft.
    """
    _authorize(actor)  # до чтения файлов, создания сессии и любой записи
    if type(set_id) is not int or set_id < 1:
        raise DomainError("invalid knowledge set")
    sessions = _sessions(engine)
    started = _now()
    # Возвращённый наружу BundleReport не принимается: проверяем файлы сами.
    report = preflight_bundle(Path(directory), Path(source))
    try:
        async with sessions() as session:
            target = await session.get(KnowledgeSet, set_id)
            if target is None:
                raise DomainError("unknown knowledge set")
            if (target.code, target.jurisdiction, target.domain) != ("kg_entry", "KG", "entry"):
                raise DomainError("bundle does not belong to this knowledge set")
    except SQLAlchemyError:
        raise ImportUnavailable("knowledge database unavailable") from None

    if report.ok:
        for attempt in range(3):
            committing = False
            try:
                async with sessions.begin() as session:
                    # PG сериализует номер/дедуп по набору; SQLite защищают UNIQUE и retry.
                    await session.execute(select(KnowledgeSet.id).where(KnowledgeSet.id == set_id).with_for_update())
                    existing = await session.scalar(select(KnowledgeVersion).where(
                        KnowledgeVersion.set_id == set_id, KnowledgeVersion.bundle_hash == report.bundle_hash))
                    if existing is not None and existing.status != "draft":
                        report.errors.append(Issue("semantic.existing_not_draft", "bundle",
                                                   "This bundle already belongs to a non-draft version."))
                        break
                    reused = existing is not None
                    if existing is None:
                        bundle = report.normalized_bundle
                        meta = bundle["meta"]
                        number = await session.scalar(select(func.max(KnowledgeVersion.version)).where(
                            KnowledgeVersion.set_id == set_id))
                        existing = KnowledgeVersion(
                            set_id=set_id, version=(number or 0) + 1, status="draft",
                            source_document=meta["source_document"], source_hash=meta["source_hash"],
                            bundle_hash=report.bundle_hash, source_prepared_by=meta["prepared_by"],
                            effective_from=date.fromisoformat(meta["effective_from"]) if meta.get("effective_from") else None,
                            created_by=actor.manager_id, bundle_meta=meta, country_aliases=bundle["countries"],
                            import_report=_summary(report),
                        )
                        session.add(existing)
                        await session.flush()
                        session.add_all(_unit(record, existing.id) for record in bundle["units"])
                        await session.flush()
                    journal = _journal(session, set_id=set_id, actor=actor, started=started,
                                       report=report, version_id=existing.id, reused=reused)
                    await session.flush()
                    result = ImportResult(True, journal.id, existing.id, report.bundle_hash, reused,
                                          _summary(report, reused=reused))
                    committing = True
                return result  # только после успешного COMMIT
            except (IntegrityError, OperationalError):
                if committing:
                    raise ImportUnavailable("knowledge commit outcome unknown; retry the same bundle to reconcile") from None
                if attempt < 2:
                    await asyncio.sleep(0.05 * (attempt + 1))
                    continue
            except Exception:
                if committing:
                    raise ImportUnavailable("knowledge commit outcome unknown; retry the same bundle to reconcile") from None
            report.errors.append(Issue("db.write", "database", "Draft transaction failed; retry after checking storage."))
            break

    try:
        async with sessions.begin() as session:
            journal = _journal(session, set_id=set_id, actor=actor, started=started, report=report)
            await session.flush()
            result = ImportResult(False, journal.id, None, report.bundle_hash, False, _summary(report))
        return result
    except SQLAlchemyError:
        # Не выдаём потерянный аудит за успешный отказ; не раскрываем SQL/DSN/параметры.
        raise ImportUnavailable("knowledge import journal unavailable; outcome requires reconciliation") from None
