"""Shared manager → bot-scope resolution.

Single source of truth for which bot ids a manager may see. Lives in core so both
the admin panel (`app/admin/router.py`) and scheduler jobs (`calendar_brief`) reuse
the same logic without importing the admin router. `None` means unrestricted (admin).
"""
from __future__ import annotations

BOT_SCOPE_BY_MANAGER: dict[str, set[str]] = {
    "ademi": {"frunze_tours", "frunze_tours_tg"},
    "адеми": {"frunze_tours", "frunze_tours_tg"},
    # Сезим уволилась 07.2026; её WhatsApp-номер (frunze_tours_sezim) ведёт Айсина.
    # Логин sezim оставлен в карте, чтобы старые записи владения не потеряли смысл.
    "sezim": {"frunze_tours_sezim"},
    "сезим": {"frunze_tours_sezim"},
    "aisina": {"frunze_tours_sezim", "frunze_tours_tg"},
    "айсина": {"frunze_tours_sezim", "frunze_tours_tg"},
    "medina": {"getvisa", "getvisa_tg"},
    "медина": {"getvisa", "getvisa_tg"},
    "eliza": {"getvisa", "getvisa_tg"},
    "элиза": {"getvisa", "getvisa_tg"},
    "getvisa": {"getvisa", "getvisa_tg"},
}


def bot_scope_for(manager: dict | None, *, admin_user: str = "") -> set[str] | None:
    """Return the set of bot ids visible to this manager; None = unrestricted admin."""
    if not manager:
        return set()
    if manager.get("admin"):
        return None
    login = str(manager.get("login") or "").strip().lower()
    name = str(manager.get("name") or "").strip().lower()
    admin_login = str(admin_user or "").strip().lower()
    if login in {"admin", "administrator", admin_login} or "админ" in name:
        return None
    return BOT_SCOPE_BY_MANAGER.get(login) or BOT_SCOPE_BY_MANAGER.get(name) or set()


def conversation_in_scope(bot_id: str, user_id: str, scope: set[str] | None) -> bool:
    """Whether a conversation (bot_id / user_id 'bot:phone') is inside a bot scope."""
    if scope is None:
        return True
    if not scope:
        return False
    return (bot_id or "") in scope or any(
        (user_id or "").startswith(f"{allowed}:") for allowed in scope)
