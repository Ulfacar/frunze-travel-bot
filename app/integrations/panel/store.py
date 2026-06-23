"""ConversationStore — персистентный лог диалогов для админ-панели.

Источник данных канбана и чат-окна: карточки = диалоги (Conversation), внутри —
человекочитаемый лог сообщений (ConvMessage). Два бэкенда за единым интерфейсом
(паттерн как у StateStore):
- `MemoryConversationStore` — дефолт (тесты, офлайн-демо, один процесс);
- `PostgresConversationStore` — прод (реюз движка из crm/db.py).
Выбор — `settings.panel_backend` (env `PANEL_BACKEND=postgres`); `get_conversation_store()`.

Read-методы возвращают простые dataclass-вью (ConversationView/MessageView), чтобы UI
не зависел от ORM и одинаково работал на обоих бэкендах.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import settings


@dataclass
class MessageView:
    sender: str           # client | bot | manager
    text: str
    created_at: datetime | None = None


@dataclass
class ConversationView:
    user_id: str
    channel: str = ""
    chat_id: str = ""
    bot_id: str = ""
    funnel: str | None = None
    stage: str = "greeting"
    intercepted: bool = False
    qualification: dict[str, Any] = field(default_factory=dict)
    ai_summary: str = ""
    manager_next_step: str = ""
    escalation_reason: str = ""
    lead_temperature: str = "new"
    last_text: str = ""
    last_sender: str = ""
    last_message_at: datetime | None = None
    messages: list[MessageView] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryConversationStore:
    """Лог диалогов в памяти процесса (дефолт)."""

    def __init__(self) -> None:
        self._conv: dict[str, ConversationView] = {}

    async def ensure(self, user_id: str, channel: str = "", bot_id: str = "",
                     chat_id: str = "") -> ConversationView:
        conv = self._conv.get(user_id)
        if conv is None:
            conv = ConversationView(user_id=user_id, channel=channel, bot_id=bot_id,
                                    chat_id=chat_id, last_message_at=_now())
            self._conv[user_id] = conv
        elif chat_id and not conv.chat_id:
            conv.chat_id = chat_id
        return conv

    async def add_message(self, user_id: str, sender: str, text: str,
                          channel: str = "", bot_id: str = "", chat_id: str = "") -> None:
        conv = await self.ensure(user_id, channel, bot_id, chat_id)
        conv.messages.append(MessageView(sender=sender, text=text, created_at=_now()))
        conv.last_text = text
        conv.last_sender = sender
        conv.last_message_at = _now()

    async def update_meta(self, user_id: str, *, funnel: str | None = None,
                          stage: str | None = None, qualification: dict | None = None,
                          intercepted: bool | None = None,
                          ai_summary: str | None = None,
                          manager_next_step: str | None = None,
                          escalation_reason: str | None = None,
                          lead_temperature: str | None = None) -> None:
        conv = await self.ensure(user_id)
        if funnel is not None:
            conv.funnel = funnel
        if stage is not None:
            conv.stage = stage
        if qualification is not None:
            conv.qualification = dict(qualification)
        if intercepted is not None:
            conv.intercepted = intercepted
        if ai_summary is not None:
            conv.ai_summary = ai_summary
        if manager_next_step is not None:
            conv.manager_next_step = manager_next_step
        if escalation_reason is not None:
            conv.escalation_reason = escalation_reason
        if lead_temperature is not None:
            conv.lead_temperature = lead_temperature

    async def set_intercepted(self, user_id: str, value: bool) -> None:
        await self.update_meta(user_id, intercepted=value)

    async def list_cards(self, funnel: str) -> list[ConversationView]:
        items = [c for c in self._conv.values() if c.funnel == funnel]
        items.sort(key=lambda c: c.last_message_at or _now(), reverse=True)
        return items

    async def get(self, user_id: str) -> ConversationView | None:
        return self._conv.get(user_id)


class PostgresConversationStore:
    """Лог диалогов в Postgres (прод). sessionmaker инъектируется в тестах."""

    def __init__(self, sessionmaker: async_sessionmaker | None = None) -> None:
        self._sessionmaker = sessionmaker

    def _sm(self) -> async_sessionmaker:
        if self._sessionmaker is None:
            from app.integrations.crm.db import get_sessionmaker
            self._sessionmaker = get_sessionmaker()
        return self._sessionmaker

    async def _ensure_row(self, session, user_id: str, channel: str, bot_id: str, chat_id: str = ""):
        from app.integrations.crm.db import Conversation
        conv = (await session.execute(
            select(Conversation).where(Conversation.user_id == user_id)
        )).scalar_one_or_none()
        if conv is None:
            conv = Conversation(user_id=user_id, channel=channel, bot_id=bot_id, chat_id=chat_id)
            session.add(conv)
            await session.flush()
        elif chat_id and not conv.chat_id:
            conv.chat_id = chat_id
        return conv

    async def ensure(self, user_id: str, channel: str = "", bot_id: str = "",
                     chat_id: str = "") -> None:
        async with self._sm()() as session:
            await self._ensure_row(session, user_id, channel, bot_id, chat_id)
            await session.commit()

    async def add_message(self, user_id: str, sender: str, text: str,
                          channel: str = "", bot_id: str = "", chat_id: str = "") -> None:
        from app.integrations.crm.db import ConvMessage
        async with self._sm()() as session:
            conv = await self._ensure_row(session, user_id, channel, bot_id, chat_id)
            session.add(ConvMessage(conversation_id=conv.id, sender=sender, text=text))
            conv.last_text = text
            conv.last_sender = sender
            conv.last_message_at = _now()
            await session.commit()

    async def update_meta(self, user_id: str, *, funnel: str | None = None,
                          stage: str | None = None, qualification: dict | None = None,
                          intercepted: bool | None = None,
                          ai_summary: str | None = None,
                          manager_next_step: str | None = None,
                          escalation_reason: str | None = None,
                          lead_temperature: str | None = None) -> None:
        async with self._sm()() as session:
            conv = await self._ensure_row(session, user_id, "", "")
            if funnel is not None:
                conv.funnel = funnel
            if stage is not None:
                conv.stage = stage
            if qualification is not None:
                conv.qualification = dict(qualification)
            if intercepted is not None:
                conv.intercepted = intercepted
            if ai_summary is not None:
                conv.ai_summary = ai_summary
            if manager_next_step is not None:
                conv.manager_next_step = manager_next_step
            if escalation_reason is not None:
                conv.escalation_reason = escalation_reason
            if lead_temperature is not None:
                conv.lead_temperature = lead_temperature
            await session.commit()

    async def set_intercepted(self, user_id: str, value: bool) -> None:
        await self.update_meta(user_id, intercepted=value)

    async def list_cards(self, funnel: str) -> list[ConversationView]:
        from app.integrations.crm.db import Conversation
        async with self._sm()() as session:
            rows = (await session.execute(
                select(Conversation).where(Conversation.funnel == funnel)
                .order_by(Conversation.last_message_at.desc())
            )).scalars().all()
            return [_view(r) for r in rows]

    async def get(self, user_id: str) -> ConversationView | None:
        from app.integrations.crm.db import Conversation
        async with self._sm()() as session:
            conv = (await session.execute(
                select(Conversation).options(selectinload(Conversation.messages))
                .where(Conversation.user_id == user_id)
            )).scalar_one_or_none()
            if conv is None:
                return None
            view = _view(conv)
            view.messages = [
                MessageView(sender=m.sender, text=m.text, created_at=m.created_at)
                for m in conv.messages
            ]
            return view


def _view(conv) -> ConversationView:
    """ORM Conversation → ConversationView (без сообщений)."""
    return ConversationView(
        user_id=conv.user_id, channel=conv.channel, chat_id=conv.chat_id, bot_id=conv.bot_id,
        funnel=conv.funnel, stage=conv.stage, intercepted=conv.intercepted,
        qualification=dict(conv.qualification or {}),
        ai_summary=getattr(conv, "ai_summary", "") or "",
        manager_next_step=getattr(conv, "manager_next_step", "") or "",
        escalation_reason=getattr(conv, "escalation_reason", "") or "",
        lead_temperature=getattr(conv, "lead_temperature", "new") or "new",
        last_text=conv.last_text,
        last_sender=conv.last_sender, last_message_at=conv.last_message_at,
    )


_memory_store = MemoryConversationStore()
_pg_store: PostgresConversationStore | None = None


def get_conversation_store():
    """Сконфигурированный бэкенд (singleton). По умолчанию — in-memory."""
    global _pg_store
    if settings.panel_backend == "postgres":
        if _pg_store is None:
            _pg_store = PostgresConversationStore()
        return _pg_store
    return _memory_store
