"""Installed autonomous-send gate; explicit Wappi activation defaults empty."""
import logging
from copy import copy

from app.channels.wappi import WappiAdapter
from app.domain import entry_channel_policy as policy,entry_channel_stops as stops

log=logging.getLogger(__name__)
SendResult=stops.SendResult


def capture_adapter(adapter):
    # Wappi's send route is held in scalar instance fields. Capture those fields
    # before any await; the provider client is intentionally shared, not rebuilt.
    return copy(adapter) if isinstance(adapter,WappiAdapter) else adapter


def _engine():
    from app.integrations.crm.db import get_sessionmaker
    return get_sessionmaker().kw['bind']


def descriptor(adapter,chat_id):
    if not isinstance(adapter,WappiAdapter):policy.fail('unsupported_channel_adapter')
    return policy.route(adapter._base,adapter._profile_id,chat_id)


def resolve_dialog(channel,bot_id,chat_id):
    from app.channels.outbound import _adapter_for
    from app.core.bots import registry
    if channel!='whatsapp' or not bot_id:policy.fail('unsupported_channel_dialog')
    bot=registry.by_id(bot_id)
    if bot is None:policy.fail('channel_bot_unavailable')
    return descriptor(_adapter_for(channel,bot),chat_id)


def _activated(adapter,chat_id):
    if getattr(adapter,'channel',None)!='whatsapp':return None
    scopes=policy.deployment_scopes()
    if not scopes:return None
    if not isinstance(adapter,WappiAdapter):policy.fail('unsupported_channel_adapter')
    account=policy.scope(adapter._base,adapter._profile_id)
    if policy._hash(account) not in scopes:return None
    return descriptor(adapter,chat_id)


async def send(adapter,chat_id,callback):
    try:
        route=_activated(adapter,chat_id)
    except Exception as exc:
        log.warning('channel guard refused identity: %s',type(exc).__name__)
        return SendResult(False)
    if route is None:return SendResult(True,await callback())
    invoked=False
    async def pinned_callback():
        nonlocal invoked
        if descriptor(adapter,chat_id)!=route:policy.fail('channel_adapter_identity_changed')
        invoked=True
        return await callback()
    try:return await stops.guarded_send(_engine(),route,pinned_callback)
    except Exception as exc:
        # No fallback, no callback retry, no routing/personal data in this log.
        log.warning('channel guard unavailable or delivery unknown: %s',type(exc).__name__)
        if invoked:raise
        return SendResult(False)


async def blocked(adapter,chat_id):
    async def admitted():return None
    return not (await send(adapter,chat_id,admitted)).invoked
