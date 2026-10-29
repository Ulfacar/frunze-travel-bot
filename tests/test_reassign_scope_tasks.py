"""«Передать менеджеру…»: только тому, кто увидит диалог; задачи — следом (флаг OFF).

Найдено при сверке с Bitrix 30.10: список получателей был «все логины», и визовый
диалог можно было отдать туровому менеджеру — у неё он не открывается (404), а в
панели висит «ведёт Айсина». Задачи при передаче оставались у прежнего (ТЗ TASK-04).
"""
import asyncio
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.core import flags
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

PHONE = "996555222333"
UID = f"getvisa:{PHONE}"
MANAGERS = [
    ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
    ManagerConfig(login="medina", name="Медина", password="m1"),
    ManagerConfig(login="eliza", name="Элиза", password="e1"),
    ManagerConfig(login="aisina", name="Айсина", password="a1"),
]


def _setup(tmp_path, monkeypatch):
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    flags.reset()
    monkeypatch.setattr(app.config.settings, "managers", MANAGERS)
    monkeypatch.setattr(app.config.settings, "admin_chat_redesign_enabled", True)
    admin_router._look_cache["key"] = None
    url = f"sqlite+aiosqlite:///{(tmp_path / 'd.db').as_posix()}"

    async def _init():
        eng = create_async_engine(url)
        async with eng.begin() as conn:
            from app.domain.models import DomainBase
            await conn.run_sync(DomainBase.metadata.create_all)
        await eng.dispose()
    asyncio.run(_init())
    sm = async_sessionmaker(create_async_engine(url, poolclass=NullPool), expire_on_commit=False)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    store = get_conversation_store()

    async def _seed():
        await store.add_message(UID, "client", "виза", channel="whatsapp", bot_id="getvisa",
                                phone=PHONE, chat_id=f"{PHONE}@c.us")
        await store.update_meta(UID, funnel="visa", assigned_to="medina")
    asyncio.run(_seed())
    return sm


def _admin():
    c = TestClient(main.app, base_url="https://testserver")
    assert c.post("/admin/login", data={"login": "admin", "password": "frunze"}).status_code == 200
    return c


def _tasks(sm, *, direction="visa", n_open=2, n_done=1, owner="medina"):
    async def _mk():
        from app.domain.calendar_tasks import CalendarTaskService
        from app.domain.services import ContactService
        async with sm() as s:
            contact = await ContactService.find_or_create_by_identity(s, "phone", PHONE)
            for i in range(n_open + n_done):
                t = await CalendarTaskService.create(
                    s, manager_id=owner, direction=direction, kind="call",
                    scheduled_date=date.today() + timedelta(days=1), contact_id=contact.id,
                    user_id=UID, created_by=owner)
                if i >= n_open:
                    await CalendarTaskService.complete(s, t, actor=owner)
            await s.commit()
    asyncio.run(_mk())


def _owners(sm):
    async def _q():
        from app.domain.models import CalendarTask
        async with sm() as s:
            rows = (await s.scalars(select(CalendarTask).order_by(CalendarTask.id))).all()
            return [(t.direction, t.status, t.manager_id) for t in rows]
    return asyncio.run(_q())


def test_reassign_to_other_direction_is_refused(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch)
    r = _admin().post(f"/admin/conversation/{UID}/reassign", data={"target": "aisina"})
    assert r.status_code == 200 and r.headers["X-Action-Outcome"] == "denied"
    assert "не видит это направление" in r.text
    conv = asyncio.run(get_conversation_store().get(UID))
    assert conv.assigned_to == "medina"
    assert not [a for a in panel_store._memory_store._audit if a["action"] == "reassign"]

    async def _q():
        from app.domain.models import Assignment
        async with sm() as s:
            return (await s.scalars(select(Assignment))).all()
    assert asyncio.run(_q()) == []


def test_menu_offers_only_managers_who_see_the_dialog(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    html = _admin().get(f"/admin/conversation/{UID}").text
    block = html[html.index("chat-reassign-"):]
    block = block[:block.index("</form>")]
    for login in ("admin", "medina", "eliza"):
        assert f'value="{login}"' in block
    assert 'value="aisina"' not in block


def test_tasks_stay_when_flag_off(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch)
    _tasks(sm)
    r = _admin().post(f"/admin/conversation/{UID}/reassign", data={"target": "eliza"})
    assert "Лид передан менеджеру eliza." in r.text and "Задач перенесено" not in r.text
    assert [o for _, _, o in _owners(sm)] == ["medina", "medina", "medina"]


def test_open_tasks_follow_the_lead_when_flag_on(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch)
    asyncio.run(flags.set_flag("reassign_moves_tasks_enabled", True))
    _tasks(sm)                                   # 2 открытых + 1 выполненная
    _tasks(sm, direction="tours", n_open=1, n_done=0, owner="aisina")   # чужое направление
    r = _admin().post(f"/admin/conversation/{UID}/reassign", data={"target": "eliza"})
    assert "Задач перенесено: 2." in r.text
    assert _owners(sm) == [("visa", "planned", "eliza"), ("visa", "planned", "eliza"),
                           ("visa", "completed", "medina"), ("tours", "planned", "aisina")]

    async def _events():
        from app.domain.models import CalendarTaskEvent
        async with sm() as s:
            return [(e.event, e.actor, e.detail) for e in (await s.scalars(
                select(CalendarTaskEvent).where(CalendarTaskEvent.event == "reassigned"))).all()]
    assert _events_ok(asyncio.run(_events()))


def _events_ok(events):
    return len(events) == 2 and all(e == ("reassigned", "admin", "medina->eliza") for e in events)


def test_repeat_reassign_moves_nothing_more(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch)
    asyncio.run(flags.set_flag("reassign_moves_tasks_enabled", True))
    _tasks(sm, n_done=0)
    c = _admin()
    assert "Задач перенесено: 2." in c.post(f"/admin/conversation/{UID}/reassign",
                                           data={"target": "eliza"}).text
    second = c.post(f"/admin/conversation/{UID}/reassign", data={"target": "eliza"}).text
    assert "Задач перенесено" not in second
    assert [o for _, _, o in _owners(sm)] == ["eliza", "eliza"]
