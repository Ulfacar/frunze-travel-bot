"""E2-06 — гейт «Рабочего дня» и карточки услуги: AC-34, AC-33, AC-28, AC-31.

Все проверки смотрят на ОТРЕНДЕРЕННЫЙ ответ сервера, а не на файл шаблона. Урок
02.10: гейт, читавший шаблон с диска, не упал, когда весь новый вид подменили на
`{% if False %}`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

import pytest
from sqlalchemy import NullPool, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.config
import app.main as main
from app.config import ManagerConfig
from app.domain.models import (
    CalendarTask, Contact, DomainBase, ServiceCase, ServiceEvent, ServicePayment,
)
from app.domain.service_cases import publish_version, seed_products, sign_contract
from app.domain.service_authz import Actor
from app.domain.task_rules import claim_task
from app.integrations.panel import store as panel_store
from fastapi.testclient import TestClient

import app.admin.router as admin_router

WORK = "/admin/work"
FLAG = "admin_workday_enabled"
WRITE = "service_cases_enabled"

# Логин ОБЯЗАН быть из `manager_scope.BOT_SCOPE_BY_MANAGER`: направления панели
# берутся из этого словаря по логину, а не из поля `bots` в настройках менеджера.
# «ademi» — туровый менеджер, как на проде.
MANAGER_LOGIN = "ademi"
OWNER = Actor(manager_id=MANAGER_LOGIN, allowed_directions=("tours",))
SYSTEM = Actor(manager_id="system", is_full_admin=True)
TICKET_STAGES = [{"code": "TKT-01", "name": "Билет продан"},
                 {"code": "TKT-02", "name": "Билет выписан"}]
TICKET_TRANSITIONS = {"TKT-01": ["TKT-02"], "TKT-02": []}


class Rendered(HTMLParser):
    """Мини-разбор ответа: проверяем вложенность и атрибуты, а не подстроки."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[dict] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.nodes.append({"tag": tag, "attrs": dict(attrs)})

    def by_attr(self, name: str, value: str | None = None) -> list[dict]:
        return [n for n in self.nodes
                if name in n["attrs"] and (value is None or n["attrs"][name] == value)]


def _clear() -> None:
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()


def _managers(monkeypatch) -> None:
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
        ManagerConfig(login=MANAGER_LOGIN, name="Адеми", password="frunze",
                      bots=["frunze_tours"]),
    ], raising=False)


def _on(monkeypatch, *, show=True, write=True) -> None:
    monkeypatch.setattr(app.config.settings, FLAG, show, raising=False)
    monkeypatch.setattr(app.config.settings, WRITE, write, raising=False)


def _login(login: str = "admin", password: str = "frunze") -> TestClient:
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login",
                       data={"login": login, "password": password}).status_code == 200
    return client


def _make_domain_sm(tmp_path: Path):
    """Доменная БД на файле: NullPool, иначе падает на смене цикла событий."""
    url = f"sqlite+aiosqlite:///{(tmp_path / 'domain.db').as_posix()}"
    engine = create_async_engine(url, poolclass=NullPool)

    async def build():
        async with engine.begin() as connection:
            await connection.run_sync(DomainBase.metadata.create_all)

    asyncio.run(build())
    return async_sessionmaker(engine, expire_on_commit=False)


