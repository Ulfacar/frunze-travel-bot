"""Sprint 2: живые операции владения лидом поверх домена (обещанный WP3 row-lock).

Назначение/снятие выполняются под ``SELECT ... FOR UPDATE`` на строке Contact
(PostgreSQL сериализует конкурентные захваты одного контакта; на SQLite FOR UPDATE
— no-op, что для тестов достаточно: там гонок процессов нет). Сами инварианты
(одно активное назначение, история, ревизии) уже живут в ``reassign_manager`` —
здесь только блокировка и удобные обёртки для панели/автораспределения.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Assignment, Contact
from app.domain.services import AssignmentService, ContactService


def identity_for(channel: str, raw: str) -> tuple[str, str]:
    """Тип идентичности по каналу: WhatsApp несёт телефон, Telegram — numeric from.id.

    Telegram-id НЕЛЬЗЯ гнать через normalize_phone: 9-значный id молча превратился бы
    в выдуманный номер 996XXXXXXXXX (ложный/коллизионный Contact), остальные длины —
    в DomainError. Для telegram — отдельный тип идентичности без нормализации.
    """
    if (channel or "").strip().lower() == "telegram":
        return "telegram", (raw or "").strip()
    return "phone", raw


async def contact_for_phone(session: AsyncSession, raw_phone: str) -> Contact:
    """Контакт по телефону (find-or-create) — та же семантика, что у задач календаря."""
    return await ContactService.find_or_create_by_identity(session, "phone", raw_phone)


async def contact_for_channel(session: AsyncSession, *, channel: str,
                              raw: str) -> Contact:
    """Контакт по идентичности канала (find-or-create): phone либо telegram-id.

    Для WhatsApp разрешаем номер без ``+``: провайдер всегда отдаёт полный E.164
    (``905078174386@c.us``), и без этого иностранные клиенты отвергались как ambiguous —
    на проде 30.07 так потерялись 16 живых диалогов. Знание о формате принадлежит каналу,
    поэтому общее правило ``normalize_phone`` остаётся строгим.
    """
    identity_type, value = identity_for(channel, raw)
    is_whatsapp = (channel or "").strip().lower() in ("whatsapp", "wappi")
    return await ContactService.find_or_create_by_identity(
        session, identity_type, value, assume_e164=is_whatsapp)


async def lock_contact(session: AsyncSession, contact_id: int) -> None:
    """Row-lock контакта на время смены владения (PG: FOR UPDATE; SQLite: no-op)."""
    await session.execute(
        select(Contact.id).where(Contact.id == contact_id).with_for_update())


async def active_assignment(session: AsyncSession, contact_id: int,
                            direction: str) -> Assignment | None:
    return await AssignmentService.active_for(session, contact_id, direction)


async def assign_locked(session: AsyncSession, contact_id: int, direction: str,
                        manager_id: str, *, assigned_by: str, reason: str,
                        allow_emergency: bool = False) -> Assignment:
    """Назначить владельца под локом контакта (перечитав активное после лока)."""
    await lock_contact(session, contact_id)
    return await AssignmentService.assign(
        session, contact_id, direction, manager_id,
        assigned_by=assigned_by, reason=reason, allow_emergency=allow_emergency)


async def end_active(session: AsyncSession, contact_id: int, direction: str) -> bool:
    """Снять активное назначение (release: лид возвращается боту/в общий пул).

    История сохраняется (active=False + ended_at), как и при переназначении.
    """
    await lock_contact(session, contact_id)
    current = await AssignmentService.active_for(session, contact_id, direction)
    if current is None:
        return False
    current.active = False
    current.ended_at = datetime.now(timezone.utc)
    await session.flush()
    return True
