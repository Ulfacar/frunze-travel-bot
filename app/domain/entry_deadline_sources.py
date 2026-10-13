"""Bind proposed arithmetic to verified application facts, never planned dates."""
from datetime import date
import re

from app.domain import entry_applications as applications, entry_issued as issued
from app.domain.entry_calculations import _sources, _evaluate
from app.domain.entry_storage import EntryStorageInvalid, _document, _hash
from app.knowledge.bundle_schema import DATE, array, enum, nullable, obj
from app.knowledge.deadline_schema import DEADLINE_REQUEST

IDENTIFIER = {"type": "integer", "minimum": 1, "maximum": 2147483647}
ANCHOR = nullable(obj({"kind": enum("application_event", "travel"), "id": IDENTIFIER}))
RECALCULATE = obj({"knowledge_version_id": IDENTIFIER, "calendar_ids": array(IDENTIFIER, maximum=10),
                  "anchor": ANCHOR, "policy": DEADLINE_REQUEST["properties"]["policy"]})
MANUAL = obj({"due_on": DATE, "evidence_on": DATE, "proof": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
              "source": enum("portal", "official_document"), "reason": enum("official_date", "corrected_date")})
CLEAR = obj({"reason": enum("no_longer_confirmed", "wrong_document", "awaiting_clarification")})
OPERATION = {"oneOf": [obj({"action": {"const": action}, "data": schema, "confirmed": {"const": True}})
                        for action, schema in (("recalculate", RECALCULATE), ("manual", MANUAL), ("clear", CLEAR))]}
EVENT_ANCHORS = {"submitted": "submission_date", "revision_requested": "return_date", "approved": "approval_date"}


def normalize(operation, *, cutoff):
    operation = _document(operation, OPERATION)
    data = operation["data"]
    if operation["action"] == "recalculate":
        if len(set(data["calendar_ids"])) != len(data["calendar_ids"]):
            raise EntryStorageInvalid("duplicate_calendar_identifier")
        data["calendar_ids"] = sorted(data["calendar_ids"])
    if operation["action"] == "manual":
        try:
            dates = [date.fromisoformat(data[key]) for key in ("due_on", "evidence_on")]
            if any(day.isoformat() != data[key] for day, key in zip(dates, ("due_on", "evidence_on"))) or dates[1] > cutoff:
                raise ValueError
        except ValueError:
            raise EntryStorageInvalid("invalid_deadline_date") from None
    return operation


def unit_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"KG\.DL\.[A-Z0-9_]{1,64}", value):
        raise EntryStorageInvalid("invalid_deadline_unit")
    return value


async def actual_anchor(session, application, selection):
    """Caller holds the application's parent lock for a coherent source snapshot."""
    events = await applications._events(session, application)
    if selection is None:
        return None
    if selection["kind"] == "application_event":
        event = next((r for r in events if r.id == selection["id"]), None)
        if event is None or event.status not in EVENT_ANCHORS or event.source not in ("portal", "official_document"):
            raise EntryStorageInvalid("deadline_anchor_unavailable")
        latest = max((r for r in events if r.status == event.status), key=lambda r: r.revision)
        return dict(**selection, name=EVENT_ANCHORS[event.status], value=event.occurred_on.isoformat(),
            snapshot_hash=event.snapshot_hash, source=event.source, reference=event.reference,
            superseded=event.id != latest.id)
    rows, _ = await issued._history(session, application, issued._approval(application, events))
    event = next((r for r in rows if r.id == selection["id"] and r.command["operation"]["action"] == "travel"), None)
    if event is None:
        raise EntryStorageInvalid("deadline_anchor_unavailable")
    data = event.command["operation"]["data"]
    latest = max((r for r in rows if r.command["operation"]["action"] == "travel" and
        r.command["operation"]["data"]["direction"] == data["direction"]),
        key=lambda r: (r.command["operation"]["data"]["on"], r.id))
    return dict(**selection, name="entry_date" if data["direction"] == "entry" else "exit_date", value=data["on"],
        snapshot_hash=event.snapshot_hash, source=data["source"], proof=data["proof"],
        passport_fingerprint=data["passport_fingerprint"], superseded=event.id != latest.id)


async def calculate_bound_deadline(session, case, application, rule_unit_id, data):
    """Unknowns remain unknown; a computed draft candidate never becomes a due date."""
    bundle, calendars, _, _, provenance = await _sources(session, case.contact_id,
        data["knowledge_version_id"], None, data["calendar_ids"])
    rule = next((r for r in bundle["units"] if r["unit_id"] == rule_unit_id and r["kind"] == "deadline"), None)
    if rule is None:
        raise EntryStorageInvalid("deadline_rule_unavailable")
    anchor = await actual_anchor(session, application, data["anchor"])
    return build_snapshot(bundle, calendars, provenance, application.snapshot_hash, rule, data, anchor)


def build_snapshot(bundle, calendars, provenance, application_hash, rule, data, anchor):
    """Pure calculation also supports replay against a verified historical anchor."""
    blockers = []
    if anchor is None:
        blockers.append("actual_anchor_missing")
    elif anchor["superseded"]:
        blockers.append("actual_anchor_superseded")
    if rule["value"] is None:
        blockers.append("rule_value_missing")
    elif anchor is not None and rule["value"]["anchor"] != anchor["name"]:
        blockers.append("source_anchor_not_supported")
    if data["policy"] is None:
        blockers.append("counting_policy_missing")
    review = None
    if not blockers:
        request = dict(format="kg-deadline-review-input/1", rule_unit_id=rule['unit_id'],
                       anchor={k: anchor[k] for k in ("name", "value")}, policy=data["policy"])
        _, review = _evaluate("deadline", bundle, calendars, None, request)
        blockers.extend(review["blocked_by"])
    return dict(format="kg-application-deadline/1", selection=data, source=provenance, source_label=bundle['meta']['version_label'],
        application_hash=application_hash, rule_hash=_hash(rule),
        rule={k: rule[k] for k in ("unit_id", "title", "section", "page", "source_ref", "confirmation_status", "label")},
        anchor=anchor, review=review, blockers=blockers, manual=None,
        publication_approved=False, may_quote=False)


def summary(snapshot):
    review = snapshot.get("review") or {}
    scenario = review.get("scenario") or {}
    manual = snapshot.get("manual")
    return dict(candidate_due=scenario.get("due"), operational_due_on=manual["due_on"] if manual else None,
        status="manual_evidence" if manual else "draft_candidate" if scenario else "unknown",
        blockers=snapshot["blockers"], publication_approved=False, may_quote=False)