def _seed_case(sm, *, owner=MANAGER_LOGIN, reference="W-1", direction="tours",
               amount="100000.00", task_at=None, claim_minutes=None):
    """Завести услугу и, если нужно, задачу с захватом."""
    out: dict = {}

    async def build():
        async with sm() as session:
            contact = Contact()
            session.add(contact)
            await session.flush()
            products = await seed_products(session, published_by="admin", by=SYSTEM)
            product = next(p for p in products if p.direction == direction)
            if product.current_version_id is None:
                await publish_version(session, product.id, TICKET_STAGES,
                                      TICKET_TRANSITIONS, "admin", by=SYSTEM)
            actor = Actor(manager_id=owner, allowed_directions=(direction,))
            case = await sign_contract(
                session, contact_id=contact.id, product_id=product.id,
                owner_login=owner, by=actor, reference=reference,
                amount=Decimal(amount), currency="KGS",
                idempotency_key=f"gate-{reference}")
            await session.flush()
            out["case_id"] = case.id
            out["revision"] = case.revision
            if task_at is not None:
                task = CalendarTask(
                    contact_id=contact.id, manager_id=owner, direction=direction,
                    kind="call", comment="Позвонить клиенту",
                    scheduled_date=task_at.date(), scheduled_at=task_at,
                    created_by="test", service_case_id=case.id)
                session.add(task)
                await session.flush()
                out["task_id"] = task.id
                if claim_minutes is not None:
                    await claim_task(session, task.id, worker="worker-A",
                                     now=datetime.now(timezone.utc)
                                     - timedelta(minutes=claim_minutes))
            await session.commit()

    asyncio.run(build())
    return out


def _count(sm, model) -> int:
    async def run():
        async with sm() as session:
            from sqlalchemy import func
            return await session.scalar(select(func.count()).select_from(model))
    return int(asyncio.run(run()) or 0)


# --- 1. Гейт флага -----------------------------------------------------------

def test_flag_off_hides_every_route_including_posts(monkeypatch, tmp_path):
    """OFF: ни одного маршрута, включая POST. Гейт только на чтении — открытая запись."""
    _clear(); _managers(monkeypatch)
    monkeypatch.setattr(app.config.settings, FLAG, False, raising=False)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    client = _login()
    for path in (WORK, "/admin/work/list", "/admin/work/claims",
                 "/admin/case/1", "/admin/case/1/panel/money",
                 "/admin/case/1/panel/path"):
        assert client.get(path).status_code == 404, path
    for path in ("/admin/case/1/advance", "/admin/case/1/money/payment",
                 "/admin/case/1/money/refund-due", "/admin/case/1/money/void",
                 "/admin/case/1/task/1/finish", "/admin/work/claim/1/release",
                 "/admin/work/claim/1/confirm"):
        assert client.post(path, data={}).status_code == 404, path


def test_flag_off_keeps_the_menu_unchanged(monkeypatch):
    """OFF: ссылки «Рабочий день» в отрендеренном меню нет."""
    _clear(); _managers(monkeypatch)
    monkeypatch.setattr(app.config.settings, FLAG, False, raising=False)
    body = _login().get("/admin").text
    assert 'href="/admin/work"' not in body


def test_flag_on_shows_the_link_and_answers(monkeypatch, tmp_path):
    """ON: страница отвечает и ссылка появляется — исключение не прячет регрессию."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    client = _login()
    assert client.get(WORK).status_code == 200
    assert 'href="/admin/work"' in client.get("/admin").text


def test_every_flagged_path_answers_when_the_flag_is_on(monkeypatch, tmp_path):
    """Все пути, исключённые из общего обхода, обязаны отвечать при ON.

    Пути под флагом вынесены в `FLAGGED_PATHS` двух существующих гейтов, и в их
    комментарии прямо сказано: исключение не должно прятать регрессию. Эта
    проверка — вторая половина той договорённости.
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    client = _login()
    bad = {}
    for path in ("/admin/work", "/admin/work/list", "/admin/work/claims"):
        code = client.get(path).status_code
        if code != 200:
            bad[path] = code
    assert bad == {}, f"при включённом тумблере страницы не отвечают: {bad}"


def test_the_flag_is_off_by_default():
    """Дефолт OFF: выкатили код — панель не изменилась."""
    from app.admin.router import FEATURE_FLAGS
    assert app.config.settings.admin_workday_enabled is False
    assert FEATURE_FLAGS["admin_workday_enabled"]["default"]() is False
    assert FEATURE_FLAGS["service_cases_enabled"]["default"]() is False


# --- 2-3. Пустота против сбоя ------------------------------------------------

def test_empty_day_is_not_reported_as_a_failure(monkeypatch, tmp_path):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    body = _login().get(WORK).text
    assert "Открытых услуг" in body
    assert "Это сбой загрузки" not in body


