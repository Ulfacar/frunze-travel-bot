"""Замена Bitrix: «Новый клиент» вручную, заметки менеджера, карточка клиента.

Права — CRITICAL-зона: кроме счастливого пути здесь чужой менеджер, чужое направление,
подмена бота/воронки в форме, двойная отправка, протухшая форма и флаги OFF.
Все номера синтетические (996555…).
"""
import asyncio
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.admin.clients as clients
import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.core import flags
from app.core.state import get_state_store
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

MANAGERS = [
    ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
    ManagerConfig(login="medina", name="Медина", password="m1"),
    ManagerConfig(login="eliza", name="Элиза", password="e1"),
    ManagerConfig(login="aisina", name="Айсина", password="a1"),
]
PASSWORDS = {"admin": "frunze", "medina": "m1", "eliza": "e1", "aisina": "a1"}
PHONE = "996555123456"
VISA_UID = f"getvisa:{PHONE}"


def _sm(path):
    url = f"sqlite+aiosqlite:///{path.as_posix()}"

    async def _init(meta_tables):
        eng = create_async_engine(url)
        async with eng.begin() as conn:
            await conn.run_sync(meta_tables)
        await eng.dispose()
    return url, _init


@pytest.fixture
def env(tmp_path, monkeypatch):
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    flags.reset()
    admin_router._look_cache["at"] = 0.0
    admin_router._look_cache["key"] = None
    monkeypatch.setattr(app.config.settings, "managers", MANAGERS)
    # Как на проде: новый вид и новый чат включены (пункт меню и заметки живут там).
    monkeypatch.setattr(app.config.settings, "admin_new_look_enabled", True)
    monkeypatch.setattr(app.config.settings, "admin_chat_redesign_enabled", True)

    notes_url, init_notes = _sm(tmp_path / "notes.db")
    asyncio.run(init_notes(lambda c: clients.Base.metadata.create_all(
        c, tables=[clients.ClientNote.__table__, clients.ClientIntakeReceipt.__table__])))
    notes_sm = async_sessionmaker(create_async_engine(notes_url, poolclass=NullPool),
                                  expire_on_commit=False)
    monkeypatch.setattr(clients, "_sm", lambda: notes_sm)

    dom_url, init_dom = _sm(tmp_path / "domain.db")
    from app.domain.models import DomainBase
    asyncio.run(init_dom(DomainBase.metadata.create_all))
    dom_sm = async_sessionmaker(create_async_engine(dom_url, poolclass=NullPool),
                                expire_on_commit=False)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: dom_sm)

    # Ни одного обращения к каналу: заметки и ручной клиент ничего не отправляют.
    async def _no_send(*a, **k):
        raise AssertionError("клиенту ничего не должно уходить")
    monkeypatch.setattr(admin_router.outbound, "send_to_client", _no_send)
    yield {"notes_sm": notes_sm, "dom_sm": dom_sm}
    flags.reset()
    admin_router._look_cache["key"] = None


def _on(*keys):
    for key in keys:
        asyncio.run(flags.set_flag(key, True))
    admin_router._look_cache["key"] = None


def _client(login):
    c = TestClient(main.app, base_url="https://testserver")
    r = c.post("/admin/login", data={"login": login, "password": PASSWORDS[login]})
    assert r.status_code == 200
    return c


def _form(c):
    html = c.get("/admin/clients/new").text
    vals = dict(re.findall(r'name="(request_key|signature|csrf_token)" value="([^"]*)"', html))
    assert len(vals) == 3, html[:500]
    return vals


def _seed(uid, *, bot="getvisa", funnel="visa", owner="", phone=PHONE, name="Тест"):
    store = get_conversation_store()

    async def _s():
        await store.add_message(uid, "client", "здравствуйте", channel="whatsapp",
                                bot_id=bot, phone=phone, chat_id=f"{phone}@c.us")
        await store.update_meta(uid, funnel=funnel, assigned_to=owner,
                                qualification={"name": name})
    asyncio.run(_s())


