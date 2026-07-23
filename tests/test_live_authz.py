"""Sprint 2: живое владение лидом в админке (флаг authz_enforce_enabled).

Endpoint-уровень через TestClient (паттерн test_calendar_admin): доменная БД —
временный SQLite через _domain_sessionmaker, панель — in-memory store.
"""
import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.core import live_authz
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

USER_ID = "getvisa:996700123456"

MANAGERS = [
    ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
    ManagerConfig(login="medina", name="Медина", password="m1"),
    ManagerConfig(login="eliza", name="Элиза", password="e1"),
]


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
    eng = create_async_engine(url, poolclass=NullPool)
    return async_sessionmaker(eng, expire_on_commit=False)


def _seed_conv(bot_id="getvisa", funnel="visa"):
    store = get_conversation_store()

    async def _s():
        await store.add_message(USER_ID, "client", "нужна виза", channel="whatsapp",
                                bot_id=bot_id, phone="996700123456")
        await store.update_meta(USER_ID, funnel=funnel)
    asyncio.run(_s())


def _client(login: str, password: str) -> TestClient:
    client = TestClient(main.app, base_url="https://testserver")
    r = client.post("/admin/login", data={"login": login, "password": password})
    assert r.status_code == 200
    return client


def _setup(tmp_path, monkeypatch, *, enforce: bool):
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    monkeypatch.setattr(app.config.settings, "managers", MANAGERS)
    if enforce:
        from app.core import flags
        asyncio.run(flags.set_flag("authz_enforce_enabled", True))
    _seed_conv()
    return sm


def _assignments(sm):
    async def _q():
        from app.domain.models import Assignment
        async with sm() as s:
            return (await s.scalars(select(Assignment).order_by(Assignment.id))).all()
    return asyncio.run(_q())


def _conv():
    return asyncio.run(get_conversation_store().get(USER_ID))


# ---------------- actor_for ----------------

def test_actor_admin_is_full_admin(monkeypatch):
    monkeypatch.setattr(app.config.settings, "managers", MANAGERS)
    actor = live_authz.actor_for({"login": "admin", "name": "Админ", "admin": True})
    assert actor.is_full_admin


def test_actor_visa_manager_gets_visa_direction():
    actor = live_authz.actor_for({"login": "medina", "name": "Медина"})
    assert not actor.is_full_admin
    assert actor.allowed_directions == frozenset({"visa"})


def test_actor_tours_manager_gets_tours_direction():
    actor = live_authz.actor_for({"login": "ademi", "name": "Адеми"})
    assert actor.allowed_directions == frozenset({"tours"})


def test_actor_unknown_login_fail_closed():
    actor = live_authz.actor_for({"login": "stranger", "name": "Кто-то"})
    assert not actor.is_full_admin and actor.allowed_directions == frozenset()


# ---------------- flag OFF: легаси-поведение ----------------

def test_flag_off_peer_takeover_still_allowed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=False)
    asyncio.run(get_conversation_store().update_meta(USER_ID, assigned_to="medina"))
    r = _client("eliza", "e1").post(f"/admin/conversation/{USER_ID}/takeover")
    assert r.status_code == 200
    assert _conv().assigned_to == "eliza"          # перехват прошёл, как раньше


# ---------------- flag ON: enforcement ----------------

def test_enforced_claim_of_unassigned_writes_domain_assignment(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch, enforce=True)
    r = _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    assert r.status_code == 200
    assert _conv().assigned_to == "medina"
    rows = _assignments(sm)
    assert len(rows) == 1 and rows[0].manager_id == "medina"
    assert rows[0].active and rows[0].direction == "visa" and rows[0].reason == "takeover"


def test_enforced_peer_takeover_blocked(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch, enforce=True)
    _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    r = _client("eliza", "e1").post(f"/admin/conversation/{USER_ID}/takeover")
    assert r.status_code == 200
    assert "Перехват запрещён" in r.text
    assert _conv().assigned_to == "medina"         # владелец не сменился
    rows = _assignments(sm)
    assert len(rows) == 1 and rows[0].manager_id == "medina"


