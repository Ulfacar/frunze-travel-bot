"""ГЕЙТ (CRITICAL, права): доступ визового менеджера к въездной CRM по PDF.

Написан ДО реализации. Флаг `kg_entry_manager_access_enabled`, дефолт OFF.

До этой задачи все экраны `/admin/kg-entry/*` и `/admin/case/{id}/kg-entry/*` требовали
полного администратора: Медина, Элиза и Гриша получали 403 «admin only» (PM-ревью
30.10.2026). Здесь закреплено, что при флаге ON визовый менеджер входит в них **только
в пределах своего направления и своих услуг**, а туровый менеджер, чужая услуга,
прямой URL, POST без прав и админские действия (публикация знаний, решения по
единицам) остаются закрытыми — на сервере, не в шаблоне.

Доменный слой проверяется отдельно: `_authorize` принимает актора-оператора,
`_authorize_admin` — нет.
"""
import asyncio
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.admin.router as ar
import app.config
import app.main as main
from app.config import ManagerConfig
from app.domain.knowledge_import import create_kg_entry_set, import_bundle
from app.domain.permissions import Actor
from tests.test_admin_workday import _clear, _login, _make_domain_sm, _managers, _on, _seed_case
from tests.test_entry_storage import FIX

FLAG = "kg_entry_manager_access_enabled"
ADMIN = Actor("admin", True)
CATALOG_OK = ("/admin/kg-entry/answers", "/admin/kg-entry/knowledge", "/admin/kg-entry/templates",
              "/admin/kg-entry/processes", "/admin/kg-entry/documents")
CATALOG_ADMIN_ONLY = ("/admin/kg-entry/publication", "/admin/kg-entry/reviews")


@pytest.fixture
def env(monkeypatch, tmp_path):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    ar.settings.managers.append(ManagerConfig(login="medina", name="Медина", password="frunze"))
    ar.settings.managers.append(ManagerConfig(login="eliza", name="Элиза", password="frunze"))
    ar.settings.managers.append(ManagerConfig(login="aisina", name="Айсина", password="frunze"))
    monkeypatch.setattr(ar.settings, "admin_kg_entry_enabled", True)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(ar, "_domain_sessionmaker", lambda: sm)
    cases = {
        "mine": _seed_case(sm, owner="medina", reference="SYN-M", direction="visa")["case_id"],
        "foreign": _seed_case(sm, owner="eliza", reference="SYN-E", direction="visa")["case_id"],
        "tours": _seed_case(sm, owner="aisina", reference="SYN-T", direction="tours")["case_id"],
    }

    async def seed():
        set_id = await create_kg_entry_set(sm.kw["bind"], actor=ADMIN)
        imported = await import_bundle(sm.kw["bind"], actor=ADMIN, set_id=set_id,
                                       directory=FIX / "synthetic_bundle",
                                       source=FIX / "synthetic_source.txt")
        assert imported.accepted
    asyncio.run(seed())
    yield {"sm": sm, "cases": cases}
    asyncio.run(sm.kw["bind"].dispose()); _clear()


def _flag(monkeypatch, value: bool):
    monkeypatch.setattr(app.config.settings, FLAG, value, raising=False)


def _url(env, key):
    return f"/admin/case/{env['cases'][key]}/kg-entry"


# --- Флаг ----------------------------------------------------------------------

def test_flag_defaults_to_off():
    assert getattr(app.config.settings, FLAG) is False


def test_flag_is_registered_in_the_panel():
    assert FLAG in ar.FEATURE_FLAGS


# --- Флаг OFF: всё как сейчас ----------------------------------------------------

@pytest.mark.parametrize("path", CATALOG_OK + CATALOG_ADMIN_ONLY)
def test_flag_off_manager_still_denied_on_catalog(env, monkeypatch, path):
    _flag(monkeypatch, False)
    client = _login("medina")
    try:
        assert client.get(path).status_code == 403
    finally:
        client.close()


@pytest.mark.parametrize("method", ["get", "post"])
def test_flag_off_manager_still_denied_on_own_case(env, monkeypatch, method):
    _flag(monkeypatch, False)
    client = _login("medina")
    try:
        assert getattr(client, method)(_url(env, "mine")).status_code == 403
    finally:
        client.close()


def test_flag_off_admin_unchanged(env, monkeypatch):
    _flag(monkeypatch, False)
    client = _login("admin")
    try:
        assert client.get(_url(env, "mine")).status_code == 200
        assert client.get("/admin/kg-entry/publication").status_code == 200
    finally:
        client.close()


