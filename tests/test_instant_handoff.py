"""P1.1: мгновенная передача готовой заявки владельцу диалога.

Проверяем ровно те свойства, которые обещаны заказчику и плану: один пуш на заявку,
владелец получает лично, «что бот пообещал» — буквальный текст клиенту, сбой отправки не
теряет заявку, канал на дайджесте мгновенных пушей не получает, флаг по умолчанию гасит
всё целиком.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import ManagerConfig, settings
from app.core import flags, instant_handoff
from app.integrations.crm.db import Base, Conversation

NOW = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)      # 02:00 по Бишкеку — ночь
MANAGERS = [
    ManagerConfig(login="aisina", password="x", telegram_chat_id="7461236387"),
    ManagerConfig(login="ademi", password="x", telegram_chat_id=""),
]


async def _db(tmp_path, rows, name="handoff.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        session.add_all(rows)
        await session.commit()
    return engine, sm


def _conv(user_id="frunze_tours_sezim:996700000001", **kw):
    kw.setdefault("phone", "996700000001")
    kw.setdefault("channel", "whatsapp")
    kw.setdefault("bot_id", "frunze_tours_sezim")
    kw.setdefault("funnel", "tours")
    kw.setdefault("stage", "manager")
    kw.setdefault("assigned_to", "aisina")
    kw.setdefault("qualification", {"name": "Айгуль", "destination": "Анталья",
                                    "budget": "до $2000"})
    kw.setdefault("last_message_at", NOW - timedelta(minutes=5))
    return Conversation(user_id=user_id, **kw)


class _Spy:
    """Подменяет отправку в Telegram: логин + текст, chat_id не трогаем."""

    def __init__(self, ok=True):
        self.sent: list[tuple[str, str]] = []
        self.ok = ok

    async def __call__(self, login, text):
        self.sent.append((login, text))
        return self.ok


def _run(scenario, monkeypatch, *, spy=None, digest_bots=(), enabled=True, cc=()):
    flags.reset()
    monkeypatch.setattr(settings, "managers", MANAGERS)   # manager_list() отдаёт их
    monkeypatch.setattr(settings, "instant_handoff_enabled", enabled)
    monkeypatch.setattr(settings, "instant_handoff_digest_bots", list(digest_bots))
    monkeypatch.setattr(settings, "instant_handoff_cc_chat_ids", list(cc))
    monkeypatch.setattr(settings, "admin_base_url", "https://panel.test")
    if spy is not None:
        monkeypatch.setattr(instant_handoff, "_send", spy)
    asyncio.run(scenario())


async def _notified_at(sm, user_id):
    async with sm() as session:
        conv = (await session.execute(select(Conversation).where(
            Conversation.user_id == user_id))).scalar_one()
        return conv.handoff_notified_at


# ------------------------------------------------------------------ мгновенный пуш


def test_sends_once_to_the_owner(tmp_path, monkeypatch):
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        first = await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001",
            promised="примерно $1600–1900, менеджер пришлёт точный расчёт",
            sessionmaker=sm)
        second = await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", promised="повтор", sessionmaker=sm)
        assert first is True and second is False        # ровно один пуш на заявку
        assert len(spy.sent) == 1
        login, text = spy.sent[0]
        assert login == "aisina"
        assert "Заявка готова" in text
        assert "Айгуль" in text and "+996 700 00 00 01" in text
        assert "Анталья" in text and "до $2000" in text
        assert "Бот пообещал: «примерно $1600–1900" in text
        assert "https://panel.test/admin/conversation/" in text
        assert await _notified_at(sm, "frunze_tours_sezim:996700000001") is not None
        await engine.dispose()
    _run(check, monkeypatch, spy=spy)


def test_promised_text_is_the_actual_reply(tmp_path, monkeypatch):
    """Менеджер обязан видеть буквально то, что бот сказал клиенту, иначе назовёт
    другую цену. Проверяем, что в пуш идёт reply, а не служебное поле карточки."""
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [
            _conv(manager_next_step="перезвонить утром", last_text="служебное")])
        await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001",
            promised="вилка $1600–1900, точный расчёт от менеджера", sessionmaker=sm)
        _, text = spy.sent[0]
        assert "вилка $1600–1900" in text
        assert "перезвонить утром" not in text and "служебное" not in text
        await engine.dispose()
    _run(check, monkeypatch, spy=spy)


def test_flag_off_sends_nothing(tmp_path, monkeypatch):
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        assert spy.sent == []
        assert await _notified_at(sm, "frunze_tours_sezim:996700000001") is None
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, enabled=False)


def test_runtime_flag_overrides_env_default(tmp_path, monkeypatch):
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        await flags.set_flag(instant_handoff.FLAG, True)
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is True
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, enabled=False)


def test_unfinished_dialog_is_not_pushed(tmp_path, monkeypatch):
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv(stage="qualification")])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        assert spy.sent == []
        await engine.dispose()
    _run(check, monkeypatch, spy=spy)


def test_office_stage_is_pushed_too(tmp_path, monkeypatch):
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv(stage="office")])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is True
        await engine.dispose()
    _run(check, monkeypatch, spy=spy)


def test_no_owner_leaves_claim_open_for_later(tmp_path, monkeypatch):
    """Владельца ещё нет → слать некому, но признак НЕ ставим: как только владелец
    появится, заявка уйдёт следующим ходом, а не потеряется навсегда."""
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv(assigned_to="")])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        assert await _notified_at(sm, "frunze_tours_sezim:996700000001") is None
        async with sm() as session:                     # владелец появился
            conv = (await session.execute(select(Conversation))).scalar_one()
            conv.assigned_to = "aisina"
            await session.commit()
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is True
        await engine.dispose()
    _run(check, monkeypatch, spy=spy)


def test_manager_without_chat_id_is_skipped_and_retriable(tmp_path, monkeypatch):
    async def check():
        engine, sm = await _db(tmp_path, [_conv(assigned_to="ademi")])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        # Признак снят обратно — заявка не потеряна.
        assert await _notified_at(sm, "frunze_tours_sezim:996700000001") is None
        await engine.dispose()
    _run(check, monkeypatch)                            # без spy: реальный _send


def test_send_failure_releases_the_claim(tmp_path, monkeypatch):
    spy = _Spy(ok=False)

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        assert len(spy.sent) == 1
        assert await _notified_at(sm, "frunze_tours_sezim:996700000001") is None
        spy.ok = True                                   # следующая попытка проходит
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is True
        await engine.dispose()
    _run(check, monkeypatch, spy=spy)


# ------------------------------------------------- копия владельцу бизнеса (Даулет)


class _CCSpy:
    """Подмена телеграм-слоя для копий: у владельца нет логина, только chat_id."""

    def __init__(self, ok=True):
        self.sent: list[tuple[str, str]] = []
        self.ok = ok

    def install(self, monkeypatch):
        from app.core import calendar_brief

        async def push(token, chat_id, text):
            self.sent.append((chat_id, text))
            return self.ok

        monkeypatch.setattr(calendar_brief, "_push_telegram", push)
        monkeypatch.setattr(calendar_brief, "_token", lambda: "token")
        return self


def test_owner_gets_a_copy_with_the_manager_named(tmp_path, monkeypatch):
    """Владелец видит оба направления. Без строки «Менеджер» он не поймёт, звонит ли
    кто-то уже, — копия без адресата бесполезна."""
    spy, cc = _Spy(), _CCSpy().install(monkeypatch)

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", promised="от $1600", sessionmaker=sm) is True
        assert [chat for chat, _ in cc.sent] == ["6217466575"]
        assert "Заявка готова" in cc.sent[0][1] and "Менеджер: aisina" in cc.sent[0][1]
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, cc=["6217466575"])


def test_copy_to_owner_survives_manager_without_chat_id(tmp_path, monkeypatch):
    """Заявка Медины сегодня утекла именно так. Копия ушла — значит заявку видят, и
    признак снимать НЕЛЬЗЯ: иначе владельцу летела бы та же карточка на каждом ходу."""
    cc = _CCSpy().install(monkeypatch)

    async def check():
        engine, sm = await _db(tmp_path, [_conv(assigned_to="ademi")])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        assert len(cc.sent) == 1
        assert await _notified_at(sm, "frunze_tours_sezim:996700000001") is not None
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        assert len(cc.sent) == 1                          # ровно одна копия на заявку
        await engine.dispose()
    _run(check, monkeypatch, cc=["6217466575"])           # без spy: реальный _send


def test_without_cc_the_claim_is_still_released(tmp_path, monkeypatch):
    """Без настроенных копий поведение прежнее: не дошло — заявка возвращается в очередь."""
    async def check():
        engine, sm = await _db(tmp_path, [_conv(assigned_to="ademi")])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        assert await _notified_at(sm, "frunze_tours_sezim:996700000001") is None
        await engine.dispose()
    _run(check, monkeypatch)


def test_broken_copy_never_blocks_the_manager_push(tmp_path, monkeypatch):
    """Копия — наблюдение, а не доставка: её сбой не имеет права стоить пуша менеджеру."""
    spy, cc = _Spy(), _CCSpy(ok=False).install(monkeypatch)

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is True
        assert len(spy.sent) == 1
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, cc=["6217466575"])


def test_exception_inside_never_propagates(tmp_path, monkeypatch):
    """Фича не имеет права ронять живой диалог."""
    async def boom(*a, **kw):
        raise RuntimeError("telegram упал")

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        monkeypatch.setattr(instant_handoff, "_send", boom)
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        await engine.dispose()
    _run(check, monkeypatch)


def test_works_at_night(tmp_path, monkeypatch):
    """«Ночью тоже слать» — ночной режим гасит ответы бота, но не этот пуш."""
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        assert NOW.hour == 20                           # 02:00 по Бишкеку
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is True
        await engine.dispose()
    _run(check, monkeypatch, spy=spy)


# ----------------------------------------------------------------------- дайджест


def test_digest_channel_gets_no_instant_push(tmp_path, monkeypatch):
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        assert await instant_handoff.maybe_notify(
            "frunze_tours_sezim:996700000001", sessionmaker=sm) is False
        assert spy.sent == []
        # Признак не тронут — заявку заберёт дайджест.
        assert await _notified_at(sm, "frunze_tours_sezim:996700000001") is None
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, digest_bots=["frunze_tours_sezim"])


def test_digest_packs_by_manager_and_claims_once(tmp_path, monkeypatch):
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [
            _conv("frunze_tours_sezim:996700000001", phone="996700000001"),
            _conv("frunze_tours_sezim:996700000002", phone="996700000002",
                  qualification={"name": "Бакыт", "destination": "Дубай"}),
        ])
        sent = await instant_handoff.run_digest(now=NOW, sessionmaker=sm, force=True)
        assert sent == 1                                # одна пачка на менеджера
        login, text = spy.sent[0]
        assert login == "aisina"
        assert "Готовые заявки" in text and "Всего: 2" in text
        assert "Айгуль" in text and "Бакыт" in text
        again = await instant_handoff.run_digest(now=NOW, sessionmaker=sm, force=True)
        assert again == 0                               # повторно те же не уходят
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, digest_bots=["frunze_tours_sezim"])


def test_digest_silent_outside_its_hours(tmp_path, monkeypatch):
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        assert await instant_handoff.run_digest(now=NOW, sessionmaker=sm) == 0
        assert spy.sent == []
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, digest_bots=["frunze_tours_sezim"])


def test_digest_fires_in_its_hour(tmp_path, monkeypatch):
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        at_15 = NOW.replace(hour=9, minute=5)           # 15:05 по Бишкеку
        assert await instant_handoff.run_digest(now=at_15, sessionmaker=sm) == 1
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, digest_bots=["frunze_tours_sezim"])


def test_digest_slot_fires_once_despite_5min_ticks(tmp_path, monkeypatch):
    """Планировщик тикает раз в 5 минут: без флага слота 15:00 разослал бы 12 пачек."""
    spy = _Spy()

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        at_15_00 = NOW.replace(hour=9, minute=0)        # 15:00 по Бишкеку
        at_15_05 = NOW.replace(hour=9, minute=5)
        assert await instant_handoff.run_digest(now=at_15_00, sessionmaker=sm) == 1
        async with sm() as session:                     # подъехала новая готовая заявка
            session.add(_conv("frunze_tours_sezim:996700000002", phone="996700000002"))
            await session.commit()
        assert await instant_handoff.run_digest(now=at_15_05, sessionmaker=sm) == 0
        assert len(spy.sent) == 1                       # слот уже отработан
        at_19 = NOW.replace(hour=13, minute=0)          # следующий слот — 19:00
        assert await instant_handoff.run_digest(now=at_19, sessionmaker=sm) == 1
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, digest_bots=["frunze_tours_sezim"])


def test_digest_failure_releases_claims(tmp_path, monkeypatch):
    spy = _Spy(ok=False)

    async def check():
        engine, sm = await _db(tmp_path, [_conv()])
        assert await instant_handoff.run_digest(now=NOW, sessionmaker=sm,
                                                force=True) == 0
        assert await _notified_at(sm, "frunze_tours_sezim:996700000001") is None
        await engine.dispose()
    _run(check, monkeypatch, spy=spy, digest_bots=["frunze_tours_sezim"])


# ------------------------------------------------------------------------- прочее


@pytest.mark.parametrize("qualification,expected", [
    ({"destination": "Анталья", "dates": "10-17 авг"}, "Анталья · 10-17 авг"),
    ({"visa_country": "Германия"}, "Германия"),
    ({}, "Туры"),
])
def test_request_line_shows_what_there_is(qualification, expected):
    assert instant_handoff._request_line(qualification, "tours") == expected


def test_long_promise_is_capped():
    text = instant_handoff.render_handoff_text(
        name="A", phone="+996", request="r", promised="я" * 500, link="")
    assert "…" in text and len(text) < 400
