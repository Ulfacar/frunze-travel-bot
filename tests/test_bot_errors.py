"""P1.4: петля «бот ошибся». Главное свойство — без регрессионного теста не закрывается."""
import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import bot_errors
from app.integrations.crm.db import Base, BotError, Conversation


async def _db(tmp_path, rows=()):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'errors.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    if rows:
        async with sm() as session:
            session.add_all(list(rows))
            await session.commit()
    return engine, sm


def _run(factory):
    asyncio.run(factory())


def test_report_pulls_dialog_context(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [Conversation(
            user_id="frunze_tours_sezim:996700000001", phone="996700000001",
            channel="whatsapp", bot_id="frunze_tours_sezim", funnel="tours")])
        eid = await bot_errors.report(
            category="price", quote="Сделаем скидку 15%",
            expected="вилка без обещания скидки",
            user_id="frunze_tours_sezim:996700000001", sessionmaker=sm)
        async with sm() as session:
            row = await session.get(BotError, eid)
            assert row.bot_id == "frunze_tours_sezim" and row.funnel == "tours"
            assert row.status == "open" and row.source == "owner"
        await engine.dispose()
    _run(check)


def test_unknown_category_rejected(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path)
        with pytest.raises(bot_errors.BotErrorInput, match="неизвестная категория"):
            await bot_errors.report(category="выдумка", quote="x", sessionmaker=sm)
        await engine.dispose()
    _run(check)


def test_empty_report_rejected(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path)
        with pytest.raises(bot_errors.BotErrorInput, match="пустую не пишем"):
            await bot_errors.report(category="other", sessionmaker=sm)
        await engine.dispose()
    _run(check)


def test_cannot_close_without_regression_test(tmp_path):
    """Ядро петли: «починили» без теста означает «починили до следующего раза»."""
    async def check():
        engine, sm = await _db(tmp_path)
        eid = await bot_errors.report(category="no_handoff",
                                      quote="не передал менеджеру", sessionmaker=sm)
        with pytest.raises(bot_errors.BotErrorInput, match="регрессионный тест"):
            await bot_errors.mark_fixed(eid, covered_by_test="", sessionmaker=sm)
        with pytest.raises(bot_errors.BotErrorInput):
            await bot_errors.mark_fixed(eid, covered_by_test="   ", sessionmaker=sm)
        assert len(await bot_errors.open_errors(sessionmaker=sm)) == 1
        await engine.dispose()
    _run(check)


def test_fix_closes_and_records_the_test(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path)
        eid = await bot_errors.report(category="price", quote="скидка 15%", sessionmaker=sm)
        assert await bot_errors.mark_fixed(
            eid, covered_by_test="tests/test_validator.py::test_no_discount",
            fix_ref="abc1234", sessionmaker=sm) is True
        assert await bot_errors.mark_fixed(          # повторно — no-op
            eid, covered_by_test="x", sessionmaker=sm) is False
        assert await bot_errors.open_errors(sessionmaker=sm) == []
        async with sm() as session:
            row = await session.get(BotError, eid)
            assert row.status == "fixed" and row.fixed_at is not None
            assert row.covered_by_test.endswith("test_no_discount")
        await engine.dispose()
    _run(check)


def test_wontfix_requires_explanation(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path)
        eid = await bot_errors.report(category="tone", quote="сухо", sessionmaker=sm)
        with pytest.raises(bot_errors.BotErrorInput):
            await bot_errors.mark_wontfix(eid, note="", sessionmaker=sm)
        assert await bot_errors.mark_wontfix(
            eid, note="так и задумано владельцем", sessionmaker=sm) is True
        await engine.dispose()
    _run(check)


def test_counts_show_progress_by_category(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path)
        a = await bot_errors.report(category="price", quote="1", sessionmaker=sm)
        await bot_errors.report(category="price", quote="2", sessionmaker=sm)
        await bot_errors.report(category="country", quote="3", sessionmaker=sm)
        await bot_errors.mark_fixed(a, covered_by_test="t::x", sessionmaker=sm)
        data = await bot_errors.counts(sessionmaker=sm)
        assert data["price"] == {"open": 1, "fixed": 1}
        assert data["country"] == {"open": 1}
        await engine.dispose()
    _run(check)


def test_untested_fixes_detects_a_leaky_loop(tmp_path):
    """Если кто-то закрыл ошибку в обход mark_fixed — это видно."""
    async def check():
        engine, sm = await _db(tmp_path)
        eid = await bot_errors.report(category="other", quote="x", sessionmaker=sm)
        async with sm() as session:                  # обход API, как руками в БД
            row = await session.get(BotError, eid)
            row.status = "fixed"
            await session.commit()
        leaky = await bot_errors.untested_fixes(sessionmaker=sm)
        assert [r.id for r in leaky] == [eid]
        await engine.dispose()
    _run(check)


def test_categories_cover_real_complaints():
    """Категории — из реальных жалоб по проекту, а не абстрактные."""
    assert {"price", "country", "misunderstood", "no_handoff"} <= set(bot_errors.CATEGORIES)


def test_open_list_is_newest_first(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path)
        for i in range(3):
            await bot_errors.report(category="other", quote=f"#{i}", sessionmaker=sm)
        rows = await bot_errors.open_errors(sessionmaker=sm)
        async with sm() as session:
            all_ids = [r.id for r in (await session.execute(
                select(BotError).order_by(BotError.id))).scalars().all()]
        assert [r.id for r in rows][0] == all_ids[-1]
        await engine.dispose()
    _run(check)
