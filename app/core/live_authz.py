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
# Два ОТДЕЛЬНЫХ тумблера по ответам заказчика 2.1 и 2.2 (05.11.2026), оба OFF.
# Раздельные намеренно: на проде нужно гасить по одному, а не всё разом.
TEAM_VIEW_FLAG = "manager_sees_direction_cases_enabled"
TAKE_COLLEAGUE_FLAG = "manager_can_take_colleague_dialog_enabled"

# Fallback на случай, когда бот не зарегистрирован в рантайме (например, TG-бот без
# токена в env): направление по известным id. Реестр ботов всегда в приоритете.
_FALLBACK_DIRECTIONS = {
    "frunze_tours": "tours", "frunze_tours_sezim": "tours", "frunze_tours_tg": "tours",
    "getvisa": "visa", "getvisa_tg": "visa",
}


async def enforcement_enabled() -> bool:
    from app.core.flags import get_flag
    return await get_flag(FLAG, settings.authz_enforce_enabled)


async def team_view_enabled() -> bool:
    """Ответ заказчика 2.1: менеджер видит всех клиентов своего направления."""
    from app.core.flags import get_flag
    return await get_flag(TEAM_VIEW_FLAG, settings.manager_sees_direction_cases_enabled)


async def take_colleague_enabled() -> bool:
    """Ответ заказчика 2.2: менеджер может забрать клиента коллеги себе."""
    from app.core.flags import get_flag
    return await get_flag(TAKE_COLLEAGUE_FLAG,
                          settings.manager_can_take_colleague_dialog_enabled)


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


async def actor_for_request(manager: dict | None, *, for_write: bool = False) -> Actor:
    """Актор запроса: права 2.1 и 2.2 читаются из рантайм-флагов ОДИН раз.

    `actor_for` остаётся синхронной и чистой — флаги в неё передаются параметрами.
    Иначе правило доступа зависело бы от базы, и его нельзя было бы проверить
    тестом без поднятой базы.

    `for_write=True` — актор для маршрута, который ЗАПИСЫВАЕТ: `team_view` в него не
    попадает. Ответ 2.1 дал менеджеру видимость направления, а не право правки, но
    часть маршрутов авторизуется `can_view_case` (`workday._case_or_404`), и с одним
    актором на всё флаг открыл бы запись в чужие дела — ревью 09.11.2026. Доменный
    слой защищён отдельно (`service_authz.can_change_case`): здесь второй контур,
    чтобы запрос не доходил до операции, а не единственный.
    """
    return actor_for(manager,
                     team_view=False if for_write else await team_view_enabled(),
                     can_take_colleague=await take_colleague_enabled())


def actor_for(manager: dict | None, *, team_view: bool = False,
              can_take_colleague: bool = False) -> Actor:
    """Actor для WP3-проверок из cookie-сессии менеджера панели."""
    scope = bot_scope_for(manager, admin_user=settings.admin_user,
                         strict=settings.crm_standalone_enabled)
    login = str((manager or {}).get("login") or "").strip().lower()
    if scope is None:                                     # полный админ
        return Actor(manager_id=login, is_full_admin=True)
    directions = frozenset(d for d in (direction_for_bot(b) for b in scope) if d)
    return Actor(manager_id=login, is_full_admin=False,
                 allowed_directions=directions, team_view=bool(team_view),
                 can_take_colleague=bool(can_take_colleague))
