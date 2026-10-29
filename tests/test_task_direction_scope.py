"""Направление задачи задаёт сервер, а не форма (CRITICAL, найдено 30.10).

До правки `POST /conversation/{id}/task/create` брал `direction` из формы как есть:
менеджер виз ставил визовому клиенту задачу «туры». Последствия видны здесь же:
утренняя сводка владельца считала её в строке «Туры», а перенос задач при передаче
клиента (по направлению) её не находил. Мусорное значение молча терялось: 200, задачи нет.
"""
import asyncio
from datetime import date, timedelta

import pytest
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

MANAGERS = [
    ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
    ManagerConfig(login="medina", name="Медина", password="m1"),
    ManagerConfig(login="aisina", name="Айсина", password="a1"),
]
PASSWORDS = {"admin": "frunze", "medina": "m1", "aisina": "a1"}
VISA = "getvisa:996555444001"
TOURS = "frunze_tours_sezim:996555444002"
TICKETS = "frunze_tours_sezim:996555444003"
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


@pytest.fixture
def sm(tmp_path, monkeypatch):
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    flags.reset()
    monkeypatch.setattr(app.config.settings, "managers", MANAGERS)
    url = f"sqlite+aiosqlite:///{(tmp_path / 'd.db').as_posix()}"

    async def _init():
        eng = create_async_engine(url)
        async with eng.begin() as conn:
            from app.domain.models import DomainBase
            await conn.run_sync(DomainBase.metadata.create_all)
        await eng.dispose()
    asyncio.run(_init())
    maker = async_sessionmaker(create_async_engine(url, poolclass=NullPool), expire_on_commit=False)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: maker)
    store = get_conversation_store()

    async def _seed():
        for uid, bot, funnel in ((VISA, "getvisa", "visa"), (TOURS, "frunze_tours_sezim", "tours"),
                                 (TICKETS, "frunze_tours_sezim", "tickets")):
            phone = uid.split(":")[1]
            await store.add_message(uid, "client", "вопрос", channel="whatsapp", bot_id=bot,
                                    phone=phone, chat_id=f"{phone}@c.us")
            await store.update_meta(uid, funnel=funnel)
    asyncio.run(_seed())
    yield maker
    flags.reset()


def _client(login):
    c = TestClient(main.app, base_url="https://testserver")
    assert c.post("/admin/login", data={"login": login, "password": PASSWORDS[login]}).status_code == 200
    return c


def _create(c, uid, **extra):
    data = {"kind": "call", "scheduled_date": TOMORROW, "comment": "перезвонить"}
    data.update(extra)
    return c.post(f"/admin/conversation/{uid}/task/create", data=data)


def _tasks(maker):
    async def _q():
        from app.domain.models import CalendarTask
        async with maker() as s:
            return [(t.user_id, t.direction, t.manager_id)
                    for t in (await s.scalars(select(CalendarTask).order_by(CalendarTask.id))).all()]
    return asyncio.run(_q())


# ---- воспроизведение: чужое направление и мусор ----

@pytest.mark.parametrize("forged", ["tours", "tickets"])
def test_visa_manager_cannot_put_foreign_direction(sm, forged):
    r = _create(_client("medina"), VISA, direction=forged)
    assert r.status_code == 403
    assert _tasks(sm) == []


@pytest.mark.parametrize("junk", ["xxx", "VISA ", "visa;drop", "../tours"])
def test_junk_direction_is_an_explicit_error_not_silent_loss(sm, junk):
    r = _create(_client("medina"), VISA, direction=junk)
    assert r.status_code == 422
    assert _tasks(sm) == []


def test_admin_cannot_mix_teams_either(sm):
    """Полный админ тоже не ставит визовому клиенту туровую задачу: направление
    клиента определяет его диалог, а не тот, кто нажал кнопку."""
    assert _create(_client("admin"), VISA, direction="tours").status_code == 403
    assert _tasks(sm) == []


# ---- что разрешено ----

