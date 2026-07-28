"""Sprint 1: admin calendar/task routes (TestClient). Domain DB is a temp SQLite file
injected via _domain_sessionmaker; conversation store is the in-memory panel."""
import asyncio
from datetime import timedelta

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


def _create_task(client, sm, **over) -> int:
    data = {"kind": "call", "scheduled_date": admin_router._bishkek_today().isoformat(),
            "comment": "перезвонить"}
    data.update(over)
    client.post(f"/admin/conversation/{USER_ID}/task/create", data=data)
    return _domain_tasks(sm)[-1].id


def test_calendar_day_shows_phone_and_call_actions(tmp_path, monkeypatch):
    """Карточка дня даёт менеджеру всё для звонка: номер, tel:/wa-ссылки, one-tap действия."""
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    _seed_conv()
    client = _admin_client()
    task_id = _create_task(client, sm, scheduled_time="09:30", priority="high")
    r = client.get("/admin/calendar")
    assert r.status_code == 200
    assert "+996 700 12 34 56" in r.text          # полный номер, а не «последние 4»
    assert "tel:+996700123456" in r.text and "https://wa.me/996700123456" in r.text
    assert f"/admin/calendar/task/{task_id}/complete" in r.text
    assert f"/admin/calendar/task/{task_id}/snooze" in r.text
    assert "09:30" in r.text


def test_calendar_complete_from_calendar(tmp_path, monkeypatch):
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    _seed_conv()
    client = _admin_client()
    task_id = _create_task(client, sm)
    r = client.post(f"/admin/calendar/task/{task_id}/complete",
                    data={"view": "day", "day": ""}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/calendar")
    assert _domain_tasks(sm)[0].status == "completed"
    # выполненная задача остаётся видна в дне — блоком «Сделано»
    assert "Сделано" in client.get("/admin/calendar").text


def test_calendar_snooze_moves_task(tmp_path, monkeypatch):
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    _seed_conv()
    client = _admin_client()
    today = admin_router._bishkek_today()
    task_id = _create_task(client, sm, scheduled_time="10:00")
    client.post(f"/admin/calendar/task/{task_id}/snooze", data={"mode": "tomorrow", "view": "day"})
    t = _domain_tasks(sm)[0]
    assert t.scheduled_date == today + timedelta(days=1) and t.status == "rescheduled"
    assert t.scheduled_at is not None                       # время дня сохранено
    assert (t.scheduled_at + timedelta(hours=6)).strftime("%H:%M") == "10:00"


def test_calendar_quick_create_by_phone_links_conversation(tmp_path, monkeypatch):
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    _seed_conv()
    client = _admin_client()
    today = admin_router._bishkek_today().isoformat()
    r = client.post("/admin/calendar/task/create",
                    data={"phone": "0700 12 34 56", "kind": "call", "scheduled_date": today,
                          "scheduled_time": "15:00", "comment": "визовый вопрос"},
                    follow_redirects=False)
    assert r.status_code == 303
    tasks = _domain_tasks(sm)
    assert len(tasks) == 1
    assert tasks[0].user_id == USER_ID          # номер сматчен с живым диалогом
    assert tasks[0].comment == "визовый вопрос" and tasks[0].manager_id == "admin"


def test_calendar_action_rejects_foreign_task(tmp_path, monkeypatch):
    """Чужую задачу нельзя закрыть даже прямым POST-ом."""
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="medina", name="Медина", password="pw"),
        ManagerConfig(login="eliza", name="Элиза", password="pw"),
    ], raising=False)
    _seed_conv(bot_id="getvisa")
    medina = TestClient(main.app, base_url="https://testserver")
    medina.post("/admin/login", data={"login": "medina", "password": "pw"})
    task_id = _create_task(medina, sm, comment="медина-задача")

    eliza = TestClient(main.app, base_url="https://testserver")
    eliza.post("/admin/login", data={"login": "eliza", "password": "pw"})
    eliza.post(f"/admin/calendar/task/{task_id}/complete", data={"view": "day"})
    assert _domain_tasks(sm)[0].status == "planned"        # не тронута


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
