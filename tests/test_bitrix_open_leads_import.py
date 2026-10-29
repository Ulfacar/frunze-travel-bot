"""B4: перенос открытых лидов из архива Битрикса (CRITICAL). Только фикстуры и tmp-база.

Номера синтетические (996555100…). Портал не трогается: вход — JSONL архива.
"""
import asyncio
import io
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain import bitrix_lead_import as imp

ASSIGNEES = {"96451": "visa", "110841": "visa", "155267": "tours"}


def _lead(i, *phones, status="NEW", assignee="96451", contact=None):
    row = {"ID": str(i), "TITLE": f"Лид {i}", "STATUS_ID": status, "ASSIGNED_BY_ID": assignee,
           "PHONE": [{"VALUE": p, "VALUE_TYPE": "WORK"} for p in phones]}
    if contact:
        row["CONTACT_ID"] = contact
    return row


LEADS = [
    _lead(1, "+996 555 100 001"),                      # новый человек → создам
    _lead(1, "+996 555 100 001"),                      # повтор строки при выгрузке
    _lead(3, "0555100001"),                            # тот же человек в другом формате → свяжу
    _lead(4, "996 (555) 100-002", assignee=""),        # есть наш визовый диалог → свяжу, visa
    _lead(5, "+996555100005", "+996555100055"),        # общая карточка на двоих → реестр
    _lead(6),                                          # без телефона → реестр
    _lead(7, contact="70"),                            # телефон только в контакте
    _lead(8, "+996555100008", status="CONVERTED"),     # закрыт → не переносим
    _lead(9, "555100009"),                             # 9 цифр: правило legacy_match — реестр
    _lead(10, "+996555100010", assignee=""),           # диалоги в двух направлениях → реестр
    _lead(11, "+996555100011", assignee="999"),        # ответственный не в карте → реестр
    _lead(12, "+996555100012"),                        # наш диалог с этим лидом — другой номер
    _lead(13, "+7 701 123 45 67", assignee="155267"),  # иностранный номер, туры
]
CONTACTS = {"70": ["+996 555 100 007"]}


@pytest.fixture
def db(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'bot.db').as_posix()}"

    async def init():
        eng = create_async_engine(url)
        async with eng.begin() as conn:
            from app.domain.models import DomainBase
            from app.integrations.crm.db import Base
            await conn.run_sync(DomainBase.metadata.create_all)
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()
    asyncio.run(init())
    sm = async_sessionmaker(create_async_engine(url, poolclass=NullPool), expire_on_commit=False)

    async def seed():
        from app.integrations.crm.db import Conversation
        async with sm() as s:
            s.add_all([
                Conversation(user_id="getvisa:996555100002", phone="996555100002", bot_id="getvisa",
                             channel="whatsapp", funnel="visa"),
                Conversation(user_id="getvisa:996555100010", phone="996555100010", bot_id="getvisa",
                             channel="whatsapp", funnel="visa"),
                Conversation(user_id="frunze_tours_sezim:996555100010", phone="996555100010",
                             bot_id="frunze_tours_sezim", channel="whatsapp", funnel="tours"),
                Conversation(user_id="getvisa:996555100099", phone="996555100099", bot_id="getvisa",
                             channel="whatsapp", funnel="visa", bitrix_lead_id="12"),
            ])
            await s.commit()
    asyncio.run(seed())
    return {"url": url, "sm": sm}


def _plan(db=None, leads=LEADS):
    existing = imp.DbExisting(db["sm"]) if db else imp.Existing()
    return asyncio.run(imp.build_plan(leads, CONTACTS, existing, assignee_direction=ASSIGNEES))


def _by_id(plan):
    return {i.lead_id: i for i in plan.items}


def _count(sm, model):
    async def q():
        async with sm() as s:
            return await s.scalar(select(func.count()).select_from(model))
    return asyncio.run(q())


# ---------------------------- план ----------------------------

def test_plan_classifies_every_case(db):
    plan = _plan(db)
    got = {k: (v.action, v.direction) for k, v in _by_id(plan).items()}
    assert got == {
        "1": (imp.CREATE, "visa"), "3": (imp.LINK, "visa"), "4": (imp.LINK, "visa"),
        "5": (imp.MIXED, ""), "6": (imp.NO_PHONE, ""), "7": (imp.CREATE, "visa"),
        "9": (imp.BAD_PHONE, ""), "10": (imp.TWO_DIRECTIONS, ""), "11": (imp.NO_DIRECTION, ""),
        "12": (imp.FOREIGN_DIALOG, ""), "13": (imp.CREATE, "tours"),
    }
    assert plan.skipped_closed == 1 and plan.duplicate_rows == 1
    assert _by_id(plan)["4"].dialogs == ("getvisa:996555100002",)
    assert _by_id(plan)["13"].phone == "77011234567"


def test_plan_is_order_independent(db):
    a = _plan(db)
    b = _plan(db, leads=list(reversed(LEADS)))
    assert [(i.lead_id, i.action) for i in a.items] == [(i.lead_id, i.action) for i in b.items]