def test_a_broken_registry_shows_a_failure_and_not_an_empty_day(monkeypatch):
    """AC-31: реестр недоступен → проблема видна, панель жива, не 500."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)

    def boom():
        raise RuntimeError("реестр недоступен")

    monkeypatch.setattr(admin_router, "_domain_sessionmaker", boom)
    response = _login().get(WORK)
    assert response.status_code == 200
    assert "Это сбой загрузки" in response.text
    assert "Открытых услуг" not in response.text


# --- 4. Порядок объясним -----------------------------------------------------

def test_order_is_explainable_and_each_row_carries_its_reason(monkeypatch, tmp_path):
    """Доказательство приёмки: порядок виден в DOM и у каждой строки своя причина."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    now = datetime.now(timezone.utc)
    stuck = _seed_case(sm, reference="W-STUCK", task_at=now - timedelta(hours=3),
                       claim_minutes=40)
    overdue = _seed_case(sm, reference="W-OVERDUE",
                         task_at=now - timedelta(days=2))
    body = _login(MANAGER_LOGIN).get(WORK + "?tab=now").text
    page = Rendered(body)
    order = [n["attrs"]["data-case-id"] for n in page.by_attr("data-case-id")]
    assert order[:2] == [str(stuck["case_id"]), str(overdue["case_id"])], order
    reasons = [n["attrs"]["data-reason"] for n in page.by_attr("data-reason")]
    assert reasons[:2] == ["claim_stuck", "task_overdue"], reasons
    # Причина — человеческая, а не только код.
    assert "дубль" in body or "результата нет" in body


def test_the_page_explains_how_the_order_is_computed(monkeypatch, tmp_path):
    """Таблица весов рисуется из RULES — приёмщик проверяет порядок сам."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    body = _login().get(WORK).text
    from app.domain.service_day import RULES
    for rule in RULES:
        assert rule["label"] in body, rule["code"]


# --- 9-11. Права -------------------------------------------------------------

def test_manager_sees_payment_but_not_refund_buttons(monkeypatch, tmp_path):
    """Деньги руководителя менеджер не видит, но знает, что они есть."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-MONEY")
    body = _login(MANAGER_LOGIN).get(f"/admin/case/{case['case_id']}?tab=money").text
    assert f"/admin/case/{case['case_id']}/money/payment" in body
    for forbidden in ("money/refund-due", "money/void", "money/correct-entry",
                      "money/contract-amount"):
        assert forbidden not in body, forbidden
    assert "руководител" in body.lower()      # сказано, у кого эти действия


def test_direct_post_of_a_financial_action_is_refused(monkeypatch, tmp_path):
    """AC-33: отказ на сервере, независимо от интерфейса. В журнале денег ноль."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-DENY")
    response = _login(MANAGER_LOGIN).post(
        f"/admin/case/{case['case_id']}/money/refund-due",
        data={"amount": "100.00", "currency": "KGS", "reason": "проверка",
              "idempotency_key": "x"})
    # Услугу менеджер видит, поэтому скрывать её существование бессмысленно —
    # отказ ОБЪЯСНЯЕТСЯ. Важно не код ответа, а то, что записи не появилось.
    assert response.status_code == 200
    assert response.headers.get("X-Action-Outcome") == "denied"
    assert _count(sm, ServicePayment) == 0


def test_a_scoped_manager_cannot_open_a_foreign_case(monkeypatch, tmp_path):
    """Чужая услуга — 404, и для каждой вкладки отдельно."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, owner="someone_else", reference="W-FOREIGN")
    client = _login(MANAGER_LOGIN)
    assert client.get(f"/admin/case/{case['case_id']}").status_code == 404
    for tab in ("path", "money", "tasks", "route"):
        assert client.get(
            f"/admin/case/{case['case_id']}/panel/{tab}").status_code == 404, tab
    # Полный админ видит.
    assert _login("admin").get(f"/admin/case/{case['case_id']}").status_code == 200


# --- 6-8. Действие меняет шаг ------------------------------------------------

