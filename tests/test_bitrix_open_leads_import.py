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
    assert first == {"contacts_created": 4, "requests_opened": 4, "references_created": 5,
                     "errors": 0, "failed": []}
    # 4 человека: 100001 (лиды 1 и 3), 100002, 100007, 77011234567; лид 3 — в ту же заявку
    assert _count(db["sm"], Contact) == 4 and _count(db["sm"], Request) == 4
    assert _count(db["sm"], ExternalReference) == 5
    again = _plan(db)
    assert sum(1 for i in again.items if i.action == imp.DONE) == 5
    second = asyncio.run(imp.apply_plan(db["sm"], again))
    assert second == {"contacts_created": 0, "requests_opened": 0, "references_created": 0,
                      "errors": 0, "failed": []}
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
    code, text = _cli(*base, "--yes", "--confirm-db", _target(db))
    assert code == 0 and "references_created=5" in text
    code, text = _cli(*base, "--yes", "--confirm-db", _target(db))
    assert "contacts_created=0, requests_opened=0, references_created=0" in text


def test_cli_without_db_plans_everything_as_new(tmp_path):
    code, text = _cli("--archive", str(_archive(tmp_path)), "--assignee", "visa=96451")
    assert code == 0 and "create_contact" in text and "link_existing" in text   # лид 3 — тот же номер
    assert _cli("--archive", str(tmp_path / "nope"))[0] == 2


# ------------------- ревью pdf 30.10 (раздел 1) -------------------

def test_ten_digit_plus_number_goes_to_registry_not_lost(db):
    """1.1: «+65 6123 4567» план называл create_contact, а запись падала на повторной
    нормализации — errors=N, лид не перенесён и не в реестре. Теперь — реестр с причиной."""
    from app.domain.models import ContactIdentity, ExternalReference
    leads = [_lead(21, "+65 6123 4567"), _lead(22, "+45 12 34 56 78"), _lead(1, "+996 555 100 001")]
    plan = _plan(db, leads=leads)
    got = _by_id(plan)
    assert got["21"].action == imp.BAD_PHONE and got["22"].action == imp.BAD_PHONE
    assert "повторн" in got["21"].detail
    assert got["1"].action == imp.CREATE
    changes = asyncio.run(imp.apply_plan(db["sm"], plan))
    assert changes["errors"] == 0 and changes["references_created"] == 1
    assert _count(db["sm"], ExternalReference) == 1 and _count(db["sm"], ContactIdentity) == 1


def test_every_planned_phone_survives_the_write_normalization(db):
    """Контракт «сухой прогон = запись»: всё, что план создаёт или связывает, проходит ту
    же нормализацию, что и `find_or_create_by_identity(assume_e164=True)`."""
    from app.domain.phones import normalize_phone
    for item in _plan(db).items:
        if item.action in (imp.CREATE, imp.LINK):
            assert normalize_phone(item.phone, assume_e164=True) == item.phone


def test_trunk_eight_without_plus_is_checked_by_hand(db):
    """1.3: «8 999 123 45 67» без «+» — это и 8…, и +7…: не создаём фантомную личность."""
    from app.domain.models import ContactIdentity
    plan = _plan(db, leads=[_lead(23, "8 999 123 45 67"), _lead(24, contact="80")])
    got = _by_id(plan)
    assert got["23"].action == imp.CHECK_BY_HAND and "вручную" in got["23"].detail
    assert imp.CHECK_BY_HAND in imp.PROBLEMS
    plan2 = asyncio.run(imp.build_plan([_lead(24, contact="80")], {"80": ["8(999)1234567"]},
                                       imp.DbExisting(db["sm"]), assignee_direction=ASSIGNEES))
    assert _by_id(plan2)["24"].action == imp.CHECK_BY_HAND
    asyncio.run(imp.apply_plan(db["sm"], plan))
    assert _count(db["sm"], ContactIdentity) == 0


def test_write_error_names_the_lead_without_the_number(db, tmp_path, monkeypatch):
    """Любая ошибка записи — с ID лида и классом ошибки; номер и текст SQL не печатаем."""
    from app.domain import services
    real = services.ContactService.find_or_create_by_identity

    async def boom(session, kind, value, **kw):
        if value == "996555100002":
            raise RuntimeError("INSERT ... parameters ('996555100002',)")
        return await real(session, kind, value, **kw)
    monkeypatch.setattr(services.ContactService, "find_or_create_by_identity", boom)
    plan = _plan(db)
    changes = asyncio.run(imp.apply_plan(db["sm"], plan))
    assert changes["errors"] == 1
    assert changes["failed"] == [("4", "RuntimeError")]
    arch = _archive(tmp_path)
    code, text = _cli("--archive", str(arch), "--dsn", db["url"], "--assignee", "visa=96451",
                      "--assignee", "tours=155267", "--yes", "--confirm-db", _target(db))
    assert "errors=" in text and "ошибка записи: лид 4: RuntimeError" in text
    assert "996555100002" not in text and "INSERT" not in text


def test_mask_keeps_only_last_four_digits():
    """1.4: раньше `9965***0001` — 8 из 12 цифр."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import bitrix_open_leads_import as cli
    assert cli.mask("996555100001") == "***0001"
    assert cli.mask("77011234567") == "***4567"
    assert cli.mask("12345") == "***"


def _target(db):
    from pathlib import Path
    return "sqlite:" + str(Path(db["url"].split(":///", 1)[1]).resolve())


def test_confirm_db_checks_host_port_and_name(db, tmp_path):
    """1.2: одно имя базы на другом хосте или в другом каталоге — не та база."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import bitrix_open_leads_import as cli
    a = cli._db_target("postgresql+asyncpg://u:secret@10.0.0.1/frunze")
    b = cli._db_target("postgresql+asyncpg://u:secret@127.0.0.1/frunze")
    assert a == "10.0.0.1:5432/frunze" and a != b and "secret" not in a
    assert cli._db_target("postgresql+asyncpg://u:p@10.0.0.1:6543/frunze") == "10.0.0.1:6543/frunze"
    from app.domain.models import ExternalReference
    arch = _archive(tmp_path)
    base = ["--archive", str(arch), "--dsn", db["url"], "--assignee", "visa=96451",
            "--assignee", "tours=155267", "--yes", "--confirm-db"]
    assert _cli(*base, "bot.db")[0] == 2                              # только имя — мало
    assert _cli(*base, "sqlite:" + str(tmp_path / "other" / "bot.db"))[0] == 2
    assert _count(db["sm"], ExternalReference) == 0
    code, text = _cli(*base, _target(db))
    assert code == 0 and "references_created=5" in text