def test_dry_run_writes_nothing(db):
    from app.domain.models import Contact, ExternalReference, Request
    _plan(db)
    assert _count(db["sm"], Contact) == 0 and _count(db["sm"], Request) == 0
    assert _count(db["sm"], ExternalReference) == 0


def test_mixed_card_is_never_merged(db):
    """Общая карточка Открытой линии: оба номера остаются раздельными, ни один не связан."""
    asyncio.run(imp.apply_plan(db["sm"], _plan(db)))
    from app.domain.models import ContactIdentity
    async def q():
        async with db["sm"]() as s:
            return (await s.scalars(select(ContactIdentity.normalized_value))).all()
    values = asyncio.run(q())
    assert "996555100005" not in values and "996555100055" not in values


# ---------------------------- запись (только tmp-база) ----------------------------

def test_apply_then_second_run_changes_nothing(db):
    from app.domain.models import Contact, ExternalReference, Request
    from app.integrations.crm.db import Conversation

    async def _snap():
        async with db["sm"]() as s:
            return sorted((c.user_id, c.bitrix_lead_id, c.assigned_to or "")
                          for c in (await s.scalars(select(Conversation))).all())
    convs_before = asyncio.run(_snap())
    first = asyncio.run(imp.apply_plan(db["sm"], _plan(db)))
    assert first == {"contacts_created": 4, "requests_opened": 4, "references_created": 5, "errors": 0}
    # 4 человека: 100001 (лиды 1 и 3), 100002, 100007, 77011234567; лид 3 — в ту же заявку
    assert _count(db["sm"], Contact) == 4 and _count(db["sm"], Request) == 4
    assert _count(db["sm"], ExternalReference) == 5
    again = _plan(db)
    assert sum(1 for i in again.items if i.action == imp.DONE) == 5
    second = asyncio.run(imp.apply_plan(db["sm"], again))
    assert second == {"contacts_created": 0, "requests_opened": 0, "references_created": 0, "errors": 0}
    assert _count(db["sm"], ExternalReference) == 5
    # Диалоги панели не тронуты: ни новых, ни изменённых (bitrix_lead_id прежний).
    from app.integrations.crm.db import Conversation

    async def convs():
        async with db["sm"]() as s:
            return sorted((c.user_id, c.bitrix_lead_id, c.assigned_to or "")
                          for c in (await s.scalars(select(Conversation))).all())
    assert convs_before == asyncio.run(convs())


def test_existing_contact_and_open_request_are_reused(db):
    from app.domain.models import Contact, Request
    from app.domain.services import ContactService, RequestService

    async def seed():
        async with db["sm"]() as s:
            c = await ContactService.find_or_create_by_identity(s, "phone", "996555100002")
            await RequestService.open(s, c.id, "visa")
            await s.commit()
    asyncio.run(seed())
    changes = asyncio.run(imp.apply_plan(db["sm"], _plan(db)))
    assert changes["contacts_created"] == 3 and changes["requests_opened"] == 3
    assert _count(db["sm"], Contact) == 4 and _count(db["sm"], Request) == 4


# ---------------------------- скрипт ----------------------------

def _archive(tmp_path):
    d = tmp_path / "arch"
    d.mkdir()
    (d / "leads.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in LEADS))
    (d / "contacts.jsonl").write_text(json.dumps({"ID": "70", "PHONE": [{"VALUE": "+996 555 100 007"}]}) + "\n")
    return d


def _cli(*args):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import bitrix_open_leads_import as cli
    out = io.StringIO()
    code = asyncio.run(cli.run(list(args), stdout=out))
    return code, out.getvalue()


def test_cli_dry_run_masks_phones_and_writes_nothing(db, tmp_path):
    from app.domain.models import ExternalReference
    arch = _archive(tmp_path)
    code, text = _cli("--archive", str(arch), "--dsn", db["url"],
                      "--assignee", "visa=96451,110841", "--assignee", "tours=155267")
    assert code == 0 and "ничего не записано" in text and "mixed_card: 1" in text
    assert "996555100005" not in text and "996555100012" not in text and "***" in text
    assert _count(db["sm"], ExternalReference) == 0


def test_cli_write_requires_exact_db_name(db, tmp_path):
    from app.domain.models import ExternalReference
    arch = _archive(tmp_path)
    base = ["--archive", str(arch), "--dsn", db["url"], "--assignee", "visa=96451",
            "--assignee", "tours=155267"]
    assert _cli(*base, "--yes")[0] == 2
    assert _cli(*base, "--yes", "--confirm-db", "prod")[0] == 2
    assert _count(db["sm"], ExternalReference) == 0
    code, text = _cli(*base, "--yes", "--confirm-db", "bot.db")
    assert code == 0 and "references_created=5" in text
    code, text = _cli(*base, "--yes", "--confirm-db", "bot.db")
    assert "contacts_created=0, requests_opened=0, references_created=0" in text


def test_cli_without_db_plans_everything_as_new(tmp_path):
    code, text = _cli("--archive", str(_archive(tmp_path)), "--assignee", "visa=96451")
    assert code == 0 and "create_contact" in text and "link_existing" in text   # лид 3 — тот же номер
    assert _cli("--archive", str(tmp_path / "nope"))[0] == 2