def test_advancing_changes_the_next_step_and_writes_one_event(monkeypatch, tmp_path):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-STEP")
    client = _login(MANAGER_LOGIN)
    before = client.get(f"/admin/case/{case['case_id']}").text
    events_before = _count(sm, ServiceEvent)
    response = client.post(f"/admin/case/{case['case_id']}/advance",
                           data={"to_stage": "TOUR-02",
                                 "expected_revision": str(case["revision"])})
    assert response.status_code == 200
    assert response.headers.get("X-Action-Outcome") == "advanced"
    after = client.get(f"/admin/case/{case['case_id']}").text
    assert "Бронь отправлена" in after
    assert before != after
    assert _count(sm, ServiceEvent) == events_before + 1


def test_advancing_without_required_facts_keeps_the_stage(monkeypatch, tmp_path):
    """Обязательные факты: отказ понятный, этап не изменился, введённое вернулось."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-FACTS")
    client = _login(MANAGER_LOGIN)
    client.post(f"/admin/case/{case['case_id']}/advance",
                data={"to_stage": "TOUR-02", "expected_revision": str(case["revision"])})
    response = client.post(f"/admin/case/{case['case_id']}/advance",
                           data={"to_stage": "TOUR-03", "expected_revision": "2"})
    assert response.headers.get("X-Action-Outcome") == "invalid"

    async def stage():
        async with sm() as session:
            return (await session.get(ServiceCase, case["case_id"])).stage
    assert asyncio.run(stage()) == "TOUR-02"


def test_a_stale_revision_is_reported_and_adds_no_second_event(monkeypatch, tmp_path):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-STALE")
    client = _login(MANAGER_LOGIN)
    data = {"to_stage": "TOUR-02", "expected_revision": str(case["revision"])}
    first = client.post(f"/admin/case/{case['case_id']}/advance", data=data)
    assert first.headers.get("X-Action-Outcome") == "advanced"
    events = _count(sm, ServiceEvent)
    second = client.post(f"/admin/case/{case['case_id']}/advance", data=data)
    assert second.headers.get("X-Action-Outcome") == "invalid"
    assert _count(sm, ServiceEvent) == events


# --- 12-13. Деньги: идемпотентность и ошибка ---------------------------------

def test_the_same_idempotency_key_records_one_payment(monkeypatch, tmp_path):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-IDEM")
    client = _login(MANAGER_LOGIN)
    data = {"amount": "40000.00", "currency": "KGS", "idempotency_key": "same-key"}
    for _ in range(2):
        response = client.post(f"/admin/case/{case['case_id']}/money/payment",
                               data=data)
        assert response.headers.get("X-Action-Outcome") == "recorded"
    assert _count(sm, ServicePayment) == 1


def test_a_failed_save_returns_the_form_with_the_same_key(monkeypatch, tmp_path):
    """Введённое не теряется, и ключ тот же — иначе повтор создаст вторую оплату."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-FAIL")
    import app.admin.workday as wd

    async def boom(*args, **kwargs):
        raise RuntimeError("журнал недоступен")

    monkeypatch.setattr(wd, "record_payment", boom)
    response = _login(MANAGER_LOGIN).post(
        f"/admin/case/{case['case_id']}/money/payment",
        data={"amount": "777.00", "currency": "KGS", "idempotency_key": "keep-me"})
    assert response.headers.get("X-Action-Outcome") == "failed"
    assert "777.00" in response.text
    assert "keep-me" in response.text
    assert _count(sm, ServicePayment) == 0


def test_write_flag_off_blocks_actions_but_keeps_the_screen(monkeypatch, tmp_path):
    """Запись выключена: экран виден, действие честно отвечает «выключено»."""
    _clear(); _managers(monkeypatch); _on(monkeypatch, show=True, write=False)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-OFF")
    client = _login(MANAGER_LOGIN)
    assert client.get(f"/admin/case/{case['case_id']}").status_code == 200
    response = client.post(f"/admin/case/{case['case_id']}/money/payment",
                           data={"amount": "100.00", "currency": "KGS",
                                 "idempotency_key": "k"})
    assert response.headers.get("X-Action-Outcome") == "off"
    assert _count(sm, ServicePayment) == 0


