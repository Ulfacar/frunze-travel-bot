"""WP3 assigned-manager authorization — PURE functions, no wiring.

Encodes the ownership rules that mirror ``reassign_manager`` and the admin roles:

* the active assigned manager (or a full-admin) may view and send;
* a peer may NOT take over an owned contact;
* re-affirming the same manager is always allowed;
* replacing a DIFFERENT active owner is an emergency reassignment, permitted ONLY
  to a full-admin;
* an unassigned contact may be claimed by any eligible manager.

This module is a FOUNDATION service: it is NOT imported by the live admin/takeover
endpoints, so production panel behaviour is unchanged. WP-later work will wire it in.

``assignment`` is duck-typed: any object exposing ``active`` (bool) and
``manager_id`` (str), or ``None`` when there is no active assignment.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    manager_id: str
    is_full_admin: bool = False


def _is_active_owner(actor: Actor, assignment) -> bool:
    return (assignment is not None and getattr(assignment, "active", False)
            and getattr(assignment, "manager_id", None) == actor.manager_id)


def can_view(actor: Actor, assignment) -> bool:
    """A full-admin sees everything; otherwise only the active assigned owner."""
    return actor.is_full_admin or _is_active_owner(actor, assignment)


def can_send(actor: Actor, assignment) -> bool:
    """Only the active assigned owner (or a full-admin) may send on a contact."""
    return actor.is_full_admin or _is_active_owner(actor, assignment)


def can_emergency_reassign(actor: Actor) -> bool:
    """Emergency takeover of a different active owner is a full-admin power only."""
    return actor.is_full_admin


def can_reassign(actor: Actor, assignment, target_manager_id: str) -> bool:
    """Whether ``actor`` may (re)assign the contact to ``target_manager_id``.

    * no active assignment → allowed (a first assignment / claim);
    * assignment already on ``target_manager_id`` → allowed (re-affirm);
    * taking over a DIFFERENT active owner → only a full-admin (emergency).
    """
    if assignment is None or not getattr(assignment, "active", False):
        return True
    if getattr(assignment, "manager_id", None) == target_manager_id:
        return True
    return can_emergency_reassign(actor)
