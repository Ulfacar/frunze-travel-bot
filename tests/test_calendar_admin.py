"""Sprint 1: admin calendar/task routes (TestClient). Domain DB is a temp SQLite file
injected via _domain_sessionmaker; conversation store is the in-memory panel."""
import asyncio

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

USER_ID = "getvisa:996700123456"


def _clear():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()


def _make_domain_sm(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'domain.db').as_posix()}"

    async def _init():
        eng = create_async_engine(url)
        async with eng.begin() as conn:
            from app.domain.models import DomainBase
            await conn.run_sync(DomainBase.metadata.create_all)
        await eng.dispose()
    asyncio.run(_init())
    eng = create_async_engine(url, poolclass=NullPool)   # fresh conn per session (loop-safe)
    return async_sessionmaker(eng, expire_on_commit=False)


def _seed_conv(bot_id="getvisa", funnel="visa"):
    store = get_conversation_store()

    async def _s():
        await store.add_message(USER_ID, "client", "нужна виза", channel="whatsapp",
                                bot_id=bot_id, phone="996700123456")   # valid KG (12 digits)
        await store.update_meta(USER_ID, funnel=funnel)
    asyncio.run(_s())


def _admin_client():
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login", data={"login": "admin", "password": "frunze"}).status_code == 200
    return client


def _domain_tasks(sm):
    async def _q():
        from sqlalchemy import select
        from app.domain.models import CalendarTask
        async with sm() as s:
            return (await s.scalars(select(CalendarTask))).all()
    return asyncio.run(_q())


def test_calendar_page_renders(tmp_path, monkeypatch):
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    r = _admin_client().get("/admin/calendar")
    assert r.status_code == 200
    assert "Календарь" in r.text and "День" in r.text and "Неделя" in r.text


def test_task_create_persists_and_shows_in_card(tmp_path, monkeypatch):
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    _seed_conv()
    client = _admin_client()
    today = admin_router._bishkek_today().isoformat()
    r = client.post(f"/admin/conversation/{USER_ID}/task/create",
                    data={"kind": "call", "scheduled_date": today, "priority": "high",
                          "comment": "перезвонить клиенту"})
    assert r.status_code == 200
    assert "перезвонить клиенту" in r.text          # task rendered in the card
    tasks = _domain_tasks(sm)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.manager_id == "admin" and t.kind == "call" and t.status == "planned"
    assert t.user_id == USER_ID and t.contact_id is not None   # Contact was resolved/created


def test_task_complete_moves_to_history(tmp_path, monkeypatch):
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    _seed_conv()
    client = _admin_client()
    today = admin_router._bishkek_today().isoformat()
    client.post(f"/admin/conversation/{USER_ID}/task/create",
                data={"kind": "meeting", "scheduled_date": today, "comment": "встреча"})
    task_id = _domain_tasks(sm)[0].id
    r = client.post(f"/admin/conversation/{USER_ID}/task/{task_id}/complete")
    assert r.status_code == 200
    assert "Активных задач нет" in r.text            # no active tasks remain
    assert _domain_tasks(sm)[0].status == "completed"


def test_calendar_lists_created_task(tmp_path, monkeypatch):
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    _seed_conv()
    client = _admin_client()
    today = admin_router._bishkek_today().isoformat()
    client.post(f"/admin/conversation/{USER_ID}/task/create",
                data={"kind": "office_visit", "scheduled_date": today, "comment": "визит в офис"})
    r = client.get(f"/admin/calendar?view=day&day={today}")
    assert r.status_code == 200
    assert "визит в офис" in r.text


def test_manager_sees_only_own_tasks(tmp_path, monkeypatch):
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="medina", name="Медина", password="pw"),
        ManagerConfig(login="eliza", name="Элиза", password="pw"),
    ], raising=False)
    _seed_conv(bot_id="getvisa")     # both medina & eliza scope = getvisa

    medina = TestClient(main.app, base_url="https://testserver")
    assert medina.post("/admin/login", data={"login": "medina", "password": "pw"}).status_code == 200
    today = admin_router._bishkek_today().isoformat()
    medina.post(f"/admin/conversation/{USER_ID}/task/create",
                data={"kind": "call", "scheduled_date": today, "comment": "медина-задача"})
    assert "медина-задача" in medina.get(f"/admin/calendar?view=day&day={today}").text

    eliza = TestClient(main.app, base_url="https://testserver")
    assert eliza.post("/admin/login", data={"login": "eliza", "password": "pw"}).status_code == 200
    # eliza can VIEW the shared getvisa conversation but the task belongs to medina only.
    assert "медина-задача" not in eliza.get(f"/admin/calendar?view=day&day={today}").text