def test_enforced_peer_send_blocked_message_not_sent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    before = len(_conv().messages)
    r = _client("eliza", "e1").post(f"/admin/conversation/{USER_ID}/send",
                                    data={"text": "здравствуйте!"})
    assert r.status_code == 200 and "Перехват запрещён" in r.text
    assert len(_conv().messages) == before         # реплика клиенту НЕ ушла и не залогирована


def test_enforced_send_to_unassigned_auto_claims(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch, enforce=True)
    r = _client("eliza", "e1").post(f"/admin/conversation/{USER_ID}/send",
                                    data={"text": "чем помочь?"})
    assert r.status_code == 200
    assert _conv().assigned_to == "eliza"          # ничей → закрепился за ответившим
    rows = _assignments(sm)
    assert len(rows) == 1 and rows[0].manager_id == "eliza"
    assert rows[0].reason == "auto_claim_on_send"


def test_enforced_admin_send_to_owned_requires_reassign(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    r = _client("admin", "frunze").post(f"/admin/conversation/{USER_ID}/send",
                                        data={"text": "я админ"})
    assert r.status_code == 200 and "Переназначить" in r.text
    assert _conv().assigned_to == "medina"


def test_enforced_release_by_owner_ends_assignment(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch, enforce=True)
    client = _client("medina", "m1")
    client.post(f"/admin/conversation/{USER_ID}/takeover")
    r = client.post(f"/admin/conversation/{USER_ID}/release")
    assert r.status_code == 200
    rows = _assignments(sm)
    assert len(rows) == 1 and not rows[0].active and rows[0].ended_at is not None


def test_enforced_release_by_peer_blocked(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch, enforce=True)
    _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    r = _client("eliza", "e1").post(f"/admin/conversation/{USER_ID}/release")
    assert r.status_code == 200 and "вернуть боту может" in r.text
    assert _assignments(sm)[0].active


def test_enforced_legacy_panel_owner_respected(tmp_path, monkeypatch):
    """До-доменный клейм (assigned_to в панели, домена нет) защищает лид от соседа."""
    sm = _setup(tmp_path, monkeypatch, enforce=True)
    asyncio.run(get_conversation_store().update_meta(USER_ID, assigned_to="medina"))
    r = _client("eliza", "e1").post(f"/admin/conversation/{USER_ID}/send",
                                    data={"text": "привет"})
    assert "Перехват запрещён" in r.text
    assert _assignments(sm) == []                  # домен не трогали


def test_enforced_reclaim_by_owner_does_not_churn_history(tmp_path, monkeypatch):
    """Повторный перехват своим же владельцем не плодит новые ревизии Assignment."""
    sm = _setup(tmp_path, monkeypatch, enforce=True)
    client = _client("medina", "m1")
    client.post(f"/admin/conversation/{USER_ID}/takeover")
    client.post(f"/admin/conversation/{USER_ID}/takeover")
    rows = _assignments(sm)
    assert len(rows) == 1 and rows[0].active and rows[0].revision == 1


def test_enforced_race_loser_is_denied_not_fail_open(tmp_path, monkeypatch):
    """DomainError из-под лока (гонку выиграл другой) — честный отказ, не fail-open."""
    _setup(tmp_path, monkeypatch, enforce=True)
    from app.domain import live_assign
    from app.domain.models import DomainError

    async def _raise(*a, **kw):
        raise DomainError("cannot take over an owned contact")
    monkeypatch.setattr(live_assign, "assign_locked", _raise)
    r = _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    assert r.status_code == 200 and "только что взял" in r.text
    assert not _conv().assigned_to               # панель победителя не перезатёрта


def test_enforced_telegram_identity_not_treated_as_phone(tmp_path, monkeypatch):
    """Telegram from.id не гонится через normalize_phone (нет выдуманных 996-номеров)."""
    _clear()
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    monkeypatch.setattr(app.config.settings, "managers", MANAGERS)
    from app.core import flags
    asyncio.run(flags.set_flag("authz_enforce_enabled", True))
    tg_uid = "getvisa_tg:123456789"              # 9-значный telegram id
    store = get_conversation_store()

    async def _s():
        await store.add_message(tg_uid, "client", "нужна виза", channel="telegram",
                                bot_id="getvisa_tg", phone="123456789")
        await store.update_meta(tg_uid, funnel="visa")
    asyncio.run(_s())
    r = _client("medina", "m1").post(f"/admin/conversation/{tg_uid}/takeover")
    assert r.status_code == 200

    async def _identities():
        from app.domain.models import ContactIdentity
        async with sm() as s:
            return (await s.scalars(select(ContactIdentity))).all()
    idents = asyncio.run(_identities())
    assert len(idents) == 1
    assert idents[0].identity_type == "telegram"
    assert idents[0].normalized_value == "123456789"   # не 996123456789


# ---------------- reassign (полный админ) ----------------

def test_reassign_admin_transfers_ownership(tmp_path, monkeypatch):
    sm = _setup(tmp_path, monkeypatch, enforce=True)
    _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    r = _client("admin", "frunze").post(f"/admin/conversation/{USER_ID}/reassign",
                                        data={"target": "eliza"})
    assert r.status_code == 200 and "Лид передан" in r.text
    assert _conv().assigned_to == "eliza"
    rows = _assignments(sm)
    assert len(rows) == 2
    assert not rows[0].active and rows[1].active
    assert rows[1].manager_id == "eliza" and rows[1].reason == "admin_reassign"
    assert rows[1].revision == rows[0].revision + 1


def test_reassign_forbidden_for_scoped_manager(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    r = _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/reassign",
                                     data={"target": "eliza"})
    assert r.status_code == 403


def test_reassign_unknown_target_rejected(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    r = _client("admin", "frunze").post(f"/admin/conversation/{USER_ID}/reassign",
                                        data={"target": "hacker"})
    assert r.status_code == 400


def test_reassign_works_with_flag_off(tmp_path, monkeypatch):
    """Переназначение доступно админу и без enforcement (пишет домен + панель)."""
    sm = _setup(tmp_path, monkeypatch, enforce=False)
    r = _client("admin", "frunze").post(f"/admin/conversation/{USER_ID}/reassign",
                                        data={"target": "medina"})
    assert r.status_code == 200
    assert _conv().assigned_to == "medina"
    assert _assignments(sm)[0].manager_id == "medina"


# ---------------- фичефлаги: только полный админ ----------------

def test_feature_flag_toggle_forbidden_for_scoped_manager(monkeypatch):
    """Аудит-фикс HIGH: скоуп-менеджер не может дёргать фичефлаги даже прямым POST."""
    _clear()
    monkeypatch.setattr(app.config.settings, "managers", MANAGERS)
    r = _client("medina", "m1").post("/admin/flags/authz_enforce_enabled",
                                     data={"on": "0"})
    assert r.status_code == 403
    from app.core import flags
    assert asyncio.run(flags.get_flag("authz_enforce_enabled", False)) is False


def test_feature_flag_toggle_allowed_for_full_admin(monkeypatch):
    _clear()
    monkeypatch.setattr(app.config.settings, "managers", MANAGERS)
    r = _client("admin", "frunze").post("/admin/flags/authz_enforce_enabled",
                                        data={"on": "1"})
    assert r.status_code == 200
    from app.core import flags
    assert asyncio.run(flags.get_flag("authz_enforce_enabled", False)) is True


# ---------------- доска: фильтр «Мои лиды» ----------------

def test_board_mine_filter(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=False)
    asyncio.run(get_conversation_store().update_meta(USER_ID, assigned_to="medina"))
    client = _client("medina", "m1")
    all_board = client.get("/admin/board/visa").text
    mine = client.get("/admin/board/visa?mine=1").text
    assert "996700123456" in all_board and "996700123456" in mine
    other = _client("eliza", "e1").get("/admin/board/visa?mine=1").text
    assert "996700123456" not in other             # чужой лид в «моих» не виден
