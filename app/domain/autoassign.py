"""Sprint 2: авто-назначение нового ВИЗОВОГО лида по round-robin (за флагом).

* Флаг ``visa_autoassign_enabled`` (default OFF) → функция no-op.
* Только направление visa: туры разбираются вручную, кросс-команд нет.
* Идемпотентно на каждый inbound: активное назначение уже есть → no-op, поэтому
  срабатывает фактически один раз — на первом сообщении нового клиента.
* Выбор — детерминированный least-recently-assigned (``assignment_queue``);
  назначение — под row-lock контакта (``live_assign``) от имени ``system``.
* Назначение НЕ перехватывает бота: бот продолжает отвечать, менеджер лишь
  становится владельцем (панель показывает «Ведёт: …», бриф роутит лида ему).
* Fail-safe: собственная сессия, все ошибки гасятся — живой диалог не страдает.
* PII: телефон/имя клиента и chat_id менеджера не логируются.
"""
from __future__ import annotations

import logging

from app.config import settings

log = logging.getLogger("domain.autoassign")

FLAG = "visa_autoassign_enabled"
VISA_DIRECTION = "visa"

TOURS_PILOT_FLAG = "tours_pilot_assign_enabled"
TOURS_DIRECTION = "tours"


async def _mirror_panel(user_id: str, login: str) -> None:
    """Отразить владельца в панельном assigned_to (только если тот пуст)."""
    from app.integrations.panel.store import get_conversation_store
    store = get_conversation_store()
    conv = await store.get(user_id)
    if conv is not None and not (conv.assigned_to or ""):
        await store.update_meta(user_id, assigned_to=login)


async def _notify_manager(login: str, user_id: str) -> None:
    """Личный TG-пуш «вам назначен лид» — только при настроенном telegram_chat_id."""
    from app.core.calendar_brief import _client_link, _push_telegram, _token
    token = _token()
    if not token:
        return
    for mgr in settings.manager_list():
        if (mgr.login or "").strip().lower() != login:
            continue
        chat_id = (getattr(mgr, "telegram_chat_id", "") or "").strip()
        if chat_id:
            text = ("🆕 Вам назначен новый лид (визы).\n"
                    f"{_client_link(user_id, settings.admin_base_url)}")
            await _push_telegram(token, chat_id, text)
        return


async def maybe_autoassign(*, phone: str, direction: str, user_id: str,
                           channel: str = "", sessionmaker=None) -> str | None:
    """Назначить нового визового клиента следующему менеджеру. Никогда не raises.

    ``channel`` определяет тип идентичности контакта: WhatsApp несёт телефон,
    Telegram — numeric id (его нельзя нормализовать как номер). Возвращает login
    назначенного менеджера или None (no-op/ошибка).
    """
    from app.core.flags import get_flag
    if (direction or "") != VISA_DIRECTION:
        return None
    if not await get_flag(FLAG, settings.visa_autoassign_enabled):
        return None
    try:
        sm = sessionmaker
        if sm is None:
            from app.integrations.crm.db import get_sessionmaker
            sm = get_sessionmaker()
        from app.domain import live_assign
        from app.domain.assignment_queue import select_next_visa_manager
        async with sm() as session:
            contact = await live_assign.contact_for_channel(
                session, channel=channel, raw=phone)
            # Лок ДО выбора: конкурентные inbound одного клиента сериализуются,
            # второй после лока видит назначение первого и выходит.
            await live_assign.lock_contact(session, contact.id)
            if await live_assign.active_assignment(session, contact.id, VISA_DIRECTION):
                await session.commit()          # контакт мог быть создан выше
                return None
            login = await select_next_visa_manager(session)
            if not login:
                await session.commit()
                log.info("visa autoassign: no manager available")
                return None
            await live_assign.assign_locked(
                session, contact.id, VISA_DIRECTION, login,
                assigned_by="system", reason="round_robin")
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — fail-safe: живой диалог важнее
        log.warning("visa autoassign failed (err=%s)", type(exc).__name__)
        return None
    # Побочные эффекты вне транзакции; сами fail-safe.
    try:
        await _mirror_panel(user_id, login)
    except Exception:  # noqa: BLE001
        log.warning("visa autoassign: panel mirror failed", exc_info=True)
    try:
        await _notify_manager(login, user_id)
    except Exception:  # noqa: BLE001
        log.warning("visa autoassign: notify failed (manager=%s)", login)
    log.info("visa autoassign: assigned manager=%s", login)
    return login


