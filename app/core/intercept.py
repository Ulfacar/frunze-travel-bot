"""Shared dialog intercept helper."""
from __future__ import annotations

from app.core.state import get_state_store
from app.integrations.panel.store import get_conversation_store


async def set_intercept(user_id: str, value: bool) -> None:
    store = get_state_store()
    state = await store.load(user_id)
    state.intercepted = value
    await store.save(state)
    await get_conversation_store().set_intercepted(user_id, value)