# --- 14. Подвисшие захваты (AC-28) -------------------------------------------

def test_a_stale_claim_is_visible_with_who_and_when(monkeypatch, tmp_path):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    now = datetime.now(timezone.utc)
    _seed_case(sm, reference="W-CLAIM", task_at=now - timedelta(hours=3),
               claim_minutes=40)
    body = _login(MANAGER_LOGIN).get(WORK).text
    assert "worker-A" in body
    assert "дубль" in body          # сказано, почему нельзя повторять слепо


def test_releasing_a_claim_requires_a_reason(monkeypatch, tmp_path):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    now = datetime.now(timezone.utc)
    case = _seed_case(sm, reference="W-REL", task_at=now - timedelta(hours=3),
                      claim_minutes=40)
    client = _login(MANAGER_LOGIN)
    empty = client.post(f"/admin/work/claim/{case['task_id']}/release",
                        data={"reason": ""})
    assert empty.headers.get("X-Action-Outcome") == "invalid"
    ok = client.post(f"/admin/work/claim/{case['task_id']}/release",
                     data={"reason": "сверено: сообщение не ушло"})
    assert ok.headers.get("X-Action-Outcome") == "released"

    async def claimed():
        async with sm() as session:
            return (await session.get(CalendarTask, case["task_id"])).claimed_at
    assert asyncio.run(claimed()) is None


def test_confirming_a_settled_claim_completes_the_task(monkeypatch, tmp_path):
    """«Действие состоялось» закрывает задачу через протокол, а не мимо него."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    now = datetime.now(timezone.utc)
    case = _seed_case(sm, reference="W-CONF", task_at=now - timedelta(hours=3),
                      claim_minutes=40)
    response = _login(MANAGER_LOGIN).post(
        f"/admin/work/claim/{case['task_id']}/confirm",
        data={"reason": "позвонил, клиент подтвердил"})
    assert response.headers.get("X-Action-Outcome") == "finished"

    async def state():
        async with sm() as session:
            task = await session.get(CalendarTask, case["task_id"])
            return task.status, task.claimed_at
    status, claimed = asyncio.run(state())
    assert status == "completed" and claimed is None


# --- 16. Доступность ---------------------------------------------------------

def test_no_div_onclick_and_tabs_are_real_buttons(monkeypatch, tmp_path):
    """Клавиатура: только настоящие элементы, вкладки с ролями."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-A11Y")
    client = _login(MANAGER_LOGIN)
    for url in (WORK, f"/admin/case/{case['case_id']}"):
        page = Rendered(client.get(url).text)
        clickable_divs = [n for n in page.nodes
                          if n["tag"] == "div" and "onclick" in n["attrs"]]
        assert clickable_divs == [], f"{url}: div с onclick"
        tabs = page.by_attr("role", "tab")
        assert tabs, f"{url}: нет вкладок с role=tab"
        assert all("aria-selected" in t["attrs"] for t in tabs), url


