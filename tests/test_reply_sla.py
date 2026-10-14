"""B2b (14.10): очередь «ждут ответа» — рабочие минуты, перехват, свои/ничьи, порог X."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import app.admin.router as admin_router
from app.core import flags
from app.core.reply_sla import overdue, waiting_minutes, working_minutes
from app.integrations.panel.store import get_conversation_store
from tests.test_live_authz import USER_ID, _client, _setup

UTC = timezone.utc


def local(y, m, d, h, mi=0):
    """Местное время Бишкека → UTC."""
    return datetime(y, m, d, h, mi, tzinfo=UTC) - timedelta(hours=6)


def conv(**kw):
    base = dict(user_id="getvisa:996700000001", bot_id="getvisa", last_sender="client", archived=False,
                intercepted=True, stage="manager", assigned_to="", phone="996700000001",
                last_message_at=local(2026, 10, 14, 11, 0), qualification={}, last_text="?")
    base.update(kw)
    return SimpleNamespace(**base)


# 14.10.2026 — среда; 18.10 — воскресенье. Визы: пн–сб, 10–19.

def test_working_minutes_inside_hours():
    assert working_minutes("getvisa", local(2026, 10, 14, 11), local(2026, 10, 14, 11, 45)) == 45


def test_night_is_not_counted():
    assert working_minutes("getvisa", local(2026, 10, 14, 23), local(2026, 10, 15, 10, 5)) == 5


def test_sunday_is_not_counted():
    assert working_minutes("getvisa", local(2026, 10, 17, 18, 30), local(2026, 10, 19, 10, 10)) == 40


def test_bot_led_or_answered_dialogs_do_not_wait():
    now = local(2026, 10, 14, 15)
    assert waiting_minutes(conv(intercepted=False, stage="greeting"), now) is None   # ведёт бот
    assert waiting_minutes(conv(last_sender="manager"), now) is None                 # ответили
    assert waiting_minutes(conv(archived=True), now) is None
    assert waiting_minutes(conv(intercepted=False, stage="manager"), now) == 240     # стадия человека


def test_overdue_mine_and_unowned_sorted_by_wait():
    now = local(2026, 10, 14, 15)
    items = overdue([conv(user_id="a", assigned_to="medina", last_message_at=local(2026, 10, 14, 14, 50)),  # 10 мин
                     conv(user_id="b", assigned_to="medina", last_message_at=local(2026, 10, 14, 12)),      # 180
                     conv(user_id="c", assigned_to="", last_message_at=local(2026, 10, 14, 14)),            # 60
                     conv(user_id="d", assigned_to="eliza", last_message_at=local(2026, 10, 14, 11))],      # чужой
                    now, sla_minutes=30, login="medina", full_admin=False)
    assert [i["user_id"] for i in items] == ["b", "c"]
    admin = overdue([conv(user_id="d", assigned_to="eliza", last_message_at=local(2026, 10, 14, 11))],
                    now, sla_minutes=30, login="grisha", full_admin=True)
    assert [i["user_id"] for i in admin] == ["d"]


# --- страница ---

def _waiting_client(minutes_ago):
    store = get_conversation_store()
    asyncio.run(store.update_meta(USER_ID, intercepted=True, stage="manager"))
    view = store._conv[USER_ID]
    view.last_sender = "client"
    view.last_message_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)


def test_route_flag_off_is_404(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    assert _client("medina", "m1").get("/admin/overdue").status_code == 404


def test_route_lists_only_with_flag(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    asyncio.run(flags.set_flag("pilot_reply_queue_enabled", True))
    monkeypatch.setattr(admin_router.settings, "pilot_reply_sla_minutes", 30)
    import app.core.reply_sla as sla
    monkeypatch.setattr(sla, "working_minutes", lambda bot_id, start, end: (end - start).total_seconds() / 60)
    _waiting_client(90)
    page = _client("medina", "m1").get("/admin/overdue")
    assert page.status_code == 200 and USER_ID.replace(":", "%3A") in page.text
    _waiting_client(5)
    assert USER_ID.replace(":", "%3A") not in _client("medina", "m1").get("/admin/overdue").text
