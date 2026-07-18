"""WP3: assigned-manager authorization — pure functions (M3 admin-send, M4 direction)."""
from dataclasses import dataclass

from app.domain.permissions import (
    Actor, can_emergency_reassign, can_reassign, can_send, can_view,
)


@dataclass
class Asg:
    manager_id: str
    direction: str = "visa"
    active: bool = True


OWNER = Actor("medina", allowed_directions=frozenset({"visa"}))
PEER = Actor("eliza", allowed_directions=frozenset({"visa"}))
TOURS_MGR = Actor("ademi", allowed_directions=frozenset({"tours"}))
ADMIN = Actor("boss", is_full_admin=True)


# --- owner / peer send --------------------------------------------------------

def test_active_owner_can_view_and_send():
    a = Asg("medina", direction="visa")
    assert can_view(OWNER, a, "visa") and can_send(OWNER, a, "visa")


def test_peer_cannot_view_or_send():
    a = Asg("medina", direction="visa")
    assert not can_view(PEER, a, "visa")
    assert not can_send(PEER, a, "visa")


# --- M3: full-admin cannot send without becoming owner ------------------------

def test_full_admin_can_view_and_reassign_but_not_send_others_client():
    a = Asg("medina", direction="visa")           # owned by medina
    assert can_view(ADMIN, a, "visa") is True      # admin may view
    assert can_reassign(ADMIN, a, "boss", "visa") is True   # admin may reassign
    assert can_send(ADMIN, a, "visa") is False     # but NOT send to medina's client


def test_new_owner_can_send_after_reassignment_old_owner_loses_it():
    # After emergency reassignment medina→boss, the active assignment is boss's.
    reassigned = Asg("boss", direction="visa")
    assert can_send(ADMIN, reassigned, "visa") is True    # admin now the active owner
    old = Asg("medina", direction="visa", active=False)   # medina's row now inactive
    assert can_send(OWNER, old, "visa") is False           # old owner loses send


def test_inactive_assignment_gives_no_send():
    assert can_send(OWNER, Asg("medina", active=False), "visa") is False


# --- M4: direction / cross-team ----------------------------------------------

def test_visa_manager_has_no_rights_on_tours_client():
    tours_asg = Asg("medina", direction="tours")
    # even if the row named medina, a visa-only manager has no tours access, and the
    # direction does not match the visa request either.
    assert can_send(OWNER, tours_asg, "tours") is False
    assert can_view(OWNER, tours_asg, "tours") is False


def test_tours_manager_has_no_rights_on_visa_client():
    visa_asg = Asg("ademi", direction="visa")
    assert can_send(TOURS_MGR, visa_asg, "visa") is False
    assert can_reassign(TOURS_MGR, visa_asg, "ademi", "visa") is False   # no visa access


def test_direction_mismatch_between_request_and_assignment_denies_send():
    visa_asg = Asg("medina", direction="visa")
    # medina owns the visa assignment but the requested action is on tours.
    assert can_send(OWNER, visa_asg, "tours") is False


# --- reassign rules -----------------------------------------------------------

def test_unassigned_can_be_claimed_and_reaffirm_allowed():
    assert can_reassign(PEER, None, "eliza", "visa") is True
    assert can_reassign(OWNER, Asg("medina"), "medina", "visa") is True


def test_peer_takeover_forbidden_emergency_admin_only():
    assert can_reassign(PEER, Asg("medina"), "eliza", "visa") is False
    assert can_emergency_reassign(ADMIN) is True
    assert can_emergency_reassign(PEER) is False