# --- Флаг ON: визовый менеджер в своём направлении ------------------------------

@pytest.mark.parametrize("path", CATALOG_OK)
def test_visa_manager_opens_catalog_screens(env, monkeypatch, path):
    _flag(monkeypatch, True)
    client = _login("medina")
    try:
        assert client.get(path).status_code == 200
    finally:
        client.close()


def test_visa_manager_opens_own_case_and_sub_screens(env, monkeypatch):
    _flag(monkeypatch, True)
    client = _login("medina")
    try:
        assert client.get(_url(env, "mine")).status_code == 200
        assert client.get(_url(env, "mine") + "/applications").status_code == 200
        assert client.get(_url(env, "mine") + "/history").status_code == 200
    finally:
        client.close()


def test_visa_manager_cannot_open_foreign_or_other_direction_case(env, monkeypatch):
    """Чужая услуга внутри направления и услуга другого направления — 404 (не раскрываем)."""
    _flag(monkeypatch, True)
    client = _login("medina")
    try:
        for key in ("foreign", "tours"):
            assert client.get(_url(env, key)).status_code == 404, key
            assert client.get(_url(env, key) + "/applications").status_code == 404, key
            assert client.post(_url(env, key), data={}).status_code in (403, 404), key
    finally:
        client.close()


@pytest.mark.parametrize("path", CATALOG_ADMIN_ONLY)
def test_visa_manager_denied_admin_only_screens(env, monkeypatch, path):
    _flag(monkeypatch, True)
    client = _login("medina")
    try:
        assert client.get(path).status_code == 403
        assert client.post(path, data={}).status_code == 403
    finally:
        client.close()


@pytest.mark.parametrize("path", CATALOG_OK + CATALOG_ADMIN_ONLY)
def test_tours_manager_denied_everywhere_with_flag_on(env, monkeypatch, path):
    _flag(monkeypatch, True)
    client = _login("aisina")
    try:
        assert client.get(path).status_code == 403
    finally:
        client.close()


@pytest.mark.parametrize("key", ["mine", "foreign", "tours"])
def test_tours_manager_denied_on_cases_before_domain(env, monkeypatch, key):
    _flag(monkeypatch, True)
    client = _login("aisina")

    def forbidden():
        raise AssertionError("domain must not be accessed")
    try:
        monkeypatch.setattr(ar, "_domain_sessionmaker", forbidden)
        assert client.get(_url(env, key)).status_code == 403
        assert client.post(_url(env, key), data={}).status_code == 403
    finally:
        client.close()


def test_anonymous_denied(env, monkeypatch):
    _flag(monkeypatch, True)
    client = TestClient(main.app, base_url="https://testserver")
    try:
        assert client.get(_url(env, "mine")).status_code == 401
        assert client.get("/admin/kg-entry/answers").status_code == 401
    finally:
        client.close()


def test_master_gate_still_wins(env, monkeypatch):
    """ADMIN_KG_ENTRY_ENABLED=false → 404 для всех, даже при включённом доступе менеджера."""
    _flag(monkeypatch, True)
    monkeypatch.setattr(ar.settings, "admin_kg_entry_enabled", False)
    client = _login("medina")
    try:
        assert client.get(_url(env, "mine")).status_code == 404
        assert client.get("/admin/kg-entry/answers").status_code == 404
    finally:
        client.close()


# --- Доменный слой --------------------------------------------------------------

def test_domain_operator_passes_work_gate_but_not_admin_gate():
    from app.domain.knowledge_import import _authorize, _authorize_admin
    from app.domain.service_authz import PermissionDenied
    operator = Actor("medina", False, frozenset({"visa"}), kg_entry_operator=True)
    plain = Actor("medina", False, frozenset({"visa"}))
    _authorize(operator)                      # работа по делу — можно
    with pytest.raises(PermissionDenied):
        _authorize(plain)                     # без признака оператора — как раньше
    with pytest.raises(PermissionDenied):
        _authorize_admin(operator)            # публикация/подписи — только админ
    _authorize_admin(ADMIN)


def test_operator_cannot_publish_or_decide(env, monkeypatch):
    from app.domain import knowledge_decisions, knowledge_publication
    from app.domain.service_authz import PermissionDenied
    operator = Actor("medina", False, frozenset({"visa"}), kg_entry_operator=True)
    engine = env["sm"].kw["bind"]
    with pytest.raises(PermissionDenied):
        asyncio.run(knowledge_decisions.review_catalog(engine, actor=operator))
    with pytest.raises(PermissionDenied):
        asyncio.run(knowledge_publication.publication_preview(
            engine, actor=operator, version_id=1, unit_ids=["KG.VF.TEST"]))


