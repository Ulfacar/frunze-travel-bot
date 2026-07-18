"""WP3: assigned-manager authorization — pure functions, no DB, no wiring."""
from dataclasses import dataclass

from app.domain.permissions import (
    Actor, can_emergency_reassign, can_reassign, can_send, can_view,
)


@dataclass
class Asg:
    manager_id: str
    active: bool = True


OWNER = Actor("medina")
PEER = Actor("eliza")
ADMIN = Actor("boss", is_full_admin=True)


def test_active_owner_can_view_and_send():
    a = Asg("medina")
    assert can_view(OWNER, a) and can_send(OWNER, a)


def test_peer_cannot_view_or_send():
    a = Asg("medina")
    assert not can_view(PEER, a)
    assert not can_send(PEER, a)


def test_full_admin_sees_and_sends_everything():
    a = Asg("medina")
    assert can_view(ADMIN, a) and can_send(ADMIN, a)
    assert can_view(ADMIN, None) and can_send(ADMIN, None)


def test_inactive_assignment_is_not_owned():
    a = Asg("medina", active=False)
    assert not can_view(OWNER, a)      # no active assignment → not the owner
    assert can_view(ADMIN, a)


def test_unassigned_contact_can_be_claimed_by_anyone():
    assert can_reassign(PEER, None, "eliza") is True
    assert can_reassign(OWNER, Asg("medina", active=False), "eliza") is True


def test_reaffirming_same_manager_is_allowed():
    assert can_reassign(OWNER, Asg("medina"), "medina") is True


def test_peer_takeover_of_active_owner_is_forbidden():
    # eliza tries to take medina's active contact — not a full-admin → denied.
    assert can_reassign(PEER, Asg("medina"), "eliza") is False


def test_emergency_reassignment_only_for_full_admin():
    assert can_reassign(ADMIN, Asg("medina"), "eliza") is True
    assert can_emergency_reassign(ADMIN) is True
    assert can_emergency_reassign(PEER) is False
