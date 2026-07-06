"""Shared lead classification for board columns, cleanup and follow-up.

The admin board and background follow-up must agree on what is noise and what is
"silent". Keep these helpers pure so they are easy to test and reuse.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


STAGE_TO_COLUMN = {
    "greeting": "greeting", "new": "greeting",
    "qualification": "qualification",
    "progress": "progress", "scoring": "progress", "search": "progress", "visa_scoring": "progress",
    "office": "office", "office_consultation": "office",
    "manager": "manager", "manager_handoff": "manager",
    "follow_up": "follow_up", "followup": "follow_up", "callback": "follow_up",
}

HUMAN_STAGES = {"office", "office_consultation", "manager", "manager_handoff"}
NOISE_STAGES = {"greeting", "new"}
# Из дожима исключаем только «на живом менеджере». Прошедших консультацию/офис (office*) и уже
# пингованных (follow_up) — дожимаем по расписанию (правка со встречи 06.07), ритм ограничен
# числом пингов и интервалом (см. is_silent + followup_max_pings/followup_interval_hours).
SILENT_EXCLUDED_COLUMNS = {"manager"}
TERMINAL_OUTCOMES = {"won", "lost"}

NOISE_LINK_RE = re.compile(
    r"(https?://|instagram\.com|fb\.me|facebook\.com|wa\.me|api\.whatsapp|t\.me|telegram\.me)",
    re.IGNORECASE,
)
NOISE_MEDIA_TERMS = ("[media", "[медиа", "[голос", "голос", "voice", "audio")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _has_message(conv) -> bool:
    return bool(getattr(conv, "messages", None) or getattr(conv, "last_text", "") or getattr(conv, "last_sender", ""))


def _has_bot_or_manager_message(conv) -> bool:
    return any(getattr(m, "sender", "") in {"bot", "manager"} for m in (getattr(conv, "messages", None) or []))


def _only_client_messages(conv) -> bool:
    messages = getattr(conv, "messages", None) or []
    if messages:
        return any(getattr(m, "sender", "") == "client" for m in messages) and not _has_bot_or_manager_message(conv)
    return getattr(conv, "last_sender", "") == "client"


def is_noise(conv, now: datetime | None = None, cfg=None) -> bool:
    """Advertising/media-only or dead empty greeting lead that can be archived."""
    stage = getattr(conv, "stage", "")
    if (
        stage not in NOISE_STAGES
        or getattr(conv, "intercepted", False)
        or getattr(conv, "assigned_to", "")
        or getattr(conv, "qualification", None)
    ):
        return False

    text = (getattr(conv, "last_text", "") or "").strip().lower()
    link_or_media = bool(NOISE_LINK_RE.search(text)) or any(term in text for term in NOISE_MEDIA_TERMS)
    if getattr(conv, "last_sender", "") == "client" and link_or_media:
        return True

    now = _aware(now) or datetime.now(timezone.utc)
    last = _aware(getattr(conv, "last_message_at", None))
    stale_days = getattr(cfg, "noise_stale_days", 3)
    is_stale = bool(last and last <= now - timedelta(days=stale_days))
    return is_stale and _has_message(conv) and _only_client_messages(conv)


def followup_pings(conv) -> int:
    """Сколько пингов дожима уже отправлено (совместимо со старым булевым followup_sent)."""
    count = int(getattr(conv, "followup_count", 0) or 0)
    if count == 0 and getattr(conv, "followup_sent", False):
        return 1  # legacy-лид, помеченный старым флагом до перехода на счётчик
    return count


def is_silent(conv, now: datetime, cfg) -> bool:
    """Broad stuck-lead definition used by both board and auto-follow-up.

    Ритм дожима: до `followup_max_pings` пингов на клиента; первый — после
    `followup_after_hours` тишины, повторные — не чаще `followup_interval_hours` (~2×/неделю).
    """
    now = _aware(now) or datetime.now(timezone.utc)
    if getattr(conv, "intercepted", False):
        return False
    pings = followup_pings(conv)
    if pings >= getattr(cfg, "followup_max_pings", 2):
        return False  # лимит пингов исчерпан — больше не дожимаем
    if getattr(conv, "outcome", "") in TERMINAL_OUTCOMES:
        return False
    if STAGE_TO_COLUMN.get(getattr(conv, "stage", ""), "greeting") in SILENT_EXCLUDED_COLUMNS:
        return False
    if is_noise(conv, now, cfg):
        return False
    if not _has_message(conv):
        return False
    last = _aware(getattr(conv, "last_message_at", None))
    if last is None:
        return False
    # Первый пинг — после followup_after_hours тишины; повторные — не чаще followup_interval_hours.
    hours = (getattr(cfg, "followup_after_hours", 24) if pings == 0
             else getattr(cfg, "followup_interval_hours", 84))
    return last <= now - timedelta(hours=hours)
