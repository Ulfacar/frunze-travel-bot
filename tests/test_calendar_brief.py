"""Sprint 1: personal calendar Morning Brief (per-manager). Time/telegram/DB injected."""
import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import ManagerConfig
from app.core import calendar_brief as cb
from app.core import flags
from app.domain.calendar_tasks import CalendarTaskService
from app.domain.models import Contact

NOW = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)   # 10:00 Bishkek → inside [9,12)
TODAY = date(2026, 7, 20)


@dataclass
class Task:
    kind: str
    scheduled_at: datetime | None = None
    priority: str = "normal"
    status: str = "planned"
    user_id: str = "getvisa:996700111"
    comment: str = ""
    ai_summary: str = ""
    direction: str = "visa"


@dataclass
class Conv:
    bot_id: str = "getvisa"
    user_id: str = "getvisa:996700999"
    funnel: str = "visa"
    outcome: str = ""
    assigned_to: str = ""
    intercepted: bool = False
    last_sender: str = "client"
    last_message_at: datetime = NOW
    qualification: dict = field(default_factory=dict)
    estimated_value: float | None = None
    estimated_value_currency: str = ""
    readiness_reason: str = ""


class _Store:
    def __init__(self, convs):
        self._convs = convs

    async def all_conversations_light(self):
        return self._convs


# --- pure builder / render ----------------------------------------------------

def test_build_and_render_contains_tasks_and_night():
    tasks = [Task("call", scheduled_at=datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
                  comment="перезвонить", ai_summary="ждёт визу в Дубай")]
    night = [Conv(qualification={"name": "Асель"})]
    brief = cb.build_manager_brief("medina", "Медина", tasks, night, NOW)
    assert brief["task_count"] == 1 and brief["night_count"] == 1
    text = cb.render_manager_brief_text(brief, base_url="https://p.kg")
    assert "📅 План" in text and "перезвонить" in text and "14:00" in text  # 08:00 UTC = 14:00 Bishkek
    assert "ждёт визу в Дубай" in text
    assert "🌙 Ночные заявки" in text and "Асель" in text
    assert "https://p.kg/admin/conversation/getvisa:996700111" in text


# --- run: flags / delivery ----------------------------------------------------

def _domain_sm():
    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    return engine


async def _prepare(engine):
    from app.domain.models import DomainBase
    async with engine.begin() as conn:
        await conn.run_sync(DomainBase.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _run_case(body, monkeypatch, *, convs=None, managers=None):
    async def _main():
        flags.reset()
        engine = _domain_sm()
        sm = await _prepare(engine)
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            await CalendarTaskService.create(s, manager_id="medina", direction="visa",
                                             kind="call", scheduled_date=TODAY, contact_id=c.id,
                                             user_id="getvisa:996700111", comment="звонок")
            await s.commit()
        monkeypatch.setattr("app.integrations.panel.store.get_conversation_store",
                            lambda: _Store(convs if convs is not None else []))
        monkeypatch.setattr(cb.settings, "managers", managers if managers is not None else [
            ManagerConfig(login="medina", name="Медина", telegram_chat_id="111"),
        ], raising=False)
        monkeypatch.setattr(cb.settings, "telegram_bot_token", "tok", raising=False)
        sent = []
        async def fake_push(token, chat_id, text):
            sent.append((chat_id, text)); return True
        monkeypatch.setattr(cb, "_push_telegram", fake_push)
        try:
            await body(sm, sent)
        finally:
            flags.reset()
            await engine.dispose()
    asyncio.run(_main())


def test_flag_off_sends_nothing(monkeypatch):
    async def body(sm, sent):
        await cb.run(NOW, sessionmaker=sm)          # calendar_brief_enabled default OFF
        assert sent == []
    _run_case(body, monkeypatch)


def test_flag_on_sends_personal_brief(monkeypatch):
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        assert len(sent) == 1
        chat_id, text = sent[0]
        assert chat_id == "111" and "звонок" in text
    _run_case(body, monkeypatch)


def test_idempotent_per_manager(monkeypatch):
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        await cb.run(NOW, sessionmaker=sm)          # second run same day
        assert len(sent) == 1                        # sent once
    _run_case(body, monkeypatch)


def test_manager_without_chat_id_skipped(monkeypatch):
    managers = [ManagerConfig(login="medina", name="Медина", telegram_chat_id=""),
                ManagerConfig(login="eliza", name="Элиза", telegram_chat_id="222")]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        # medina (no chat id) skipped; eliza gets a brief (empty tasks but night/greeting)
        assert [c for c, _ in sent] == ["222"]
    _run_case(body, monkeypatch, managers=managers)


def test_outside_window_no_send(monkeypatch):
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        early = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)   # 06:00 Bishkek < 09:00
        await cb.run(early, sessionmaker=sm)
        assert sent == []
    _run_case(body, monkeypatch)


def test_night_requests_scoped_to_manager_bots(monkeypatch):
    convs = [Conv(bot_id="getvisa", user_id="getvisa:1", qualification={"name": "Виза-клиент"}),
             Conv(bot_id="frunze_tours", user_id="frunze_tours:2",
                  qualification={"name": "Тур-клиент"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        _, text = sent[0]
        assert "Виза-клиент" in text            # medina's bot scope = getvisa
        assert "Тур-клиент" not in text          # tours bot out of scope
    _run_case(body, monkeypatch, convs=convs)