def _count(sm, model):
    async def _q():
        async with sm() as s:
            return await s.scalar(select(func.count()).select_from(model))
    return asyncio.run(_q())


def _audit(action):
    return [a for a in panel_store._memory_store._audit if a.get("action") == action]


def _conv(uid):
    return asyncio.run(get_conversation_store().get(uid))


# ------------------------------ флаги OFF ------------------------------

def test_everything_hidden_when_flags_off(env):
    _seed(VISA_UID)
    c = _client("medina")
    assert c.get("/admin/clients/new").status_code == 404
    assert c.post("/admin/clients/new", data={"name": "x"}).status_code == 404
    assert c.get(f"/admin/client/{PHONE}").status_code == 404
    assert c.post(f"/admin/conversation/{VISA_UID}/notes",
                  data={"note": "x", "note_key": "a" * 32}).status_code == 404
    chat = c.get(f"/admin/conversation/{VISA_UID}").text
    assert "chat-notes-" not in chat
    assert "/admin/clients/new" not in c.get("/admin/calendar").text


# --------------------------- новый клиент ---------------------------

def test_visa_manager_creates_client_from_call(env):
    _on(clients.MANUAL_FLAG, clients.CARD_FLAG)
    c = _client("medina")
    assert "/admin/clients/new" in c.get("/admin/calendar").text   # пункт меню виден
    vals = _form(c)
    r = c.post("/admin/clients/new", data=dict(vals, name="Асель", phone="0555 123 456",
                                                source="call", bot_id="getvisa", funnel="visa",
                                                note="Шенген, перезвонить завтра"),
               follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin?open=getvisa%3A996555123456"
    conv = _conv(VISA_UID)
    assert conv is not None
    assert (conv.channel, conv.bot_id, conv.chat_id, conv.funnel) == (
        "whatsapp", "getvisa", f"{PHONE}@c.us", "visa")
    assert conv.assigned_to == "medina" and conv.intercepted is True
    assert conv.stage == "manager" and conv.qualification == {"name": "Асель"}
    assert conv.source == ""            # не «пост»: источник ручного клиента — в квитанции
    assert asyncio.run(get_state_store().load(VISA_UID)).intercepted is True  # бот молчит
    assert len(_audit("manual_lead")) == 1
    assert _count(env["notes_sm"], clients.ClientNote) == 1
    card = c.get(f"/admin/client/{PHONE}").text
    assert "Асель" in card and "вручную: Позвонил" in card and "Шенген, перезвонить" in card


def test_double_submit_creates_one_client_one_note(env):
    _on(clients.MANUAL_FLAG)
    c = _client("medina")
    data = dict(_form(c), name="Асель", phone="+996 555 123 456", source="office",
                bot_id="getvisa", funnel="visa", note="пришла в офис")
    first = c.post("/admin/clients/new", data=data, follow_redirects=False)
    second = c.post("/admin/clients/new", data=data, follow_redirects=False)
    assert first.status_code == second.status_code == 303
    assert first.headers["location"] == second.headers["location"]
    assert len(panel_store._memory_store._conv) == 1
    assert len(_audit("manual_lead")) == 1
    assert _count(env["notes_sm"], clients.ClientNote) == 1
    assert _count(env["notes_sm"], clients.ClientIntakeReceipt) == 1


def test_same_form_key_with_other_data_is_conflict(env):
    _on(clients.MANUAL_FLAG)
    c = _client("medina")
    data = dict(_form(c), name="Асель", phone="0555123456", source="call",
                bot_id="getvisa", funnel="visa")
    assert c.post("/admin/clients/new", data=data, follow_redirects=False).status_code == 303
    r = c.post("/admin/clients/new", data=dict(data, name="Другое имя"), follow_redirects=False)
    assert r.status_code == 409
    assert _conv(VISA_UID).qualification == {"name": "Асель"}


def test_form_key_of_other_manager_is_rejected(env):
    _on(clients.MANUAL_FLAG)
    vals = _form(_client("eliza"))                # подпись привязана к Элизе и её сессии
    r = _client("medina").post("/admin/clients/new", data=dict(
        vals, name="X", phone="0555123456", source="call", bot_id="getvisa", funnel="visa"))
    assert r.status_code == 403
    assert _conv(VISA_UID) is None


def test_tampered_signature_or_csrf_rejected(env):
    _on(clients.MANUAL_FLAG)
    c = _client("medina")
    base = dict(_form(c), name="X", phone="0555123456", source="call",
                bot_id="getvisa", funnel="visa")
    assert c.post("/admin/clients/new", data=dict(base, signature="0" * 64)).status_code == 403
    assert c.post("/admin/clients/new", data=dict(base, csrf_token="bad")).status_code == 403
    assert c.post("/admin/clients/new", data=dict(base, extra="1")).status_code == 422
    assert _conv(VISA_UID) is None


@pytest.mark.parametrize("bot_id,funnel", [
    ("frunze_tours_sezim", "tours"),     # чужой номер (туры)
    ("frunze_tours", "tours"),
    ("getvisa", "tours"),                # свой номер, чужая воронка
    ("getvisa", "tickets"),
    ("unknown_bot", "visa"),
])
def test_visa_manager_cannot_create_in_foreign_direction(env, bot_id, funnel):
    _on(clients.MANUAL_FLAG)
    c = _client("medina")
    r = c.post("/admin/clients/new", data=dict(_form(c), name="X", phone="0555123456",
                                                source="call", bot_id=bot_id, funnel=funnel))
    assert r.status_code == 403
    assert len(panel_store._memory_store._conv) == 0


def test_tours_manager_sees_only_her_number(env):
    _on(clients.MANUAL_FLAG)
    c = _client("aisina")
    html = c.get("/admin/clients/new").text
    assert 'value="frunze_tours_sezim"' in html and 'value="getvisa"' not in html
    r = c.post("/admin/clients/new", data=dict(_form(c), name="Бакыт", phone="0555 777 888",
                                                source="instagram", bot_id="frunze_tours_sezim",
                                                funnel="tickets"), follow_redirects=False)
    assert r.status_code == 303
    conv = _conv("frunze_tours_sezim:996555777888")
    assert conv.funnel == "tickets" and conv.assigned_to == "aisina"
    r = c.post("/admin/clients/new", data=dict(_form(c), name="X", phone="0555 777 889",
                                                source="call", bot_id="getvisa", funnel="visa"))
    assert r.status_code == 403


def test_existing_number_is_not_taken_over(env):
    _on(clients.MANUAL_FLAG, clients.CARD_FLAG)
    _seed(VISA_UID, owner="eliza", name="Клиент Элизы")
    c = _client("medina")
    r = c.post("/admin/clients/new", data=dict(_form(c), name="Новое имя", phone="0555123456",
                                                source="call", bot_id="getvisa", funnel="visa",
                                                note="звонил ещё раз"))
    assert r.status_code == 200 and r.headers["X-Action-Outcome"] == "existing"
    assert "уже есть" in r.text and "ведёт Элиза" in r.text
    conv = _conv(VISA_UID)
    assert conv.assigned_to == "eliza" and conv.intercepted is False
    assert conv.qualification == {"name": "Клиент Элизы"}
    assert _count(env["notes_sm"], clients.ClientNote) == 1
    assert not _audit("manual_lead")


def test_invalid_input_keeps_form(env):
    _on(clients.MANUAL_FLAG)
    c = _client("medina")
    vals = _form(c)
    r = c.post("/admin/clients/new", data=dict(vals, name="Асель", phone="12345",
                                                source="call", bot_id="getvisa", funnel="visa"))
    assert r.status_code == 422 and "Номер не распознан" in r.text and 'value="Асель"' in r.text
    r = c.post("/admin/clients/new", data=dict(vals, name="", phone="0555123456",
                                                source="call", bot_id="getvisa", funnel="visa"))
    assert r.status_code == 422
    r = c.post("/admin/clients/new", data=dict(vals, name="A", phone="0555123456",
                                                source="telegram", bot_id="getvisa", funnel="visa"))
    assert r.status_code == 422
    assert len(panel_store._memory_store._conv) == 0


def test_domain_owner_blocks_manual_claim(env):
    """По этому человеку в визах уже есть владелец (учёт назначений) — не отнимаем."""
    _on(clients.MANUAL_FLAG, "authz_enforce_enabled")

    async def _assign():
        from app.domain import live_assign
        async with env["dom_sm"]() as s:
            contact = await live_assign.contact_for_channel(s, channel="whatsapp", raw=PHONE)
            await live_assign.assign_locked(s, contact.id, "visa", "eliza",
                                            assigned_by="admin", reason="test")
            await s.commit()
    asyncio.run(_assign())
    c = _client("medina")
    r = c.post("/admin/clients/new", data=dict(_form(c), name="X", phone="0555123456",
                                                source="call", bot_id="getvisa", funnel="visa"))
    assert r.status_code == 409 and "eliza" in r.text   # текст сторожа владения — с логином
    assert _conv(VISA_UID) is None


# ------------------------------ заметки ------------------------------

def _note_key(html):
    m = re.search(r'name="note_key" value="([0-9a-f]{32})"', html)
    assert m, "нет формы заметки"
    return m.group(1), re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_note_saved_shown_and_double_submit_ignored(env):
    _on(clients.CARD_FLAG)
    _seed(VISA_UID)
    c = _client("medina")
    key, csrf = _note_key(c.get(f"/admin/conversation/{VISA_UID}").text)
    data = {"note": "Клиент просит без звонков", "note_key": key, "csrf_token": csrf}
    r1 = c.post(f"/admin/conversation/{VISA_UID}/notes", data=data)
    r2 = c.post(f"/admin/conversation/{VISA_UID}/notes", data=data)
    assert r1.status_code == r2.status_code == 200
    assert "Клиент просит без звонков" in r1.text
    assert _count(env["notes_sm"], clients.ClientNote) == 1
    assert len(_audit("note")) == 1
    assert not get_conversation_store()._conv[VISA_UID].messages[1:]   # клиенту ничего


def test_note_from_foreign_direction_is_404(env):
    _on(clients.CARD_FLAG, clients.MANUAL_FLAG)
    _seed(VISA_UID)
    tours = _client("aisina")
    csrf = _form(tours)["csrf_token"]          # настоящий CSRF её собственной сессии
    r = tours.post(f"/admin/conversation/{VISA_UID}/notes",
                   data={"note": "чужая", "note_key": "b" * 32, "csrf_token": csrf})
    assert r.status_code == 404
    assert tours.get(f"/admin/conversation/{VISA_UID}").status_code == 404
    assert _count(env["notes_sm"], clients.ClientNote) == 0


def test_note_needs_csrf_and_text(env):
    _on(clients.CARD_FLAG)
    _seed(VISA_UID)
    c = _client("medina")
    key, csrf = _note_key(c.get(f"/admin/conversation/{VISA_UID}").text)
    url = f"/admin/conversation/{VISA_UID}/notes"
    assert c.post(url, data={"note": "x", "note_key": key, "csrf_token": "bad"}).status_code == 403
    assert c.post(url, data={"note": "x", "note_key": "zz", "csrf_token": csrf}).status_code == 422
    r = c.post(url, data={"note": "   ", "note_key": key, "csrf_token": csrf})
    assert r.headers["X-Action-Outcome"] == "failed"
    r = c.post(url, data={"note": "я" * 2001, "note_key": key, "csrf_token": csrf})
    assert r.headers["X-Action-Outcome"] == "failed"
    assert _count(env["notes_sm"], clients.ClientNote) == 0


def test_note_field_is_not_the_reply_field(env):
    """Скрипты чата ищут поле ответа по `form.composer textarea[name="text"]`."""
    _on(clients.CARD_FLAG)
    _seed(VISA_UID)
    html = _client("medina").get(f"/admin/conversation/{VISA_UID}").text
    notes = html[html.index("chat-notes-"):html.index("chat-composer")]
    assert 'name="text"' not in notes and 'name="note"' in notes
    assert html.index("chat-notes-") < html.index('id="composer-')


# ---------------------------- карточка клиента ----------------------------

def test_card_shows_only_own_direction(env):
    _on(clients.CARD_FLAG)
    tours_uid = f"frunze_tours_sezim:{PHONE}"
    _seed(VISA_UID, name="Асель")
    _seed(tours_uid, bot="frunze_tours_sezim", funnel="tours", owner="aisina", name="Асель")
    asyncio.run(clients._insert_note(_conv(tours_uid), "aisina", "туровая тайна", "note:t1"))
    asyncio.run(clients._insert_note(_conv(VISA_UID), "medina", "визовая заметка", "note:v1"))

    visa = _client("medina").get(f"/admin/client/{PHONE}")
    assert visa.status_code == 200
    assert "визовая заметка" in visa.text and "туровая тайна" not in visa.text
    assert "frunze_tours_sezim" not in visa.text and "Обращения (1)" in visa.text

    admin = _client("admin").get(f"/admin/client/{PHONE}")
    assert "Обращения (2)" in admin.text and "туровая тайна" in admin.text


def test_card_of_foreign_number_is_404(env):
    _on(clients.CARD_FLAG)
    _seed(VISA_UID)
    assert _client("aisina").get(f"/admin/client/{PHONE}").status_code == 404
    assert _client("medina").get("/admin/client/996555000000").status_code == 404
    assert _client("medina").get("/admin/client/abc").status_code == 404


def test_card_shows_reassign_history(env):
    _on(clients.CARD_FLAG)
    _seed(VISA_UID, owner="medina")
    admin = _client("admin")
    r = admin.post(f"/admin/conversation/{VISA_UID}/reassign", data={"target": "eliza"})
    assert r.status_code == 200
    card = _client("eliza").get(f"/admin/client/{PHONE}").text
    assert "Админ передал(а) → Элиза" in card
    assert "Элиза · Визы" in card and "сейчас" in card       # учёт назначений


def test_card_includes_archived_dialogs(env):
    _on(clients.CARD_FLAG)
    _seed(VISA_UID, name="Асель")
    asyncio.run(get_conversation_store().set_archived(VISA_UID, True))
    card = _client("medina").get(f"/admin/client/{PHONE}")
    assert card.status_code == 200 and "в архиве" in card.text


def test_retry_after_partial_failure_finishes_own_card(env, monkeypatch):
    """Сбой после создания строки диалога: повтор той же формы доводит карточку,
    а не показывает её как «номер уже есть»."""
    _on(clients.MANUAL_FLAG)
    c = _client("medina")
    data = dict(_form(c), name="Асель", phone="0555123456", source="call",
                bot_id="getvisa", funnel="visa")
    real = admin_router._set_intercept
    calls = {"n": 0}

    async def flaky(uid, value):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("redis моргнул")
        await real(uid, value)
    monkeypatch.setattr(admin_router, "_set_intercept", flaky)
    with pytest.raises(RuntimeError):
        c.post("/admin/clients/new", data=data, follow_redirects=False)
    r = c.post("/admin/clients/new", data=data, follow_redirects=False)
    assert r.status_code == 303
    conv = _conv(VISA_UID)
    assert conv.assigned_to == "medina" and conv.intercepted is True
    assert len(_audit("manual_lead")) == 1 and not _audit("manual_lead_existing")
