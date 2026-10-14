"""B2c (14.10): одно напоминание владельцу на эпизод ожидания, дедуп в БД, ночь не в счёт."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import flags, reply_alerts
from app.integrations.crm import db
from app.integrations.panel.store import PostgresConversationStore

UTC = timezone.utc
KEY = "getvisa:996700000001"


def local(d, h, mi=0):  # 14.10.2026 — среда; Бишкек = UTC+6
    return datetime(2026, 10, d, h, mi, tzinfo=UTC) - timedelta(hours=6)


@pytest.fixture
def env(tmp_path, monkeypatch):
    url = "sqlite+aiosqlite:///" + str(tmp_path / "alerts.db").replace("\\", "/")
    engine = create_async_engine(url)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    async def prep():
        async with engine.begin() as c:
            await c.run_sync(db.Base.metadata.create_all)
    asyncio.run(prep())
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_sessionmaker", sm)
    flags.reset()
    asyncio.run(flags.set_flag(reply_alerts.FLAG, True))
    monkeypatch.setattr(reply_alerts.settings, "pilot_reply_sla_minutes", 30)
    sent = []

    async def fake_send(login, text):
        sent.append((login, text))
        return env_state["ok"]
    env_state = {"ok": True}
    monkeypatch.setattr(reply_alerts, "_send", fake_send)
    import app.core.instant_handoff as ih
    monkeypatch.setattr(ih, "_chat_id_for", lambda login: "chat-" + login if login != "nochat" else "")
    store = PostgresConversationStore()
    yield dict(url=url, sm=sm, engine=engine, sent=sent, state=env_state, store=store)
    flags.reset()
    asyncio.run(engine.dispose())


def waiting(env, *, at, owner="medina", intercepted=True):
    async def go():
        await env["store"].add_message(KEY, "client", "когда будет готово?", channel="whatsapp",
                                       bot_id="getvisa", phone="996700000001")
        async with env["sm"]() as s:
            await s.execute(update(db.Conversation).where(db.Conversation.user_id == KEY).values(
                assigned_to=owner, intercepted=intercepted, stage="manager", last_message_at=at, last_sender="client"))
            await s.commit()
    asyncio.run(go())


def run(env, now, sm=None):
    return asyncio.run(reply_alerts.run(now=now, sessionmaker=sm or env["sm"]))


def test_one_alert_per_episode_no_repeats(env):
    waiting(env, at=local(14, 11, 0))
    assert run(env, local(14, 11, 40)) == 1
    assert run(env, local(14, 11, 45)) == 0
    assert run(env, local(14, 15, 0)) == 0
    assert [login for login, _ in env["sent"]] == ["medina"]
    assert "996700000001" not in env["sent"][0][1]          # без номера клиента


def test_dedupe_survives_restart(env):
    waiting(env, at=local(14, 11, 0))
    assert run(env, local(14, 11, 40)) == 1
    fresh = async_sessionmaker(create_async_engine(env["url"]), expire_on_commit=False)
    assert run(env, local(14, 12, 0), sm=fresh) == 0


def test_manager_reply_before_threshold_cancels(env):
    waiting(env, at=local(14, 11, 0))
    asyncio.run(env["store"].add_message(KEY, "manager", "уже смотрю", channel="whatsapp", bot_id="getvisa"))
    assert run(env, local(14, 12, 0)) == 0 and env["sent"] == []


def test_night_does_not_accumulate(env):
    waiting(env, at=local(14, 23, 0))
    assert run(env, local(15, 9, 59)) == 0                   # ночь: 0 рабочих минут
    assert run(env, local(15, 10, 31)) == 1                  # 31 рабочая минута утром


def test_new_episode_after_reply_alerts_again(env):
    waiting(env, at=local(14, 11, 0))
    assert run(env, local(14, 11, 40)) == 1
    asyncio.run(env["store"].add_message(KEY, "manager", "ответ", channel="whatsapp", bot_id="getvisa"))
    waiting(env, at=local(14, 13, 0))
    assert run(env, local(14, 13, 40)) == 1
    assert len(env["sent"]) == 2


def test_failed_send_is_retried_later_not_lost(env):
    waiting(env, at=local(14, 11, 0))
    env["state"]["ok"] = False
    assert run(env, local(14, 11, 40)) == 0
    env["state"]["ok"] = True
    assert run(env, local(14, 11, 45)) == 1


def test_flag_off_unowned_or_no_chat_are_skipped(env):
    waiting(env, at=local(14, 11, 0), owner="")
    assert run(env, local(14, 12, 0)) == 0
    waiting(env, at=local(14, 11, 0), owner="nochat")
    assert run(env, local(14, 12, 0)) == 0
    async def marker():
        async with env["sm"]() as s:
            return (await s.execute(select(db.Conversation.reply_alert_at))).scalar_one()
    assert asyncio.run(marker()) is None                     # без адресата отметку не ставим
    waiting(env, at=local(14, 11, 0), owner="medina")
    asyncio.run(flags.set_flag(reply_alerts.FLAG, False))
    assert run(env, local(14, 12, 0)) == 0
    assert env["sent"] == []


def test_bot_led_dialog_is_not_alerted(env):
    async def go():
        await env["store"].add_message(KEY, "client", "?", channel="whatsapp", bot_id="getvisa")
        async with env["sm"]() as s:
            await s.execute(update(db.Conversation).values(assigned_to="medina", intercepted=False,
                                                           stage="greeting", last_message_at=local(14, 11)))
            await s.commit()
    asyncio.run(go())
    assert run(env, local(14, 13)) == 0