def test_the_next_step_comes_before_the_tabs_in_the_dom(monkeypatch, tmp_path):
    """Главное действие — первым: на телефоне до вкладок доскроллить сложнее."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-DOM")
    body = _login(MANAGER_LOGIN).get(f"/admin/case/{case['case_id']}").text
    step = body.find("data-next-step")
    tabs = body.find('role="tablist"')
    assert step != -1, "блок следующего шага не помечен data-next-step"
    assert tabs != -1 and step < tabs, (step, tabs)


def test_every_input_has_a_label(monkeypatch, tmp_path):
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-LBL")
    client = _login(MANAGER_LOGIN)
    for url in (WORK, f"/admin/case/{case['case_id']}?tab=money"):
        html = client.get(url).text
        page = Rendered(html)
        labelled = {n["attrs"].get("for") for n in page.nodes if n["tag"] == "label"}
        for node in page.nodes:
            if node["tag"] != "input":
                continue
            attrs = node["attrs"]
            if attrs.get("type") == "hidden":
                continue
            has = ("aria-label" in attrs
                   or (attrs.get("id") and attrs["id"] in labelled))
            assert has, f"{url}: поле без подписи {attrs}"


# --- Находки ревью 05.10 -----------------------------------------------------

def _admin_case(sm, monkeypatch, tmp_path, *, reference="W-ADM"):
    """Услуга, которой владеет полный админ: нужна для денежных операций."""
    return _seed_case(sm, owner="admin", reference=reference)


def test_void_and_correct_use_the_field_names_the_form_sends(monkeypatch, tmp_path):
    """Формы шлют `voids_id`/`corrects_id` — хендлер обязан их понимать.

    Расхождение имён делало аннулирование и исправление неработающими, а отказ
    выглядел сбоем базы: `int("")` падал мимо доменной ошибки. Ни один прежний
    тест не проводил успешную денежную операцию через форму.
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _admin_case(sm, monkeypatch, tmp_path)
    client = _login()          # полный админ: возвраты и аннулирование у него
    paid = client.post(f"/admin/case/{case['case_id']}/money/payment",
                       data={"amount": "1000.00", "currency": "KGS",
                             "idempotency_key": "void-base"})
    assert paid.headers.get("X-Action-Outcome") == "recorded"

    async def first_payment_id():
        async with sm() as session:
            row = await session.scalar(select(ServicePayment)
                                       .order_by(ServicePayment.id))
            return row.id
    import asyncio as _a
    target = _a.run(first_payment_id())

    # Имя поля — такое, как в форме карточки.
    voided = client.post(f"/admin/case/{case['case_id']}/money/void",
                         data={"voids_id": str(target), "reason": "оплата не поступала",
                               "idempotency_key": "void-1"})
    assert voided.headers.get("X-Action-Outcome") == "voided", voided.text[:200]
    assert _count(sm, ServicePayment) == 2       # платёж + аннулирование


@pytest.mark.parametrize("value", ["", "   ", "abc", "1.5"])
def test_a_bad_record_number_is_a_clear_refusal_not_a_failure(monkeypatch, tmp_path,
                                                              value):
    """Мусор в номере записи — понятный отказ, а не «не сохранилось»."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _admin_case(sm, monkeypatch, tmp_path, reference="W-BAD")
    response = _login().post(f"/admin/case/{case['case_id']}/money/void",
                             data={"voids_id": value, "reason": "проверка",
                                   "idempotency_key": "bad-1"})
    assert response.headers.get("X-Action-Outcome") == "invalid", value


def test_every_action_is_written_to_the_audit_log(monkeypatch, tmp_path):
    """Действие без следа в журнале аудита недопустимо — особенно для денег.

    Вызов `add_audit` асинхронный, и без `await` запись не происходила вовсе:
    ни переход этапа, ни оплата, ни разбор захвата не оставляли следа.
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _admin_case(sm, monkeypatch, tmp_path, reference="W-AUD")
    client = _login()
    client.post(f"/admin/case/{case['case_id']}/money/payment",
                data={"amount": "500.00", "currency": "KGS",
                      "idempotency_key": "aud-1"})
    actions = [entry.get("action") for entry
               in panel_store._memory_store._audit]
    assert "recorded" in actions, actions


def test_a_failed_action_tells_the_manager_what_happened(monkeypatch, tmp_path):
    """Ошибка видна СРАЗУ, а не внутри закрытого блока формы.

    Единственный текст ошибки лежал в свёрнутом `<details>` формы оплаты —
    менеджер видел, что «ничего не произошло», и не понимал почему (AC-34).
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _admin_case(sm, monkeypatch, tmp_path, reference="W-SEEN")
    import app.admin.workday as wd

    async def boom(*args, **kwargs):
        raise RuntimeError("журнал недоступен")

    monkeypatch.setattr(wd, "record_payment", boom)
    response = _login().post(f"/admin/case/{case['case_id']}/money/payment",
                             data={"amount": "900.00", "currency": "KGS",
                                   "idempotency_key": "seen-1"})
    assert response.headers.get("X-Action-Outcome") == "failed"
    page = Rendered(response.text)
    banners = page.by_attr("data-outcome")
    assert banners, "нет плашки с исходом действия"
    assert any(n["attrs"].get("role") == "alert" for n in banners)
    assert "900.00" in response.text           # введённое вернулось


def test_an_invalid_outcome_is_not_treated_as_success_in_the_browser(monkeypatch,
                                                                     tmp_path):
    """Исход считается по белому списку успеха, а не «всё кроме плохого».

    Прежний список не знал про `invalid` и `off`: страница перезагружалась
    молча, и менеджер думал, что захват разобран, а он висел.
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    body = _login().get(WORK).text
    assert "good.indexOf(outcome) >= 0" in body or "good.indexOf" in body
    for outcome in ("invalid", "off", "denied", "failed"):
        assert outcome in body, f"исход {outcome} не объяснён менеджеру"