async def _audit_assign(login: str, user_id: str, reason: str) -> None:
    """Audit-запись о назначении (не роняет поток при сбое панели)."""
    try:
        from app.integrations.panel.store import get_conversation_store
        await get_conversation_store().add_audit(
            "system", "assign", user_id, f"{reason} → {login}")
    except Exception:  # noqa: BLE001
        log.warning("tours pilot: audit write failed (manager=%s)", login)


def tours_owner_for(bot_id: str) -> str:
    """Кому закреплять новый туровый лид этого канала. Пусто — канал не обслуживаем.

    Карта `tours_owner_by_bot` (bot_id → логин) описывает оба туровых номера сразу и имеет
    приоритет. Если она пуста, работает прежняя одноканальная пара
    `tours_pilot_bot_id`/`tours_pilot_manager` — так пилот не ломается на старых стендах.
    """
    mapping = {str(k).strip(): str(v or "").strip().lower()
               for k, v in (settings.tours_owner_by_bot or {}).items()}
    key = (bot_id or "").strip()
    if mapping:
        return mapping.get(key, "")
    if key != settings.tours_pilot_bot_id:
        return ""
    pilot = (settings.tours_pilot_manager or "").strip().lower()
    if not pilot:
        log.info("tours pilot: no pilot manager configured")
    return pilot


async def maybe_assign_tours_pilot(*, phone: str, direction: str, bot_id: str,
                                   user_id: str, channel: str = "",
                                   sessionmaker=None) -> str | None:
    """Пилот: назначить новый ТУРОВЫЙ лид единственному менеджеру (Адеми). Не raises.

    Закрывает owner-gap Morning Brief. Строго: флаг ON, direction=tours,
    bot_id=tours_pilot_bot_id, у контакта НЕТ активного tours-owner. Существующего
    владельца НЕ перезаписывает. Идемпотентно (row-lock + проверка активного).
    Владелец — settings.tours_pilot_manager (не хардкод). Пишет Assignment + audit;
    зеркалит в панель (для брифа). Флаг OFF → новые лиды не назначаются.
    """
    from app.core.flags import get_flag
    if (direction or "") != TOURS_DIRECTION:
        return None
    pilot = tours_owner_for(bot_id)
    if not pilot:
        return None
    if not await get_flag(TOURS_PILOT_FLAG, settings.tours_pilot_assign_enabled):
        return None
    try:
        sm = sessionmaker
        if sm is None:
            from app.integrations.crm.db import get_sessionmaker
            sm = get_sessionmaker()
        from app.domain import live_assign
        async with sm() as session:
            contact = await live_assign.contact_for_channel(
                session, channel=channel, raw=phone)
            await live_assign.lock_contact(session, contact.id)
            # Существующий owner НИКОГДА не перезаписываем (идемпотентность + защита).
            if await live_assign.active_assignment(session, contact.id, TOURS_DIRECTION):
                await session.commit()
                return None
            await live_assign.assign_locked(
                session, contact.id, TOURS_DIRECTION, pilot,
                assigned_by="system", reason="tours_pilot")
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — fail-safe
        log.warning("tours pilot assign failed (err=%s)", type(exc).__name__)
        return None
    try:
        await _mirror_panel(user_id, pilot)
    except Exception:  # noqa: BLE001
        log.warning("tours pilot: panel mirror failed", exc_info=True)
    await _audit_assign(pilot, user_id, "tours_pilot")
    log.info("tours pilot: assigned manager=%s", pilot)
    return pilot
