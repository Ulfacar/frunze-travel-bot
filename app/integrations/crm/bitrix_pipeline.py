"""Best-effort pipeline for Bitrix lead stages, dossier and sale read-back."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.core import flags
from app.integrations.crm.bitrix24 import (
    LEAD_COMMENTS_MARKER,
    sanitize_lead_comments,
    strip_lead_comments_bbcode,
)
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("crm.bitrix_pipeline")

STAGE_SEQUENCE: tuple[str, ...] = (
    "NEW", "UC_S0NTF8", "UC_Y4VY7B", "UC_1I1YV0", "UC_T9AEO4",
    "UC_A492DB", "UC_PNSIIB",
)
TERMINAL_STATUSES = frozenset({"CONVERTED", "JUNK", "UC_R8BD0W"})
DOSSIER_MARKER = LEAD_COMMENTS_MARKER
READ_BACK_LIMIT = 100
_tasks: set[asyncio.Task] = set()
_inflight_stages: set[tuple[str, str]] = set()

_LEGACY_KEYS = frozenset({
    "destination", "region", "departure_city", "tourists", "children_ages", "budget",
    "dates", "nights", "hotel_stars", "meal", "name", "country", "trip_purpose",
    "purpose", "age", "marital_status", "occupation", "prior_countries", "companions",
    "english_level", "prior_refusal", "prior_visas", "visa_country",
})


def _adapter(adapter: Any = None) -> Any:
    if adapter is not None:
        return adapter
    from app.integrations.crm.bitrix24 import Bitrix24Crm
    return Bitrix24Crm()


async def _enabled(conv: Any) -> bool:
    global_on = await flags.get_flag("bitrix_pipeline_enabled", settings.bitrix_pipeline_enabled)
    bot_id = (getattr(conv, "bot_id", "") or str(conv.user_id).partition(":")[0]).strip()
    return await flags.get_flag(f"bitrix_pipeline_enabled:{bot_id}", global_on)


async def advance(conv_key: str, internal_stage: str, *, adapter: Any = None,
                  _conv: Any = None, _lead: dict | None = None) -> str:
    """Move a lead forward if the bot still owns its stage; return the new STATUS_ID."""
    store = get_conversation_store()
    conv = _conv if _conv is not None else await store.get(conv_key)
    stage_map = settings.bitrix_stage_map or {}
    if conv is None or not stage_map or not await _enabled(conv):
        return ""
    lead_id = getattr(conv, "bitrix_lead_id", "") or ""
    target = stage_map.get(internal_stage, "")
    if not lead_id or not target or getattr(conv, "intercepted", False):
        return ""
    client = _adapter(adapter)
    try:
        lead = _lead if _lead is not None else await client.get_lead(lead_id)
        current = str(lead.get("STATUS_ID") or "")
        remembered = getattr(conv, "bitrix_stage_by_bot", "") or ""
        if current in TERMINAL_STATUSES:
            log.info("pipeline skip terminal conv_key=%s from=%s to=%s", conv_key, current, target)
            return ""
        if remembered and current != remembered:
            log.info("pipeline skip frozen_manual conv_key=%s from=%s to=%s", conv_key, current, target)
            return ""
        if target not in STAGE_SEQUENCE or current not in STAGE_SEQUENCE:
            return ""
        if STAGE_SEQUENCE.index(target) <= STAGE_SEQUENCE.index(current):
            return ""
        await client.update_stage_status(lead_id, target)
        lead["STATUS_ID"] = target
        await store.update_meta(conv_key, bitrix_stage_by_bot=target)
        log.info("pipeline moved conv_key=%s from=%s to=%s", conv_key, current, target)
        return target
    except Exception:  # noqa: BLE001 - CRM side channel is fail-open
        log.warning("pipeline advance failed conv_key=%s", conv_key, exc_info=True)
        return ""


def render_dossier(conv: Any, qualification: dict) -> str:
    q = dict(qualification or {})
    lines = [DOSSIER_MARKER]
    labels = (
        (("destination", "region", "country", "visa_country", "направление"), "Направление"),
        (("budget", "бюджет"), "Бюджет"), (("dates", "nights", "даты"), "Даты"),
        (("tourists", "adults", "children", "children_ages", "companions",
          "взрослых", "детей"), "Состав"),
    )
    for keys, label in labels:
        values = [str(q[k]).strip() for k in keys if str(q.get(k) or "").strip()]
        if values:
            lines.append(f"{label}: {' · '.join(values)}")
    offer_url = str(q.get("offer_url") or q.get("tour_url") or "").strip()
    if not offer_url:
        for message in reversed(getattr(conv, "messages", []) or []):
            match = re.search(r"https?://\S+/t/[\w-]+", getattr(message, "text", "") or "")
            if match:
                offer_url = match.group(0).rstrip(".,)")
                break
    if offer_url:
        lines.append(f"Предложено: {offer_url}")
    base = settings.public_base_url.rstrip("/") if settings.public_base_url else ""
    panel_path = f"/admin/conversation/{conv.user_id}"
    lines.append(f"Диалог: {base + panel_path if base else panel_path}")
    if getattr(conv, "last_message_at", None):
        lines.append(f"Последнее сообщение: {conv.last_message_at:%d.%m.%Y %H:%M}")
    return sanitize_lead_comments("\n".join(lines))


def _legacy_ours(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    for line in lines:
        key, sep, value = line.partition(":")
        if not sep or not value.strip() or key.strip() not in _LEGACY_KEYS:
            return False
    return True


def _dossier_ours(text: str) -> bool:
    """Recognise our marker in portal-normalised COMMENTS.

    Bitrix may add BBCode around links on read-back.  Ownership lives only in the
    first non-empty visible line; dossier contents are deliberately not compared.
    """
    visible = strip_lead_comments_bbcode(text)
    first_line = next((line.strip() for line in visible.splitlines() if line.strip()), "")
    return first_line.startswith(DOSSIER_MARKER)


async def sync_dossier(conv_key: str, *, qualification: dict | None = None,
                       adapter: Any = None, _conv: Any = None,
                       _lead: dict | None = None) -> bool:
    store = get_conversation_store()
    conv = _conv if _conv is not None else await store.get(conv_key)
    if conv is None or not await _enabled(conv):
        return False
    lead_id = getattr(conv, "bitrix_lead_id", "") or ""
    if not lead_id or getattr(conv, "intercepted", False):
        return False
    client = _adapter(adapter)
    try:
        lead = _lead if _lead is not None else await client.get_lead(lead_id)
        if str(lead.get("STATUS_ID") or "") in TERMINAL_STATUSES:
            return False
        comments = str(lead.get("COMMENTS") or "")
        if comments and not _dossier_ours(comments) and not _legacy_ours(comments):
            return False
        text = render_dossier(conv, conv.qualification if qualification is None else qualification)
        await client.update_comments(lead_id, text)
        return True
    except Exception:  # noqa: BLE001
        log.warning("pipeline dossier failed conv_key=%s", conv_key, exc_info=True)
        return False


def _opportunity(conv: Any) -> str:
    value = getattr(conv, "estimated_value", None)
    if value is not None:
        return str(value)
    budget = str((getattr(conv, "qualification", {}) or {}).get("budget") or "")
    match = re.search(r"\d[\d\s.,]*", budget)
    return re.sub(r"[^\d.]", "", match.group(0).replace(",", ".")) if match else ""


async def read_back_once(*, adapter: Any = None) -> dict:
    stats = {key: 0 for key in ("checked", "moved", "frozen_manual", "dossier_written",
            "dossier_skipped_human", "won", "deals_created", "deals_dry_run", "errors")}
    client = _adapter(adapter)
    store = get_conversation_store()
    convs = await store.all_conversations_light()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.bitrix_read_back_days)

    def _recent(conv: Any) -> bool:
        active = getattr(conv, "last_message_at", None)
        if active is None:
            return False
        if active.tzinfo is None:
            active = active.replace(tzinfo=timezone.utc)
        return active >= cutoff

    candidates = [c for c in convs if getattr(c, "bitrix_lead_id", "") and _recent(c)]
    for conv in candidates[:READ_BACK_LIMIT]:
        try:
            lead = await client.get_lead(conv.bitrix_lead_id)
            stats["checked"] += 1
            if str(lead.get("STATUS_ID") or "") != "CONVERTED":
                continue
            if (getattr(conv, "outcome", "") or "") != "won":
                await store.update_meta(conv.user_id, outcome="won")
                stats["won"] += 1
            if getattr(conv, "bitrix_deal_id", ""):
                continue
            if not await flags.get_flag("bitrix_autodeal_enabled", settings.bitrix_autodeal_enabled):
                stats["deals_dry_run"] += 1
                continue
            fields = {
                "CATEGORY_ID": settings.bitrix_deal_category_id,
                "STAGE_ID": settings.bitrix_deal_stage_id,
                "TITLE": str(lead.get("TITLE") or f"Тур: {getattr(conv, 'phone', conv.user_id)}"),
                "COMMENTS": f"Диалог: /admin/conversation/{conv.user_id}",
            }
            if lead.get("ASSIGNED_BY_ID"):
                fields["ASSIGNED_BY_ID"] = lead["ASSIGNED_BY_ID"]
            opportunity = _opportunity(conv)
            if opportunity:
                fields["OPPORTUNITY"] = opportunity
            deal_id = await client.create_deal(fields)
            if deal_id:
                await store.update_meta(conv.user_id, bitrix_deal_id=deal_id)
                stats["deals_created"] += 1
        except Exception:  # noqa: BLE001
            stats["errors"] += 1
            log.warning("pipeline read-back failed conv_key=%s", conv.user_id, exc_info=True)
    log.info("pipeline read-back stats=%s", stats)
    return stats


async def _advance_and_sync(conv_key: str, stage: str, qualification: dict | None) -> None:
    store = get_conversation_store()
    conv = await store.get(conv_key)
    if conv is None:
        return
    target = (settings.bitrix_stage_map or {}).get(stage, "")
    if target and (getattr(conv, "bitrix_stage_by_bot", "") or "") == target:
        return
    lead_id = getattr(conv, "bitrix_lead_id", "") or ""
    if not lead_id:
        return
    client = _adapter()
    try:
        lead = await client.get_lead(lead_id)
    except Exception:  # noqa: BLE001
        log.warning("pipeline lead read failed conv_key=%s", conv_key, exc_info=True)
        return
    await advance(conv_key, stage, adapter=client, _conv=conv, _lead=lead)
    await sync_dossier(
        conv_key, qualification=qualification, adapter=client, _conv=conv, _lead=lead,
    )


def fire(conv_key: str, stage: str, qualification: dict | None) -> None:
    """Schedule portal work without delaying the customer response."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    key = (conv_key, stage)
    if key in _inflight_stages:
        return
    task = loop.create_task(_advance_and_sync(conv_key, stage, qualification))
    _inflight_stages.add(key)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    task.add_done_callback(lambda _done: _inflight_stages.discard(key))
