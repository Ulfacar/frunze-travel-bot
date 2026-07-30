"""Тесты разового разбора владения диалогами (`scripts/assign_manager_backlog.py`).

Отдельно проверяем каждый предохранитель, за который заплачено ревью: превью ничего не
меняет и совпадает с применением, ротация не вырождается на длинной пачке, NULL считается
бесхозным, telegram-ряд не превращается в выдуманный номер, откат возвращает прежнего
владельца.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import ManagerConfig, settings
from app.core import flags
from app.domain.models import Assignment, DomainBase
from app.integrations.crm.db import AuditLog, Base, ConvMessage, Conversation
from scripts.assign_manager_backlog import (
    REASON_DEPARTED, REASON_SEZIM, REASON_VISA, run)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
STALE = NOW - timedelta(days=90)


def _conv(user_id, **kw):
    """Диалог с осмысленными дефолтами: свежий, whatsapp, с телефоном."""
    kw.setdefault("channel", "whatsapp")
    kw.setdefault("last_message_at", NOW - timedelta(hours=1))
    kw.setdefault("bot_id", "getvisa")
    kw.setdefault("funnel", "visa")
    return Conversation(user_id=user_id, **kw)


async def _db(tmp_path, rows, name="backlog.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(DomainBase.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        session.add_all(rows)
        await session.commit()
    return engine, sm


async def _owners(sm):
    """{user_id: assigned_to} — зеркало панели."""
    async with sm() as session:
        rows = (await session.execute(select(Conversation))).scalars().all()
        return {r.user_id: (r.assigned_to or "") for r in rows}


async def _active(sm):
    """{(direction, manager)} — активные назначения в домене."""
    async with sm() as session:
        rows = (await session.execute(select(Assignment))).scalars().all()
        return {(r.direction, r.manager_id) for r in rows if r.active}


def _sync(coro_factory):
    """Тесты синхронные (как соседние в проекте): гоняем сценарий через asyncio.run."""
    flags.reset()
    asyncio.run(coro_factory())


# --------------------------------------------------------------------- визовый бэклог


def test_dry_run_changes_nothing(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv("getvisa:1", phone="996700000001"),
            _conv("getvisa:2", phone="996700000002"),
            _conv("getvisa:owned", phone="996700000003", assigned_to="medina"),
        ])
        summary = await run(sessionmaker=sm, sezim=False, now=NOW)
        assert summary["mode"] == "dry-run"
        assert sum(summary["visa"].values()) == 2
        assert await _owners(sm) == {
            "getvisa:1": "", "getvisa:2": "", "getvisa:owned": "medina"}
        assert await _active(sm) == set()          # домен тоже чист
        await engine.dispose()
    _sync(check)


def test_apply_assigns_mirrors_audits_and_is_idempotent(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv("getvisa:1", phone="996700000001"),
            _conv("getvisa:2", phone="996700000002"),
        ])
        first = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        second = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert sum(first["visa"].values()) == 2
        assert sum(second["visa"].values()) == 0   # повторный запуск — no-op
        assert await _active(sm) == {("visa", "medina"), ("visa", "eliza")}
        async with sm() as session:
            audits = (await session.execute(select(AuditLog))).scalars().all()
            assert len(audits) == 2
            assert all(a.detail.startswith(f"{REASON_VISA}: - -> ") for a in audits)
        await engine.dispose()
    _sync(check)


def test_visa_split_is_even_on_many_rows(tmp_path):
    """Ловит вырождение ротации: `assigned_at` из server_default в PG константен внутри
    транзакции, и без явной метки все строки после второй уезжали одному логину."""
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv(f"getvisa:{i}", phone=f"99670000{i:04d}") for i in range(1, 9)
        ])
        summary = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert summary["visa"] == {"medina": 4, "eliza": 4}
        await engine.dispose()
    _sync(check)


def test_dry_run_matches_apply_counts(tmp_path):
    async def check():
        rows = [_conv(f"getvisa:{i}", phone=f"99670000{i:04d}") for i in range(1, 7)]
        e1, sm1 = await _db(tmp_path, rows, name="preview.db")
        preview = await run(sessionmaker=sm1, sezim=False, now=NOW)
        e2, sm2 = await _db(tmp_path, [
            _conv(f"getvisa:{i}", phone=f"99670000{i:04d}") for i in range(1, 7)
        ], name="applied.db")
        applied = await run(sessionmaker=sm2, apply=True, sezim=False, now=NOW)
        assert preview["visa"] == applied["visa"]
        await e1.dispose()
        await e2.dispose()
    _sync(check)


def test_dry_run_raises_same_error_as_apply(tmp_path):
    """Оба режима падают одинаково: превью обязано ловить конфигурационную ошибку."""
    async def check():
        engine, sm = await _db(tmp_path, [_conv("getvisa:1", phone="996700000001")])
        await flags.set_flag("manager_off:medina", True)
        await flags.set_flag("manager_off:eliza", True)
        for apply in (False, True):
            with pytest.raises(RuntimeError, match="no available visa manager"):
                await run(sessionmaker=sm, apply=apply, sezim=False, now=NOW)
        await engine.dispose()
    _sync(check)


def test_manager_off_sends_everything_to_the_other(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv(f"getvisa:{i}", phone=f"99670000{i:04d}") for i in range(1, 5)
        ])
        await flags.set_flag("manager_off:medina", True)
        summary = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert summary["visa"] == {"eliza": 4}
        await engine.dispose()
    _sync(check)


def test_since_days_reports_fresh_and_total(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv("getvisa:fresh", phone="996700000001"),
            _conv("getvisa:stale", phone="996700000002", last_message_at=STALE),
        ])
        summary = await run(sessionmaker=sm, apply=True, sezim=False,
                            since_days=30, now=NOW)
        assert sum(summary["visa"].values()) == 1
        owners = await _owners(sm)
        assert owners["getvisa:stale"] == ""       # застойный не тронут
        assert owners["getvisa:fresh"] != ""
        await engine.dispose()
    _sync(check)


def test_since_days_zero_takes_everything(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv("getvisa:stale", phone="996700000002", last_message_at=STALE)])
        summary = await run(sessionmaker=sm, apply=True, sezim=False,
                            since_days=0, now=NOW)
        assert sum(summary["visa"].values()) == 1
        await engine.dispose()
    _sync(check)


def test_min_messages_separates_real_talk_from_a_hello(tmp_path):
    """На живых данных (бот в бою с 01.07, база младше месяца) отсечка по давности —
    no-op, и разделяет реальный разговор от «поздоровался и ушёл» число сообщений."""
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv("getvisa:talk", phone="996700000001"),
            _conv("getvisa:hello", phone="996700000002"),
        ])
        async with sm() as session:
            ids = {c.user_id: c.id for c in (await session.execute(
                select(Conversation))).scalars().all()}
            session.add_all(
                [ConvMessage(conversation_id=ids["getvisa:talk"], sender="client",
                             text=f"сообщение {i}") for i in range(4)]
                + [ConvMessage(conversation_id=ids["getvisa:hello"], sender="client",
                               text="здравствуйте")])
            await session.commit()
        summary = await run(sessionmaker=sm, apply=True, sezim=False,
                            min_messages=4, since_days=0, now=NOW)
        assert sum(summary["visa"].values()) == 1
        owners = await _owners(sm)
        assert owners["getvisa:talk"] != ""
        assert owners["getvisa:hello"] == ""
        await engine.dispose()
    _sync(check)


def test_third_manager_in_roster_no_keyerror(tmp_path, monkeypatch):
    async def check():
        monkeypatch.setattr(settings, "visa_manager_roster", ["medina", "eliza", "asel"])
        engine, sm = await _db(tmp_path, [
            _conv(f"getvisa:{i}", phone=f"99670000{i:04d}") for i in range(1, 7)
        ])
        summary = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert summary["visa"] == {"medina": 2, "eliza": 2, "asel": 2}
        await engine.dispose()
    _sync(check)


def test_null_assigned_to_is_ownerless(tmp_path):
    """На проде колонка nullable (self-heal-DDL без NOT NULL) — NULL обязан считаться
    бесхозным, иначе часть бэклога не видна скрипту вообще."""
    async def check():
        engine, sm = await _db(tmp_path, [_conv("getvisa:null", phone="996700000009")])
        async with sm() as session:
            conv = (await session.execute(
                select(Conversation))).scalar_one()
            conv.assigned_to = None
            await session.commit()
        summary = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert sum(summary["visa"].values()) == 1
        await engine.dispose()
    _sync(check)


def test_existing_domain_owner_only_repairs_mirror(tmp_path):
    """Владелец есть в домене, зеркало панели пустое → восстановить, НЕ переназначать."""
    async def check():
        engine, sm = await _db(tmp_path, [_conv("getvisa:1", phone="996700000001")])
        await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        async with sm() as session:                      # ломаем зеркало руками
            conv = (await session.execute(select(Conversation))).scalar_one()
            owner_before = conv.assigned_to
            conv.assigned_to = ""
            await session.commit()
        summary = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert summary["mirrors_repaired"] == 1
        assert (await _owners(sm))["getvisa:1"] == owner_before
        await engine.dispose()
    _sync(check)


def test_row_without_identity_is_skipped_not_guessed(tmp_path):
    """Ряд без телефона и без telegram-идентичности пропускается со счётчиком: иначе
    9-значный id молча стал бы выдуманным номером 996XXXXXXXXX с реальным владельцем."""
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv("getvisa_tg:123456789", phone="", channel="", bot_id="getvisa_tg"),
            _conv("getvisa:ok", phone="996700000001"),
        ])
        summary = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert summary["skipped"].get("нет идентичности") == 1
        assert sum(summary["visa"].values()) == 1
        assert (await _owners(sm))["getvisa_tg:123456789"] == ""
        await engine.dispose()
    _sync(check)


def test_foreign_whatsapp_numbers_are_assigned(tmp_path):
    """На проде 30.07 таких было 16 — иностранные клиенты канала (Турция, КЗ, УЗ, ОАЭ),
    у одного 22 сообщения. Раньше все уходили в skipped как ambiguous."""
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv("getvisa:tr", phone="905078174386"),      # Турция
            _conv("getvisa:kz", phone="77088657170"),       # Казахстан
            _conv("getvisa:uz", phone="998943236050"),      # Узбекистан
        ])
        summary = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert sum(summary["visa"].values()) == 3
        assert summary["skipped"] == {}
        assert all(v for v in (await _owners(sm)).values())
        await engine.dispose()
    _sync(check)


def test_telegram_row_uses_telegram_identity(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _conv("getvisa_tg:123456789", phone="", channel="telegram",
                  chat_id="123456789", bot_id="getvisa_tg"),
        ])
        summary = await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert sum(summary["visa"].values()) == 1
        async with sm() as session:
            from app.domain.models import ContactIdentity
            kinds = {i.identity_type: i.normalized_value for i in (await session.execute(
                select(ContactIdentity))).scalars().all()}
        assert kinds == {"telegram": "123456789"}     # номер НЕ выдуман
        await engine.dispose()
    _sync(check)


# ------------------------------------------------------- наследство Сезим и орфаны


def _tours(user_id, **kw):
    kw.setdefault("bot_id", "frunze_tours_sezim")
    kw.setdefault("funnel", "tours")
    return _conv(user_id, **kw)


def test_sezim_panel_owner_moves_to_new_owner(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("sezim:1", phone="996700000004", assigned_to="sezim"),
        ])
        summary = await run(sessionmaker=sm, apply=True, visa=False,
                            owner="aisina", now=NOW)
        assert summary["sezim_moved"] == 1
        assert (await _owners(sm))["sezim:1"] == "aisina"
        assert await _active(sm) == {("tours", "aisina")}
        async with sm() as session:
            audit = (await session.execute(select(AuditLog))).scalars().all()[-1]
            assert audit.detail == f"{REASON_SEZIM}: sezim -> aisina"
        await engine.dispose()
    _sync(check)


def test_sezim_domain_only_owner_also_moves(tmp_path):
    """Дыра зеркала: в панели пусто, в домене владелец Сезим. Раньше такие диалоги
    не переносились вообще и оставались закрыты для нового менеджера."""
    async def check():
        engine, sm = await _db(tmp_path, [_tours("sezim:mirror", phone="996700000007")])
        async with sm() as session:
            from app.domain import live_assign
            contact = await live_assign.contact_for_channel(
                session, channel="whatsapp", raw="996700000007")
            await live_assign.assign_locked(
                session, contact.id, "tours", "sezim",
                assigned_by="test", reason="legacy")
            await session.commit()
        summary = await run(sessionmaker=sm, apply=True, visa=False,
                            owner="aisina", now=NOW)
        assert summary["sezim_moved"] == 1
        assert await _active(sm) == {("tours", "aisina")}
        await engine.dispose()
    _sync(check)


def test_orphans_untouched_without_flag(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("sezim:1", phone="996700000004", assigned_to="sezim"),
            _tours("sezim:free", phone="996700000005"),
        ])
        summary = await run(sessionmaker=sm, apply=True, visa=False,
                            owner="aisina", now=NOW)
        assert summary["sezim_moved"] == 1
        assert summary["tours_orphans_moved"] == 0
        assert (await _owners(sm))["sezim:free"] == ""
        await engine.dispose()
    _sync(check)


def test_orphans_assigns_fresh_only_with_flag(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("sezim:free", phone="996700000005"),
            _tours("sezim:old", phone="996700000006", last_message_at=STALE),
        ])
        summary = await run(sessionmaker=sm, apply=True, visa=False,
                            tours_orphans=True, owner="aisina",
                            since_days=30, now=NOW)
        assert summary["tours_orphans_moved"] == 1
        owners = await _owners(sm)
        assert owners["sezim:free"] == "aisina"
        assert owners["sezim:old"] == ""            # застойный остаётся на потом
        await engine.dispose()
    _sync(check)


def test_foreign_owner_is_left_alone(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("sezim:ademi", phone="996700000008", assigned_to="ademi"),
        ])
        summary = await run(sessionmaker=sm, apply=True, visa=False,
                            tours_orphans=True, owner="aisina", now=NOW)
        assert summary["sezim_moved"] == 0
        assert (await _owners(sm))["sezim:ademi"] == "ademi"
        await engine.dispose()
    _sync(check)


def test_conflicting_domain_owner_is_collected_in_preview(tmp_path):
    """Превью собирает ВСЕ конфликты, применение падает на первом."""
    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("sezim:conflict", phone="996700000010", assigned_to="sezim"),
        ])
        async with sm() as session:
            from app.domain import live_assign
            contact = await live_assign.contact_for_channel(
                session, channel="whatsapp", raw="996700000010")
            await live_assign.assign_locked(
                session, contact.id, "tours", "ademi",
                assigned_by="test", reason="live")
            await session.commit()
        preview = await run(sessionmaker=sm, visa=False, owner="aisina", now=NOW)
        assert len(preview["conflicts"]) == 1
        assert preview["sezim_moved"] == 0
        with pytest.raises(RuntimeError, match="конфликт владельца"):
            await run(sessionmaker=sm, apply=True, visa=False, owner="aisina", now=NOW)
        assert (await _owners(sm))["sezim:conflict"] == "sezim"   # ничего не применилось
        await engine.dispose()
    _sync(check)


# ------------------------------------------------------------------------- откат


def test_rollback_restores_previous_owner(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("sezim:1", phone="996700000004", assigned_to="sezim"),
        ])
        await run(sessionmaker=sm, apply=True, visa=False, owner="aisina", now=NOW)
        assert (await _owners(sm))["sezim:1"] == "aisina"

        preview = await run(sessionmaker=sm, visa=False, rollback=REASON_SEZIM, now=NOW)
        assert preview["rolled_back"] == 1
        assert (await _owners(sm))["sezim:1"] == "aisina"        # превью не меняет

        done = await run(sessionmaker=sm, apply=True, visa=False,
                         rollback=REASON_SEZIM, now=NOW)
        assert done["rolled_back"] == 1
        assert (await _owners(sm))["sezim:1"] == "sezim"
        assert await _active(sm) == {("tours", "sezim")}

        again = await run(sessionmaker=sm, apply=True, visa=False,
                          rollback=REASON_SEZIM, now=NOW)
        assert again["rolled_back"] == 0                          # идемпотентно
        await engine.dispose()
    _sync(check)


def test_rollback_clears_owner_when_there_was_none(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [_conv("getvisa:1", phone="996700000001")])
        await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        assert (await _owners(sm))["getvisa:1"] != ""
        await run(sessionmaker=sm, apply=True, sezim=False,
                  rollback=REASON_VISA, now=NOW)
        assert (await _owners(sm))["getvisa:1"] == ""
        assert await _active(sm) == set()
        await engine.dispose()
    _sync(check)


def test_rollback_skips_rows_touched_by_a_human(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [_conv("getvisa:1", phone="996700000001")])
        await run(sessionmaker=sm, apply=True, sezim=False, now=NOW)
        async with sm() as session:                    # менеджер забрал диалог руками
            conv = (await session.execute(select(Conversation))).scalar_one()
            conv.assigned_to = "asel"
            await session.commit()
        summary = await run(sessionmaker=sm, apply=True, sezim=False,
                            rollback=REASON_VISA, now=NOW)
        assert summary["rolled_back"] == 0
        assert (await _owners(sm))["getvisa:1"] == "asel"
        await engine.dispose()
    _sync(check)


def test_unknown_rollback_reason_rejected(tmp_path):
    async def check():
        engine, sm = await _db(tmp_path, [])
        with pytest.raises(ValueError, match="неизвестный reason"):
            await run(sessionmaker=sm, rollback="whatever", now=NOW)
        await engine.dispose()
    _sync(check)


# --------------------------------------------------------------- PostgreSQL-ярус

_PG_DSN = os.environ.get("TEST_POSTGRES_DSN")
_pg_reason = ("POSTGRESQL VALIDATION SKIPPED — REQUIRED BEFORE PRODUCTION ROLLOUT "
              "(set TEST_POSTGRES_DSN to a dedicated, non-production test database)")


def _normalize_async_pg(dsn: str) -> str:
    for prefix, repl in (("postgresql+asyncpg://", None),
                         ("postgresql://", "postgresql+asyncpg://"),
                         ("postgres://", "postgresql+asyncpg://")):
        if dsn.startswith(prefix):
            return dsn if repl is None else repl + dsn[len(prefix):]
    return dsn


@pytest.mark.skipif(not _PG_DSN, reason=_pg_reason)
class TestPostgresTier:
    """Единственный ярус, где `SELECT ... FOR UPDATE` действительно блокирует: на SQLite
    он no-op, поэтому ровность раздачи и конкурентный запуск проверяем только здесь."""

    def test_split_is_even_and_concurrent_run_is_safe(self):
        async def scenario():
            engine = create_async_engine(_normalize_async_pg(_PG_DSN))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(DomainBase.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(DomainBase.metadata.create_all)
            sm = async_sessionmaker(engine, expire_on_commit=False)
            async with sm() as session:
                session.add_all([_conv(f"getvisa:{i}", phone=f"99670000{i:04d}")
                                 for i in range(1, 21)])
                await session.commit()
            # Два одновременных прогона: строки залочены, дублей владения быть не должно.
            first, second = await asyncio.gather(
                run(sessionmaker=sm, apply=True, sezim=False, batch_size=5, now=NOW),
                run(sessionmaker=sm, apply=True, sezim=False, batch_size=5, now=NOW),
                return_exceptions=True,
            )
            totals = [s for s in (first, second) if isinstance(s, dict)]
            assert totals, f"оба прогона упали: {first!r} / {second!r}"
            async with sm() as session:
                convs = (await session.execute(select(Conversation))).scalars().all()
                assert all((c.assigned_to or "") for c in convs)
                counts: dict[str, int] = {}
                for c in convs:
                    counts[c.assigned_to] = counts.get(c.assigned_to, 0) + 1
                # Ровность: ни один менеджер не забрал больше 60% пачки.
                assert max(counts.values()) <= 12, counts
                active = (await session.execute(
                    select(Assignment).where(Assignment.active.is_(True)))).scalars().all()
                assert len(active) == 20        # ровно одно активное на контакт
            await engine.dispose()
        _sync(scenario)


# ------------------------------------------------------- владелец-призрак (--departed)


DEPARTED_MAP = {"frunze_tours": "ademi", "frunze_tours_sezim": "aisina"}
LIVE_MANAGERS = [
    ManagerConfig(login="ademi", password="x"),
    ManagerConfig(login="aisina", password="x"),
    ManagerConfig(login="medina", password="x"),
]


def test_departed_owner_moves_to_channel_manager(tmp_path, monkeypatch):
    """Наследство уволившейся расползлось по ОБОИМ туровым каналам, а `--sezim` знает
    только один. Каждый диалог уходит менеджеру своего канала, не одному на всех."""
    monkeypatch.setattr(settings, "managers", LIVE_MANAGERS)
    monkeypatch.setattr(settings, "tours_owner_by_bot", DEPARTED_MAP)

    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("a:1", phone="996700000011", bot_id="frunze_tours",
                   assigned_to="sezim"),
            _tours("s:1", phone="996700000012", bot_id="frunze_tours_sezim",
                   assigned_to="sezim"),
            _tours("live:1", phone="996700000013", bot_id="frunze_tours",
                   assigned_to="ademi"),
        ])
        summary = await run(sessionmaker=sm, apply=True, visa=False, sezim=False,
                            departed=True, since_days=0, now=NOW)
        assert summary["departed_moved"] == 2
        owners = await _owners(sm)
        assert owners["a:1"] == "ademi"          # канал Адеми → Адеми
        assert owners["s:1"] == "aisina"         # канал Айсины → Айсине
        assert owners["live:1"] == "ademi"       # живого владельца не трогаем
        await engine.dispose()
    _sync(check)


def test_departed_dry_run_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "managers", LIVE_MANAGERS)
    monkeypatch.setattr(settings, "tours_owner_by_bot", DEPARTED_MAP)

    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("a:1", phone="996700000011", bot_id="frunze_tours",
                   assigned_to="sezim"),
        ])
        summary = await run(sessionmaker=sm, visa=False, sezim=False,
                            departed=True, since_days=0, now=NOW)
        assert summary["departed_moved"] == 1            # превью считает
        assert (await _owners(sm))["a:1"] == "sezim"     # но не меняет
        await engine.dispose()
    _sync(check)


def test_departed_rollback_returns_previous_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "managers", LIVE_MANAGERS)
    monkeypatch.setattr(settings, "tours_owner_by_bot", DEPARTED_MAP)

    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("a:1", phone="996700000011", bot_id="frunze_tours",
                   assigned_to="sezim"),
        ])
        await run(sessionmaker=sm, apply=True, visa=False, sezim=False,
                  departed=True, since_days=0, now=NOW)
        assert (await _owners(sm))["a:1"] == "ademi"
        await run(sessionmaker=sm, apply=True, rollback=REASON_DEPARTED, now=NOW)
        assert (await _owners(sm))["a:1"] == "sezim"
        await engine.dispose()
    _sync(check)


def test_departed_skips_channel_outside_the_map(tmp_path, monkeypatch):
    """Канал не в карте — не наш: чужие диалоги скрипт не раздаёт."""
    monkeypatch.setattr(settings, "managers", LIVE_MANAGERS)
    monkeypatch.setattr(settings, "tours_owner_by_bot", {"frunze_tours": "ademi"})

    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("tg:1", phone="996700000014", bot_id="frunze_tours_tg",
                   assigned_to="sezim"),
        ])
        summary = await run(sessionmaker=sm, apply=True, visa=False, sezim=False,
                            departed=True, since_days=0, now=NOW)
        assert summary["departed_moved"] == 0
        assert (await _owners(sm))["tg:1"] == "sezim"
        await engine.dispose()
    _sync(check)


def test_from_login_takes_service_account_dialogs(tmp_path, monkeypatch):
    """Служебный `admin` — живой логин, поэтому под «призрака» не попадает, но Telegram у
    него нет и пуш по его лидам уходить некуда. Забираем явным указанием оператора."""
    monkeypatch.setattr(settings, "managers",
                        LIVE_MANAGERS + [ManagerConfig(login="admin", password="x")])
    monkeypatch.setattr(settings, "tours_owner_by_bot", DEPARTED_MAP)

    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("adm:1", phone="996700000021", bot_id="frunze_tours_sezim",
                   assigned_to="admin"),
            _tours("keep:1", phone="996700000022", bot_id="frunze_tours_sezim",
                   assigned_to="aisina"),
        ])
        summary = await run(sessionmaker=sm, apply=True, visa=False, sezim=False,
                            from_logins=("admin",), since_days=0, now=NOW)
        assert summary["departed_moved"] == 1
        owners = await _owners(sm)
        assert owners["adm:1"] == "aisina"
        assert owners["keep:1"] == "aisina"          # уже её — трогать нечего
        await engine.dispose()
    _sync(check)


def test_owner_equal_to_channel_manager_is_not_touched(tmp_path, monkeypatch):
    """Диалог уже у менеджера канала — переносить нечего, лишней аудит-записи быть не должно."""
    monkeypatch.setattr(settings, "managers", LIVE_MANAGERS)
    monkeypatch.setattr(settings, "tours_owner_by_bot", DEPARTED_MAP)

    async def check():
        engine, sm = await _db(tmp_path, [
            _tours("own:1", phone="996700000023", bot_id="frunze_tours_sezim",
                   assigned_to="aisina"),
        ])
        summary = await run(sessionmaker=sm, apply=True, visa=False, sezim=False,
                            from_logins=("aisina",), since_days=0, now=NOW)
        assert summary["departed_moved"] == 0
        async with sm() as session:
            assert (await session.execute(select(AuditLog))).scalars().all() == []
        await engine.dispose()
    _sync(check)