def test_no_direction_in_form_takes_conversation_funnel(sm):
    """Форма в шаблоне поле не шлёт — направление берётся с сервера."""
    assert _create(_client("medina"), VISA).status_code == 200
    assert _create(_client("aisina"), TICKETS).status_code == 200
    assert _tasks(sm) == [(VISA, "visa", "medina"), (TICKETS, "tickets", "aisina")]


def test_matching_direction_accepted(sm):
    assert _create(_client("medina"), VISA, direction="visa").status_code == 200
    assert _tasks(sm) == [(VISA, "visa", "medina")]


def test_tours_team_may_mark_tickets_and_tours(sm):
    """Билеты ведёт команда туров: внутри туровой команды выбор допустим."""
    c = _client("aisina")
    assert _create(c, TOURS, direction="tickets").status_code == 200
    assert _create(c, TICKETS, direction="tours").status_code == 200
    assert _create(c, TOURS, direction="visa").status_code == 403
    assert [d for _, d, _ in _tasks(sm)] == ["tickets", "tours"]


def test_foreign_conversation_is_404_before_any_direction_check(sm):
    assert _create(_client("aisina"), VISA, direction="tours").status_code == 404
    assert _create(_client("medina"), TOURS).status_code == 404
    assert _tasks(sm) == []


# ---- последствие, ради которого это CRITICAL: сводка владельца ----

def test_owner_digest_counts_visa_task_under_visa(sm):
    _create(_client("medina"), VISA, direction="tours")       # отклонено
    _create(_client("medina"), VISA)                           # принято

    async def _rows():
        from app.core.calendar_brief import build_owner_digest
        from app.domain.models import CalendarTask
        async with sm() as s:
            tasks = (await s.scalars(select(CalendarTask))).all()
        return build_owner_digest([], tasks, lookback_hours=12, day=date.today())
    digest = asyncio.run(_rows())
    by_key = {d["key"]: d for d in digest["directions"]}
    assert set(by_key) == {"visa"}
    assert by_key["visa"]["by_manager"] == [("medina", 1)]


# ---- соседние эндпоинты задач: тот же класс ошибки ----

def test_calendar_quick_create_ignores_form_direction(sm):
    """Быстрая задача из календаря поля direction не принимает вовсе: направление —
    по найденному диалогу или по направлению менеджера."""
    c = _client("medina")
    r = c.post("/admin/calendar/task/create", data={
        "phone": "0555444001", "kind": "call", "scheduled_date": TOMORROW,
        "direction": "tours"}, follow_redirects=False)
    assert r.status_code in (200, 303)
    assert _tasks(sm) == [(VISA, "visa", "medina")]


def test_calendar_quick_create_does_not_link_foreign_dialog(sm):
    """Номер чужого направления: задача заводится, но к туровому диалогу не привязывается
    и получает направление менеджера."""
    c = _client("medina")
    c.post("/admin/calendar/task/create", data={
        "phone": "0555444002", "kind": "call", "scheduled_date": TOMORROW},
        follow_redirects=False)
    assert _tasks(sm) == [("", "visa", "medina")]


def test_other_manager_cannot_touch_task_from_calendar_or_chat(sm):
    _create(_client("medina"), VISA)
    task_id = 1
    aisina = _client("aisina")
    for path in (f"/admin/calendar/task/{task_id}/complete",
                 f"/admin/calendar/task/{task_id}/cancel",
                 f"/admin/calendar/task/{task_id}/snooze"):
        aisina.post(path, data={"mode": "h2"}, follow_redirects=False)
    aisina.post(f"/admin/calendar/task/{task_id}/reschedule",
                data={"scheduled_date": TOMORROW}, follow_redirects=False)
    assert aisina.post(f"/admin/conversation/{VISA}/task/{task_id}/complete").status_code == 404

    async def _status():
        from app.domain.models import CalendarTask
        async with sm() as s:
            t = await s.get(CalendarTask, task_id)
            return t.status, t.scheduled_date.isoformat()
    assert asyncio.run(_status()) == ("planned", TOMORROW)