def test_a_case_on_the_final_stage_is_not_reported_as_stuck(monkeypatch, tmp_path):
    """Доведённая до конца услуга не «зависла» — иначе список превращается в шум."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-FINAL")
    import asyncio as _a
    from app.domain.service_cases import advance
    from app.domain.service_authz import Actor as _Actor

    async def finish():
        async with sm() as session:
            actor = _Actor(manager_id=MANAGER_LOGIN, allowed_directions=("tours",))
            path = [("TOUR-02", None),
                    ("TOUR-03", {"booking_reference": "X", "confirmed_at": "2026-11-20"}),
                    ("TOUR-04", None), ("TOUR-05", None), ("TOUR-06", None),
                    ("TOUR-07", None)]
            for stage, facts in path:
                await advance(session, case["case_id"], to_stage=stage, by=actor,
                              facts=facts)
            await session.commit()

    _a.run(finish())
    body = _login(MANAGER_LOGIN).get(WORK + "?tab=stuck").text
    page = Rendered(body)
    stuck_rows = page.by_attr("data-stuck", "1")
    assert stuck_rows == [], "завершённая услуга помечена зависшей"


def test_one_unreadable_case_does_not_break_the_whole_screen(monkeypatch, tmp_path):
    """Сбойная услуга показывается строкой, а не гасит экран целиком."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    good = _seed_case(sm, reference="W-OK")
    bad = _seed_case(sm, reference="W-BROKEN")
    import app.domain.service_day as sd
    original = sd.digest_for

    async def selective(session, case, **kwargs):
        if case.id == bad["case_id"]:
            raise RuntimeError("битая услуга")
        return await original(session, case, **kwargs)

    monkeypatch.setattr(sd, "digest_for", selective)
    # Вкладка «все»: услуга без признаков не имеет сильной причины, и фильтр
    # «сейчас» её законно прячет — проверяем не фильтр, а устойчивость экрана.
    response = _login(MANAGER_LOGIN).get(WORK + "?tab=all")
    assert response.status_code == 200
    assert "Это сбой загрузки" not in response.text      # экран не погас
    page = Rendered(response.text)
    ids = {n["attrs"]["data-case-id"] for n in page.by_attr("data-case-id")}
    assert str(good["case_id"]) in ids
    assert str(bad["case_id"]) in ids, "сбойная услуга пропала из списка"
    assert "не удалось разобрать" in response.text.lower()


@pytest.mark.parametrize("path", ["money/refund-due", "money/refund-paid",
                                  "money/void", "money/correct-entry",
                                  "money/contract-amount"])
def test_every_financial_route_refuses_a_plain_manager(monkeypatch, tmp_path, path):
    """AC-33 для ВСЕХ пяти финансовых маршрутов, а не только для одного."""
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="W-ALL-DENY")
    response = _login(MANAGER_LOGIN).post(
        f"/admin/case/{case['case_id']}/{path}",
        data={"amount": "100.00", "currency": "KGS", "reason": "попытка",
              "idempotency_key": "deny-x", "voids_id": "1", "corrects_id": "1"})
    # Отказ объясняется (услуга видна менеджеру), но операция НЕ выполняется.
    assert response.status_code == 200, path
    assert response.headers.get("X-Action-Outcome") == "denied", path
    assert _count(sm, ServicePayment) == 0, path