# --- Вход из чата: ссылка «Визовая заявка (КР)» ----------------------------------

@pytest.fixture
def chat_env(env, monkeypatch):
    from app.integrations.panel import store
    from app.domain.models import Contact, ContactIdentity, Product
    from app.domain.service_cases import sign_contract
    monkeypatch.setattr(ar.settings, "authz_enforce_enabled", False)
    monkeypatch.setattr(ar.settings, "panel_backend", "memory")
    uid = "getvisa:996555000777"
    conv = store.ConversationView(user_id=uid, phone="996555000777", channel="whatsapp",
                                  bot_id="getvisa", funnel="visa", assigned_to="medina",
                                  qualification={"name": "Demo", "entry_mode": "kg_entry",
                                                 "kg_entry": {"citizenship": "Индия"}})
    store._memory_store._conv[uid] = conv
    sm = env["sm"]

    async def seed():
        async with sm() as session:
            contact = Contact(); session.add(contact); await session.flush()
            session.add(ContactIdentity(contact_id=contact.id, identity_type="phone",
                                        normalized_value="996555000777", provider_scope=""))
            product = await session.scalar(select(Product).where(Product.direction == "visa"))
            case = await sign_contract(
                session, contact_id=contact.id, product_id=product.id, owner_login="medina",
                by=Actor("medina", False, frozenset({"visa"})), reference="SYN-CHAT",
                amount=Decimal("100.00"), currency="KGS", idempotency_key="chat-SYN")
            await session.commit()
            return case.id
    case_id = asyncio.run(seed())
    return {"uid": uid, "case_id": case_id, "conv": conv}


def test_chat_link_shown_to_owner_only_with_flag(chat_env, monkeypatch):
    label = "Визовая заявка (КР)"
    href = f"/admin/case/{chat_env['case_id']}/kg-entry"
    url = f"/admin/conversation/{chat_env['uid']}"
    _flag(monkeypatch, False)
    client = _login("medina")
    try:
        page = client.get(url); assert page.status_code == 200
        assert label not in page.text and href not in page.text
        _flag(monkeypatch, True)
        page = client.get(url); assert page.status_code == 200
        assert label in page.text and href in page.text
        # Ссылка ведёт на экран, который менеджер реально может открыть.
        assert client.get(href).status_code == 200
    finally:
        client.close()
    # Чужой визовый менеджер видит диалог направления, но не чужую услугу — без ссылки.
    other = _login("eliza")
    try:
        page = other.get(url)
        assert page.status_code == 200 and label not in page.text
    finally:
        other.close()


def test_chat_link_absent_for_outbound_visa_dialog(chat_env, monkeypatch):
    _flag(monkeypatch, True)
    chat_env["conv"].qualification = {"name": "Demo"}        # обычный выездной лид
    client = _login("medina")
    try:
        page = client.get(f"/admin/conversation/{chat_env['uid']}")
        assert page.status_code == 200 and "Визовая заявка (КР)" not in page.text
    finally:
        client.close()


def test_case_card_shows_entry_link_only_to_allowed(env, monkeypatch):
    link = f"/admin/case/{env['cases']['mine']}/kg-entry"
    _flag(monkeypatch, False)
    client = _login("medina")
    try:
        page = client.get(f"/admin/case/{env['cases']['mine']}")
        assert page.status_code == 200 and link not in page.text
        _flag(monkeypatch, True)
        page = client.get(f"/admin/case/{env['cases']['mine']}")
        assert page.status_code == 200 and link in page.text
    finally:
        client.close()
    admin = _login("admin")
    try:
        assert link in admin.get(f"/admin/case/{env['cases']['mine']}").text
    finally:
        admin.close()


def test_operator_cannot_create_knowledge_set_or_import_calendars(env):
    """Ревью потока bitrix 30.10: оператор создавал набор знаний. Обе точки — только админ."""
    from app.domain.entry_storage import import_work_calendars
    from app.domain.knowledge_import import create_kg_entry_set
    from app.domain.service_authz import PermissionDenied
    operator = Actor("medina", False, frozenset({"visa"}), kg_entry_operator=True)
    engine = env["sm"].kw["bind"]
    with pytest.raises(PermissionDenied):
        asyncio.run(create_kg_entry_set(engine, actor=operator))
    with pytest.raises(PermissionDenied):
        asyncio.run(import_work_calendars(engine, actor=operator, document={}))
