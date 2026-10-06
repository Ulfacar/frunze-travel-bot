"""CONTRACT-UI: HTTP → настоящий домен на синтетической SQLite.

Не подменяем sign_contract: проверяем контакты, события, задачи и откат после
ошибок. Доступ и CSRF проверяются прямыми запросами, а не наличием кнопки.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote

import pytest
from sqlalchemy import select

import app.admin.contracts as contracts
import app.admin.router as ar
import app.domain.service_cases as domain
from app.config import ManagerConfig
from app.domain.models import (
    Assignment, CalendarTask, Contact, ContactIdentity, Product, ServiceCase,
    ServiceEvent, ServicePayment,
)
from app.domain.service_authz import SYSTEM_ACTOR
from app.integrations.panel import store
from tests.test_admin_workday import Rendered, _clear, _login, _make_domain_sm, _managers, _on

UID = "frunze_tours:996555000111"
URL = f"/admin/conversation/{quote(UID, safe='')}/contract"


@pytest.fixture
def env(monkeypatch, tmp_path):
    _clear()
    _managers(monkeypatch)
    ar.settings.managers.append(ManagerConfig(login="medina", name="Медина", password="frunze"))
    ar.settings.managers.append(ManagerConfig(login="aisina", name="Айсина", password="frunze"))
    _on(monkeypatch)
    monkeypatch.setattr(ar.settings, "authz_enforce_enabled", False)
    monkeypatch.setattr(ar.settings, "panel_backend", "memory")
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(ar, "_domain_sessionmaker", lambda: sm)
    conv = store.ConversationView(user_id=UID, phone="996555000111", channel="whatsapp",
                                  bot_id="frunze_tours", funnel="tours", assigned_to="ademi",
                                  qualification={"name": "Тестовый клиент"},
                                  sale_amount=999, sale_currency="USD")
    store._memory_store._conv[UID] = conv

    async def seed():
        async with sm() as session:
            ids = {}
            for code, direction, published, active in (
                    ("tour", "tours", True, True), ("visa", "visa", True, True),
                    ("draft", "tours", False, True), ("archive", "tours", True, False)):
                product = await domain.create_product(session, code=code, name=code,
                                                      direction=direction, by=SYSTEM_ACTOR)
                if published:
                    await domain.publish_version(session, product.id, domain.TOUR_STAGES,
                                                 domain.TOUR_TRANSITIONS, "system", by=SYSTEM_ACTOR)
                product.active = active
                ids[code] = product.id
            await session.commit()
            return ids

    ids = asyncio.run(seed())
    yield sm, conv, ids, _login("ademi")
    _clear()


def form_data(client, ids, url=URL):
    response = client.get(url)
    assert response.status_code == 200, response.text[-3000:]
    inputs = Rendered(response.text).by_attr("name")
    data = {n["attrs"]["name"]: n["attrs"].get("value", "") for n in inputs
            if n["tag"] == "input"}
    data.update(product_id=str(ids["tour"]), reference="SYN-2026-01",
                signed_at="2026-10-06T01:30", amount="12500.50", currency="KGS",
                amount_unknown_reason="", confirmed="yes")
    return data


def snapshot(sm):
    async def read():
        async with sm() as session:
            return {model.__tablename__: (await session.execute(
                select(model.__table__).order_by(model.id))).all()
                for model in (Contact, ContactIdentity, ServiceCase, ServiceEvent,
                              CalendarTask, ServicePayment, Assignment)}
    return asyncio.run(read())


def post(client, data, url=URL):
    return client.post(url, data=data, follow_redirects=False)


def assign(sm, owner):
    async def seed():
        async with sm() as session:
            contact = await contracts.ContactService.find_or_create_by_identity(
                session, "phone", "+996555000111")
            await contracts.live_assign.assign_locked(session, contact.id, "tours", owner,
                                                      assigned_by="admin", reason="synthetic")
            await session.commit()
    asyncio.run(seed())


def test_get_is_read_only_and_offers_only_active_published_product(env):
    sm, conv, ids, client = env
    before = snapshot(sm)
    response = client.get(URL)
    assert response.status_code == 200
    options = Rendered(response.text).by_attr("value")
    options = [n["attrs"]["value"] for n in options if n["tag"] == "option"]
    assert options == ["", str(ids["tour"])]
    assert snapshot(sm) == before
    assert 'name="amount"' in response.text and 'value="999"' not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_real_form_creates_case_event_task_and_redirects_to_working_card(env):
    sm, conv, ids, client = env
    response = post(client, form_data(client, ids))
    assert response.status_code == 303
    assert response.headers["x-action-outcome"] == "contract_signed"
    card = client.get(response.headers["location"])
    assert card.status_code == 200 and "SYN-2026-01" in card.text
    rows = snapshot(sm)
    assert len(rows["contacts"]) == len(rows["contact_identities"]) == len(rows["service_cases"]) == 1
    case = rows["service_cases"][0]._mapping
    assert case["owner_login"] == case["signed_by"] == "ademi"
    assert case["agreed_amount"] == Decimal("12500.50") and case["currency"] == "KGS"
    assert case["signed_at"] == datetime(2026, 10, 5, 19, 30)  # UTC из Бишкек UTC+6
    events = [r._mapping["event_type"] for r in rows["service_events"]]
    assert events == ["case_opened", "contract_signed"]
    assert len(rows["calendar_tasks"]) == 1
    assert rows["calendar_tasks"][0]._mapping["service_case_id"] == case["id"]
    assert rows["service_payments"] == []
    assert conv.sale_amount == 999 and conv.outcome == ""  # старый исход не подменяется


def test_double_submit_and_retry_after_lost_response_have_one_result(env):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    first = post(client, data)
    before = snapshot(sm)
    second = post(client, data)
    assert first.status_code == second.status_code == 303
    assert first.headers["location"] == second.headers["location"]
    assert snapshot(sm) == before
    changed = post(client, dict(data, amount="999.00"))
    assert changed.status_code == 409
    assert "уже сохранена" in changed.text
    assert snapshot(sm) == before


def test_unknown_price_is_not_zero(env):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    data.update(amount="", currency="", amount_unknown_reason="Ожидаем уточнение предложения")
    assert post(client, data).status_code == 303
    case = snapshot(sm)["service_cases"][0]._mapping
    assert case["agreed_amount"] is None and case["amount_unknown_reason"] == data["amount_unknown_reason"]


@pytest.mark.parametrize("changes", [
    {"reference": ""}, {"reference": "x" * 129}, {"amount": "0"}, {"amount": "-1"},
    {"amount": "NaN"}, {"amount": "1.001"}, {"amount": "1000000000000"},
    {"amount": ""}, {"currency": "КГС"}, {"currency": ""},
    {"amount_unknown_reason": "Неизвестно"}, {"signed_at": "2026-02-31T12:00"},
    {"signed_at": "2026-10-06T01:30+06:00"}, {"confirmed": ""}, {"product_id": "oops"},
])
def test_invalid_input_has_no_partial_contact_case_or_task_and_keeps_form(env, changes):
    sm, conv, ids, client = env
    data = dict(form_data(client, ids), **changes)
    before = snapshot(sm)
    response = post(client, data)
    assert response.status_code == 422
    assert 'role="alert"' in response.text
    assert data["idempotency_key"] in response.text
    assert snapshot(sm) == before


@pytest.mark.parametrize("field", ["csrf_token", "idempotency_key", "key_signature"])
@pytest.mark.parametrize("forged", ["", "forged", "подделка"])
def test_forged_or_missing_form_tokens_fail_closed(env, field, forged):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    data[field] = forged
    before = snapshot(sm)
    assert post(client, data).status_code == 403
    assert snapshot(sm) == before


def test_form_key_cannot_be_replayed_for_another_conversation_or_session(env):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    other_uid = "frunze_tours:996555000222"
    store._memory_store._conv[other_uid] = store.ConversationView(
        user_id=other_uid, phone="996555000222", channel="whatsapp", bot_id="frunze_tours",
        funnel="tours", assigned_to="ademi")
    assert post(client, data, f"/admin/conversation/{other_uid}/contract").status_code == 403
    other_client = _login("ademi")
    assert post(other_client, data).status_code == 403
    assert snapshot(sm)["service_cases"] == []


def test_visible_csrf_token_cannot_sign_an_arbitrary_idempotency_key(env):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    data["idempotency_key"] = "0" * 48
    payload = "\n".join(("contract-v1", "ademi", UID, data["idempotency_key"], data["csrf_token"]))
    data["key_signature"] = hmac.new(data["csrf_token"].encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert post(client, data).status_code == 403
    assert snapshot(sm)["contacts"] == []


@pytest.mark.parametrize("owner", ["aisina", "medina"])
def test_foreign_panel_owner_is_rejected_even_when_old_authz_flag_is_off(env, owner):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    conv.assigned_to = owner
    before = snapshot(sm)
    assert client.get(URL).status_code == 404
    assert post(client, data).status_code == 404
    assert snapshot(sm) == before


def test_foreign_direction_and_product_are_rejected(env):
    sm, conv, ids, client = env
    assert _login("medina").get(URL).status_code == 404
    data = form_data(client, ids)
    for product_id in (ids["visa"], 999999):
        assert post(client, dict(data, product_id=str(product_id))).status_code == 404
    assert snapshot(sm)["contacts"] == []


def test_domain_owner_overrides_stale_panel_permission(env):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    assign(sm, "aisina")
    before = snapshot(sm)
    assert post(client, data).status_code == 404
    assert snapshot(sm) == before


@pytest.mark.parametrize("owner", ["", "deleted-manager"])
def test_unassigned_or_deleted_manager_cannot_create_contract(env, owner):
    sm, conv, ids, client = env
    admin = _login("admin")
    data = form_data(admin, ids)
    conv.assigned_to = owner
    assert post(admin, data).status_code == 422
    assert admin.get(URL).status_code == 422
    assert snapshot(sm)["contacts"] == []


def test_admin_records_contract_for_current_owner_not_arbitrary_posted_owner(env):
    sm, conv, ids, _ = env
    client = _login("admin")
    data = form_data(client, ids)
    data.update(owner_login="medina", contact_id="999", signed_by="forged")
    assert post(client, data).status_code == 303
    case = snapshot(sm)["service_cases"][0]._mapping
    assert case["owner_login"] == "ademi" and case["signed_by"] == "admin"


@pytest.mark.parametrize("flag", ["admin_workday_enabled", "service_cases_enabled"])
def test_flags_rechecked_after_opening_form(env, monkeypatch, flag):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    monkeypatch.setattr(ar.settings, flag, False)
    before = snapshot(sm)
    response = post(client, data)
    assert response.status_code == (404 if flag == "admin_workday_enabled" else 409)
    assert snapshot(sm) == before


@pytest.mark.parametrize("product", ["draft", "archive"])
def test_unpublished_or_archived_product_cannot_be_selected_by_direct_post(env, product):
    sm, conv, ids, client = env
    data = dict(form_data(client, ids), product_id=str(ids[product]))
    before = snapshot(sm)
    assert post(client, data).status_code == 422
    assert snapshot(sm) == before


@pytest.mark.parametrize("channel,key", [("whatsapp", "905078174386"), ("telegram", "123456789")])
def test_identity_uses_channel_and_preserves_international_country_code(env, channel, key):
    sm, conv, ids, client = env
    conv.channel, conv.phone, conv.user_id = channel, key, "frunze_tours:" + key
    store._memory_store._conv[conv.user_id] = conv
    url = f"/admin/conversation/{conv.user_id}/contract"
    data = form_data(client, ids, url)
    assert post(client, data, url).status_code == 303
    identity = snapshot(sm)["contact_identities"][0]._mapping
    assert identity["normalized_value"] == key
    assert identity["identity_type"] == ("telegram" if channel == "telegram" else "phone")


def test_phone_key_mismatch_is_not_silently_merged(env):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    conv.phone = "996555000222"
    assert post(client, data).status_code == 422
    assert snapshot(sm)["contacts"] == []


def test_legacy_chat_phone_display_fallback_still_creates_correct_identity(env):
    sm, conv, ids, client = env
    conv.phone = ""
    assert client.get(f"/admin/conversation/{UID}").status_code == 200
    # Рендер старой карточки меняет view.phone на bot_id:phone.
    assert conv.phone == UID
    assert post(client, form_data(client, ids)).status_code == 303
    assert snapshot(sm)["contact_identities"][0]._mapping["normalized_value"] == "996555000111"


def test_initial_task_failure_rolls_back_contact_and_contract_then_same_form_retries(env, monkeypatch):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    original = domain._create_initial_tasks

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic task failure")

    monkeypatch.setattr(domain, "_create_initial_tasks", fail)
    before = snapshot(sm)
    response = post(client, data)
    assert response.status_code == 503 and data["idempotency_key"] in response.text
    assert snapshot(sm) == before
    monkeypatch.setattr(domain, "_create_initial_tasks", original)
    assert post(client, data).status_code == 303


def test_database_outage_shows_retry_form_without_claiming_success(env, monkeypatch):
    sm, conv, ids, client = env
    data = form_data(client, ids)

    def unavailable():
        raise RuntimeError("synthetic outage")

    monkeypatch.setattr(ar, "_domain_sessionmaker", unavailable)
    response = post(client, data)
    assert response.status_code == 503
    assert data["idempotency_key"] in response.text
    assert response.headers["x-action-outcome"] == "failed"


@pytest.mark.parametrize("redesign", [False, True])
def test_both_chat_versions_offer_link_only_when_both_flags_on(env, monkeypatch, redesign):
    sm, conv, ids, client = env
    monkeypatch.setattr(ar.settings, "admin_chat_redesign_enabled", redesign)
    chat_url = f"/admin/conversation/{UID}"
    response = client.get(chat_url)
    links = Rendered(response.text).by_attr("href")
    assert any(n["attrs"]["href"].endswith("/contract") for n in links)
    monkeypatch.setattr(ar.settings, "service_cases_enabled", False)
    links = Rendered(client.get(chat_url).text).by_attr("href")
    assert not any(n["attrs"]["href"].endswith("/contract") for n in links)


def test_form_is_native_post_with_named_labels_and_escaped_input(env):
    sm, conv, ids, client = env
    data = form_data(client, ids)
    data.update(reference='<script>alert("x")</script>', amount="0")
    response = post(client, data)
    assert '<script>alert("x")</script>' not in response.text
    nodes = Rendered(response.text)
    forms = [n for n in nodes.nodes if n["tag"] == "form"]
    assert any(f["attrs"].get("method") == "post" for f in forms)
    labels = {n["attrs"]["for"] for n in nodes.by_attr("for")}
    for n in nodes.by_attr("name"):
        if n["tag"] in ("input", "select", "textarea") and n["attrs"].get("type") != "hidden":
            assert n["attrs"].get("id") in labels
