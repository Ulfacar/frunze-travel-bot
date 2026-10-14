"""Сводка пилота: агрегаты без ПД, эпизоды ожидания в рабочих минутах."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.crm import db
from app.integrations.panel.store import PostgresConversationStore
from scripts.pilot_daily_summary import compute

UTC = timezone.utc


def local(h, mi=0, d=27):  # 27.10.2026 — вторник
    return datetime(2026, 10, d, h, mi, tzinfo=UTC) - timedelta(hours=6)


def test_summary_counts_without_personal_data(tmp_path, monkeypatch):
    url = "sqlite+aiosqlite:///" + str(tmp_path / "s.db").replace("\\", "/")
    engine = create_async_engine(url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_sessionmaker", sm)
    store = PostgresConversationStore()

    async def go():
        async with engine.begin() as c:
            await c.run_sync(db.Base.metadata.create_all)
        key = "getvisa:996700000001"
        times = [("client", local(11)), ("manager", local(11, 50)),     # 50 мин — дольше 30
                 ("client", local(12)), ("manager", local(12, 10)),     # 10 мин
                 ("client", local(18, 40))]                             # 20 мин до закрытия (19:00), без ответа
        for sender, at in times:
            mid = await store.add_message(key, sender, "текст", channel="whatsapp", bot_id="getvisa",
                                          phone="996700000001", status="failed" if (sender, at) == times[3] else "")
            async with sm() as s:
                await s.execute(update(db.ConvMessage).where(db.ConvMessage.id == mid).values(created_at=at))
                await s.commit()
        await store.add_audit("medina", "sale_full_payment", key, "case 1")
        async with sm() as s:
            await s.execute(update(db.AuditLog).values(created_at=local(15)))
            await s.commit()
        return await compute(sm, date(2026, 10, 27), {"getvisa"}, 30)
    result = asyncio.run(go())
    assert result["waiting_episodes"] == 3
    assert result["waited_longer_than_sla"] == 1
    assert result["max_wait_minutes"] == 50.0
    assert result["send_failed"] == 1
    assert result["sales_full_payment"] == 1
    assert "996700000001" not in json.dumps(result)
    asyncio.run(engine.dispose())
