"""WP3 assigned-manager authorization — PURE functions, no wiring.

Ownership + team rules (mirrors ``reassign_manager`` and the admin roles):

* SEND is allowed ONLY to the active assigned owner whose assignment is in the
  requested direction. ``is_full_admin`` does NOT grant send — an admin must first
  reassign the contact to themselves (become the active owner) before sending.
* VIEW and REASSIGN are available to a full-admin through the admin flow, and to a
  manager who has access to the requested direction.
* A peer may NOT take over an owned contact; re-affirming the same manager is
  allowed; replacing a DIFFERENT active owner is an emergency reassignment,
  permitted ONLY to a full-admin.
* Direction / cross-team: a visa manager gets no rights on a tours contact and
  vice-versa. Access to a direction comes from ``Actor.allowed_directions`` (or
  full-admin for view/reassign), and the assignment's ``direction`` must match the
  requested one.

FOUNDATION service: NOT imported by the live admin/takeover endpoints — production
panel behaviour is unchanged. ``assignment`` is duck-typed (``active``,
``manager_id``, ``direction``) or ``None`` when there is no active assignment.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Actor:
    manager_id: str
    is_full_admin: bool = False
    # Directions (teams) this manager may act in, e.g. frozenset({"visa"}).
    allowed_directions: frozenset[str] = field(default_factory=frozenset)
    # Оператор въездной CRM по PDF (визовый менеджер при включённом
    # `kg_entry_manager_access_enabled`). Даёт право РАБОТАТЬ по делу (анкеты, заявки,
    # документы, сроки), но не администрировать знания: публикация, решения по
    # единицам, импорт — только `is_full_admin`. Выставляется ТОЛЬКО шлюзом
    # `app/admin/kg_entry._gate`, никогда из cookie напрямую.
    kg_entry_operator: bool = False
    # Ответ заказчика 2.1 от 05.11.2026: менеджер видит всех клиентов своего
    # направления, а не только своих. Флаг `manager_sees_direction_cases_enabled`,
    # дефолт OFF. Выставляется ТОЛЬКО там, где строится актор запроса
    # (`live_authz.actor_for`), никогда из cookie напрямую.
    team_view: bool = False
    # Ответ заказчика 2.2: менеджер может забрать клиента коллеги ВНУТРИ своего
    # направления — включая живую переписку. Между направлениями запрет остаётся.
    # Флаг `manager_can_take_colleague_dialog_enabled`, дефолт OFF. Отменяет прежнее
    # правило «перехват чужого запрещён» (CLAUDE.md §7) в границах направления.
    can_take_colleague: bool = False


def _has_direction_access(actor: Actor, requested_direction: str | None) -> bool:
    """Whether the actor's team scope covers the requested direction."""
    if requested_direction is None:
        return True
    if actor.is_full_admin:
        return True
    return requested_direction in actor.allowed_directions


def _is_active_owner(actor: Actor, assignment, requested_direction: str | None) -> bool:
    """Active assignment on this manager AND (if given) matching direction."""
    if assignment is None or not getattr(assignment, "active", False):
        return False
    if getattr(assignment, "manager_id", None) != actor.manager_id:
        return False
    if (requested_direction is not None
            and getattr(assignment, "direction", None) != requested_direction):
        return False
    return True


def can_view(actor: Actor, assignment, requested_direction: str | None = None) -> bool:
    """Full-admin may view via the admin flow; otherwise the active owner in a
    direction the manager has access to."""
    if actor.is_full_admin:
        return True
    return (_has_direction_access(actor, requested_direction)
            and _is_active_owner(actor, assignment, requested_direction))


def can_send(actor: Actor, assignment, requested_direction: str | None = None) -> bool:
    """SEND only for the active assigned owner in the requested direction. A
    full-admin does NOT get automatic send — they must own the contact first."""
    return (_has_direction_access(actor, requested_direction)
            and _is_active_owner(actor, assignment, requested_direction))


def can_emergency_reassign(actor: Actor) -> bool:
    """Emergency takeover of a different active owner is a full-admin power only."""
    return actor.is_full_admin


def can_reassign(actor: Actor, assignment, target_manager_id: str,
                 requested_direction: str | None = None) -> bool:
    """Whether ``actor`` may (re)assign the contact to ``target_manager_id``.

    * full-admin → allowed (admin flow), across teams;
    * otherwise the actor needs access to the requested direction, and:
        - no active assignment → allowed (a first assignment / claim);
        - assignment already on ``target_manager_id`` → allowed (re-affirm);
        - taking over a DIFFERENT active owner → emergency, full-admin only, UNLESS
          ``actor.can_take_colleague`` and the actor takes the contact to himself
          inside his own direction (owner decision 2.2 of 05.11.2026).
    """
    if actor.is_full_admin:
        return True
    if not _has_direction_access(actor, requested_direction):
        return False
    if assignment is None or not getattr(assignment, "active", False):
        return True
    if getattr(assignment, "manager_id", None) == target_manager_id:
        return True
    if actor.can_take_colleague and target_manager_id == actor.manager_id:
        # Ответ заказчика 2.2 от 05.11.2026: забрать клиента коллеги СЕБЕ внутри
        # своего направления можно, включая живую переписку. Передать клиента
        # третьему менеджеру — по-прежнему админское полномочие: это распоряжение
        # чужой работой, а не взятие на себя. Между направлениями запрет остаётся
        # (`_has_direction_access` выше).
        return True
    return can_emergency_reassign(actor)
