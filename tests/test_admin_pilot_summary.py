"""«Сводка пилота» для руководителя направления: цифры, раскрытие и права (флаг OFF).

Время зафиксировано (29.10.2026 14:00 по Бишкеку), рабочие минуты подменены на
календарные — иначе тест зависел бы от часа и дня недели запуска. Номера синтетические.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.admin.pilot_summary as page
import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.core import flags
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

NOW = datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc)          # 14:00 в Бишкеке
TODAY = NOW - timedelta(hours=2)                                  # 12:00 по Бишкеку
YESTERDAY = NOW - timedelta(days=1)
PASS = {"admin": "frunze", "grisha": "g1", "medina": "m1", "aisina": "a1", "ademi": "d1"}
V1, V2, V3, V4 = (f"getvisa:99655580000{i}" for i in range(1, 5))
T1 = "frunze_tours:996555800009"          # номер Адеми
T2 = "frunze_tours_sezim:996555800008"    # номер Айсины — вне скоупа Адеми


class FixedDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


@pytest.fixture
def env(monkeypatch):
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    flags.reset()
    admin_router._look_cache["key"] = None
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login=k, name=k.capitalize(), password=v, admin=(k == "admin"))
        for k, v in PASS.items()])
    monkeypatch.setattr(app.config.settings, "admin_new_look_enabled", True)
    monkeypatch.setattr(app.config.settings, "pilot_reply_sla_minutes", 30)
    monkeypatch.setattr(app.config.settings, "panel_direction_leads",
                        {"visa": ["grisha"], "tours": ["ademi"]})
    monkeypatch.setattr(page, "datetime", FixedDT)
    import app.core.reply_sla as sla
    monkeypatch.setattr(sla, "working_minutes", lambda bot, s, e: (e - s).total_seconds() / 60)
    _seed()
    yield monkeypatch
    flags.reset()
    admin_router._look_cache["key"] = None


def _conv(uid, bot, owner, msgs, name=""):
    store = get_conversation_store()

    async def go():
        for sender, at, status in msgs:
            await store.add_message(uid, sender, f"{sender} текст", channel="whatsapp", bot_id=bot,
                                    phone=uid.split(":")[1], status=status)
            store._conv[uid].messages[-1].created_at = at
        await store.update_meta(uid, funnel="visa" if bot == "getvisa" else "tours",
                                assigned_to=owner, qualification={"name": name} if name else {})
    asyncio.run(go())


def _audit(manager, action, uid, detail, at):
    panel_store._memory_store._audit.append(
        {"manager": manager, "action": action, "user_id": uid, "detail": detail, "created_at": at})


def _seed():
    _conv(V1, "getvisa", "medina", [("client", TODAY, ""),
                                     ("manager", TODAY + timedelta(minutes=10), "sent")], "Асель")
    _conv(V2, "getvisa", "", [("client", TODAY, "")], "Бакыт")                 # ждёт 120 мин
    _conv(V3, "getvisa", "medina", [("client", TODAY, ""),
                                     ("manager", TODAY + timedelta(minutes=5), "failed"),
                                     ("manager", TODAY + timedelta(minutes=6), "unknown")])
    _conv(V4, "getvisa", "medina", [("client", YESTERDAY, ""),
                                     ("bot", YESTERDAY + timedelta(minutes=1), "sent")])
    _conv(T1, "frunze_tours", "ademi", [("client", TODAY, "")], "Турист")
    _conv(T2, "frunze_tours_sezim", "aisina", [("client", TODAY, "")], "Чужой турист")
    _audit("medina", "send", V1, "ответ", TODAY + timedelta(minutes=10))
    _audit("medina", "outcome", V4, "won", YESTERDAY + timedelta(minutes=30))
    _audit("ademi", "send", T1, "x", TODAY)
    _audit("aisina", "send", T2, "x", TODAY)


def _on():
    asyncio.run(flags.set_flag(page.FLAG, True))
    admin_router._look_cache["key"] = None


def _client(login):
    c = TestClient(main.app, base_url="https://testserver")
    assert c.post("/admin/login", data={"login": login, "password": PASS[login]}).status_code == 200
    return c


def _cards(html):
    import re
    return {label: int(n) for n, label in re.findall(
        r'<b>(\d+)</b><span>([^<]+)</span>', html)}


# ---------------------------- цифры ----------------------------

def test_lead_sees_visa_numbers_for_today(env):
    _on()
    r = _client("grisha").get("/admin/pilot-summary")
    assert r.status_code == 200
    cards = _cards(r.text)
    assert cards["Новых обращений"] == 3            # V1, V2, V3; V4 — вчерашний; тур не считается
    assert cards["Ответили из панели"] == 1
    assert cards["Ждали дольше 30 мин"] == 1        # V2: 120 мин без ответа
    assert cards["Не доставлено"] == 1 and cards["Неизвестно, дошло ли"] == 1
    assert cards["Продажи"] == 0
    assert cards["Дольше всех ждали, мин"] == 120


def test_yesterday_and_week(env):
    _on()
    c = _client("grisha")
    y = _cards(c.get("/admin/pilot-summary", params={"period": "yesterday"}).text)
    assert y["Новых обращений"] == 1 and y["Продажи"] == 1 and y["Ответили из панели"] == 0
    w = _cards(c.get("/admin/pilot-summary", params={"period": "week"}).text)
    assert w["Новых обращений"] == 4 and w["Продажи"] == 1


def test_sales_follow_b3_when_enabled(env):
    _on()
    asyncio.run(flags.set_flag("sale_by_full_payment_enabled", True))
    _audit("medina", "sale_full_payment", V1, "case=1 ", TODAY + timedelta(minutes=20))
    w = _cards(_client("grisha").get("/admin/pilot-summary", params={"period": "week"}).text)
    assert w["Продажи"] == 1                         # отметка «won» при B3 не считается


def test_aggregates_have_no_personal_data(env):
    _on()
    html = _client("grisha").get("/admin/pilot-summary", params={"period": "week"}).text
    for secret in ("996555800001", "996555800002", "Асель", "Бакыт", "клиент текст"):
        assert secret not in html


def test_every_number_opens_its_dialogs(env):
    _on()
    c = _client("grisha")
    over = c.get("/admin/pilot-summary", params={"metric": "over_sla"}).text
    assert "Бакыт" in over and "Асель" not in over and "/admin?open=getvisa%3A996555800002" in over
    mine = c.get("/admin/pilot-summary", params={"metric": "answered", "who": "medina"}).text
    assert "Асель" in mine and "Бакыт" not in mine
    failed = c.get("/admin/pilot-summary", params={"metric": "failed"}).text
    assert "996555800003" in failed
    assert c.get("/admin/pilot-summary", params={"metric": "secret"}).status_code == 422


# ---------------------------- права ----------------------------

def test_flag_off_is_404_for_everyone(env):
    assert _client("grisha").get("/admin/pilot-summary").status_code == 404
    assert _client("admin").get("/admin/pilot-summary").status_code == 404
    assert "/admin/pilot-summary" not in _client("grisha").get("/admin/calendar").text


@pytest.mark.parametrize("login", ["medina", "aisina"])
def test_ordinary_managers_are_forbidden(env, login):
    _on()
    c = _client(login)
    assert c.get("/admin/pilot-summary").status_code == 403
    assert c.get("/admin/pilot-summary", params={"direction": "visa", "metric": "new"}).status_code == 403
    assert "/admin/pilot-summary" not in c.get("/admin/calendar").text


def test_forged_direction_is_403(env):
    _on()
    assert _client("grisha").get("/admin/pilot-summary", params={"direction": "tours"}).status_code == 403
    assert _client("ademi").get("/admin/pilot-summary", params={"direction": "visa"}).status_code == 403
    assert _client("grisha").get("/admin/pilot-summary", params={"direction": "anything"}).status_code == 403


def test_tours_lead_sees_only_tours(env):
    _on()
    r = _client("ademi").get("/admin/pilot-summary", params={"metric": "new"})
    assert r.status_code == 200 and "Турист" in r.text          # раскрытие «новых»: только туры
    cards = _cards(r.text)
    assert cards["Новых обращений"] == 1 and cards["Ответили из панели"] == 1
    assert "Асель" not in r.text and "Бакыт" not in r.text
    assert "Чужой турист" not in r.text              # номер вне его скоупа не считается вовсе


def test_lead_list_does_not_widen_own_scope(env):
    """В списке руководителей туров стоит визовый Гриша — туры ему всё равно закрыты."""
    _on()
    env.setattr(app.config.settings, "panel_direction_leads", {"visa": [], "tours": ["grisha"]})
    assert _client("grisha").get("/admin/pilot-summary").status_code == 403


def test_admin_sees_both_directions_and_menu(env):
    _on()
    c = _client("admin")
    assert c.get("/admin/pilot-summary", params={"direction": "visa"}).status_code == 200
    tours = c.get("/admin/pilot-summary", params={"direction": "tours"})
    assert tours.status_code == 200 and _cards(tours.text)["Новых обращений"] == 2   # админ — все номера
    assert "/admin/pilot-summary" in _client("grisha").get("/admin/calendar").text


# ------------------- ревью ux 30.10: P5, P1, P2 -------------------

V5 = "getvisa:996555800005"


def test_client_waiting_since_yesterday_counts_today(env):
    """P5: написал вчера в 22:00 и всё ещё ждёт — это и «сегодня» ждали дольше X."""
    _conv(V5, "getvisa", "medina", [("client", NOW - timedelta(hours=16), "")], "Вечерний")
    _on()
    c = _client("grisha")
    today = c.get("/admin/pilot-summary", params={"metric": "over_sla"}).text
    assert "Вечерний" in today
    cards = _cards(today)
    assert cards["Дольше всех ждали, мин"] == 960     # с 22:00 вчера до 14:00 сегодня
    assert cards["Новых обращений"] == 3              # новым он остаётся только вчера
    assert "с прошлого дня" in today                  # на странице сказано, как считается
    y = c.get("/admin/pilot-summary", params={"period": "yesterday", "metric": "over_sla"}).text
    assert "Вечерний" in y                            # 22:00–24:00 вчера — тоже дольше 30


def test_answered_carryover_wait_is_not_open_forever(env):
    """Ждал с вечера, ответили сегодня в 09:00 — эпизод закрыт ответом, а не «сейчас»."""
    _conv(V5, "getvisa", "medina", [("client", NOW - timedelta(hours=16), ""),
                                     ("manager", NOW - timedelta(hours=5), "sent")], "Вечерний")
    _on()
    cards = _cards(_client("grisha").get("/admin/pilot-summary").text)
    assert cards["Дольше всех ждали, мин"] == 660     # 22:00 → 09:00


def test_drilldown_does_not_load_full_histories(env):
    """P1: раскрытие строит строки из лёгких карточек, не из `store.get` с историей."""
    _on()

    async def no_full(*a, **kw):
        raise AssertionError("раскрытие не должно грузить полную историю диалога")
    env.setattr(panel_store._memory_store, "get", no_full)
    r = _client("grisha").get("/admin/pilot-summary", params={"metric": "new"})
    assert r.status_code == 200 and "Асель" in r.text and "Бакыт" in r.text


def test_simple_mode_shows_phone_readably(env):
    """P2: в простом режиме номер в раскрытии — как везде, «+996 555 80 00 02»."""
    env.setattr(app.config.settings, "panel_simple_mode_enabled", True)
    _on()
    html = _client("grisha").get("/admin/pilot-summary", params={"metric": "over_sla"}).text
    assert "+996 555 80 00 02" in html


def test_sql_loader_and_cards_run_on_a_real_engine(env, tmp_path):
    """P1: ветка Postgres вызывается на живом движке (SQLite): окно сообщений через JOIN,
    карточки раскрытия — пачками, без истории."""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core import pilot_summary as ps
    from app.integrations.crm import db
    from app.integrations.panel.store import PostgresConversationStore
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "p.db"))
    sm = async_sessionmaker(engine, expire_on_commit=False)
    store = PostgresConversationStore(sessionmaker=sm)
    env.setattr(panel_store, "get_conversation_store", lambda: store)
    env.setattr(ps, "CARD_BATCH", 2)                 # три диалога → две пачки IN

    async def go():
        async with engine.begin() as conn:
            await conn.run_sync(db.Base.metadata.create_all)
        for uid, bot, at in ((V1, "getvisa", TODAY), (V2, "getvisa", NOW - timedelta(hours=16)),
                             (V3, "getvisa", TODAY - timedelta(days=30)), (T1, "frunze_tours", TODAY)):
            mid = await store.add_message(uid, "client", "текст", channel="whatsapp", bot_id=bot,
                                          phone=uid.split(":")[1])
            async with sm() as s:
                await s.execute(update(db.ConvMessage).where(db.ConvMessage.id == mid)
                                .values(created_at=at))
                await s.commit()
        await store.update_meta(V1, qualification={"name": "Асель"})
        await store.add_audit("medina", "send", V1, "x")
        async with sm() as s:
            await s.execute(update(db.AuditLog).values(created_at=TODAY))
            await s.commit()
        start, end = ps.period_bounds("today", NOW)
        dialogs, audit = await ps.load({"getvisa"}, start, end)
        views = await ps.cards([V1, V2, V3, T1])
        return dialogs, audit, views
    dialogs, audit, views = asyncio.run(go())
    by = {d.user_id: d for d in dialogs}
    assert set(by) == {V1, V2, V3}                   # туры не попали
    assert len(by[V2].messages) == 1                 # вчерашнее сообщение — в окне
    assert by[V3].messages == []                     # месячной давности — нет
    assert [r["action"] for r in audit] == ["send"]
    assert set(views) == {V1, V2, V3, T1}
    assert views[V1].qualification.get("name") == "Асель" and views[V1].messages == []
    asyncio.run(engine.dispose())
