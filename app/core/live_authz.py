"""Sprint 2: мост между сессией панели и чистыми WP3-правилами владения.

Собирает ``app.domain.permissions.Actor`` из cookie-сессии менеджера. Направления
команды выводятся из существующего бот-скоупа (``BOT_SCOPE_BY_MANAGER``) через
сценарии ботов (getvisa* → visa, frunze_tours* → tours) — новой оси конфигурации
не появляется. Сами правила (кто может писать/перехватывать) живут в
``app.domain.permissions`` и здесь не дублируются.
"""
from __future__ import annotations

from app.config import settings
from app.core.manager_scope import bot_scope_for
from app.domain.permissions import Actor

FLAG = "authz_enforce_enabled"

# Fallback на случай, когда бот не зарегистрирован в рантайме (например, TG-бот без
# токена в env): направление по известным id. Реестр ботов всегда в приоритете.
_FALLBACK_DIRECTIONS = {
    "frunze_tours": "tours", "frunze_tours_sezim": "tours", "frunze_tours_tg": "tours",
    "getvisa": "visa", "getvisa_tg": "visa",
}


async def enforcement_enabled() -> bool:
    from app.core.flags import get_flag
    return await get_flag(FLAG, settings.authz_enforce_enabled)


def direction_for_bot(bot_id: str) -> str:
    """Направление (сценарий воронки) бота: из реестра, иначе по известным id."""
    try:
        from app.core.bots import registry
        bot = registry.by_id(bot_id)
        if bot is not None and getattr(bot, "scenario", ""):
            return bot.scenario
    except Exception:  # noqa: BLE001 — реестр может быть не инициализирован в тестах
        pass
    return _FALLBACK_DIRECTIONS.get(bot_id or "", "")


def actor_for(manager: dict | None) -> Actor:
    """Actor для WP3-проверок из cookie-сессии менеджера панели."""
    scope = bot_scope_for(manager, admin_user=settings.admin_user)
    login = str((manager or {}).get("login") or "").strip().lower()
    if scope is None:                                     # полный админ
        return Actor(manager_id=login, is_full_admin=True)
    directions = frozenset(d for d in (direction_for_bot(b) for b in scope) if d)
    return Actor(manager_id=login, is_full_admin=False, allowed_directions=directions)
