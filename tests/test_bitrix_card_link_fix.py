"""ГЕЙТ: ссылка 🗂 в уведомлении ведёт в карточку, которую менеджер реально открывает.

Написан ДО реализации, исполнителем НЕ редактируется. ТЗ: `docs/task-bitrix-card-link-fix.md`.

## Зачем

Замер прода 11.08.2026: из 21 визового пуша со ссылкой **12** вели в наш лид на служебном
аккаунте 155383 (его не видит ни один менеджер), **5** — в карточки i2crm 2024 года
уволенных сотрудников, и лишь **4** — в настоящую карточку Открытой линии.

Причина: `_ensure_lead` читал `settings.bitrix_prefer_openline_lead` (env, дефолт False),
а тумблер в панели пишет флаг в БД. Флаг стоял `t` — и не значил ничего.

## Что закреплено

1. Тумблер из БД управляет выбором карточки (env пуст — как на проде).
2. Снятый тумблер = прежнее поведение, но БЕЗ регресса на служебный аккаунт.
3. Пуш, у которого карточки ещё нет, ищет её сам — но НЕ создаёт (окно против дублей).
4. Портал недоступен → пуш уходит без ссылки. Заявка важнее ссылки.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.integrations.crm.bitrix24 as b24
from app.config import ManagerConfig, settings
from app.core import flags, instant_handoff
from app.integrations.crm import bitrix_mirror
from app.integrations.crm.db import Base, Conversation
from app.integrations.panel import store as ps

PORTAL = "https://getvisakg.bitrix24.kz"
KEY = "getvisa:996553250718"
PHONE = "996553250718"
NOW = datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc)

# Реальные формы SOURCE_ID с живого портала (проверено 06.08 и 11.08).
OPENLINE_VISA = {"ID": "185405", "SOURCE_ID": "27|2F099BC3-478D"}   # её открывает менеджер
OURS = {"ID": "185407", "SOURCE_ID": "CALL"}                        # наш лид, 155383
I2CRM_2024 = {"ID": "106217", "SOURCE_ID": "5|I2CRM"}               # уволенный сотрудник

MANAGERS = [ManagerConfig(login="medina", password="x", telegram_chat_id="7461236300"),
            ManagerConfig(login="eliza", password="x", telegram_chat_id="7461236301")]


class FakeAdapter:
    """Портал. Считает запросы: пуш не имеет права ходить в сеть без нужды."""

    def __init__(self, leads=None, *, boom=False):
        self.leads = list(leads or [])
        self.created: list[dict] = []
        self.lookups = 0
        self.boom = boom

    async def find_leads_by_phone(self, phone):
        self.lookups += 1
        if self.boom:
            raise RuntimeError("портал недоступен")
        return list(self.leads)

    async def find_lead_id_by_phone(self, phone):
        self.lookups += 1
        if self.boom:
            raise RuntimeError("портал недоступен")
        return self.leads[0]["ID"] if self.leads else ""

    async def create_lead(self, contact, funnel, data, assigned_by_id=""):
        self.created.append({"assigned_by_id": assigned_by_id})
        self.leads.append({"ID": "900", "SOURCE_ID": "CALL"})
        return "900"

    async def add_note(self, lead_id, text):
        return None


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(settings, "bitrix_mirror_enabled", True)
    # Ровно как на проде: переменной в env НЕТ, поведение задаёт только флаг в БД.
    monkeypatch.setattr(settings, "bitrix_prefer_openline_lead", False, raising=False)
    monkeypatch.setattr(settings, "bitrix_openline_wait_seconds", 600, raising=False)
    monkeypatch.setattr(settings, "bitrix_portal_url", PORTAL, raising=False)
    monkeypatch.setattr(settings, "bitrix_assignee_by_bot", {"getvisa": "96451"}, raising=False)
    monkeypatch.setattr(settings, "bitrix_assignee_by_manager",
                        {"medina": "96451", "eliza": "110841"}, raising=False)
    monkeypatch.setattr(settings, "managers", MANAGERS)
    monkeypatch.setattr(settings, "instant_handoff_enabled", True)
    monkeypatch.setattr(settings, "instant_handoff_digest_bots", [])
    monkeypatch.setattr(settings, "instant_handoff_cc_chat_ids", [])
    monkeypatch.setattr(settings, "admin_base_url", "https://panel.test")
    yield
    flags.reset()


def _with_portal(fake, coro_factory):
    orig, b24.Bitrix24Crm = b24.Bitrix24Crm, (lambda: fake)
    try:
        return asyncio.run(coro_factory())
    finally:
        b24.Bitrix24Crm = orig


def _mirror(fake, *, assigned_to="", bot_id="getvisa"):
    """Прод-порядок: реплика уже в панели, потом зеркалим."""
    async def scenario():
        store = ps.get_conversation_store()
        await store.ensure(KEY, bot_id=bot_id)
        if assigned_to:
            await store.update_meta(KEY, assigned_to=assigned_to)
        await store.add_message(KEY, sender="client", text="нужна виза в США")
        await bitrix_mirror.mirror_message(KEY, sender="client", text="нужна виза в США",
                                           phone=PHONE, funnel="visa", bot_id=bot_id)
        return await store.get(KEY)
    return _with_portal(fake, scenario)


async def _db(tmp_path, *, lead_id="", name="cardlink.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        session.add(Conversation(
            user_id=KEY, phone=PHONE, channel="whatsapp", bot_id="getvisa", funnel="visa",
            stage="manager", assigned_to="medina", bitrix_lead_id=lead_id,
            qualification={"name": "Камран", "visa_country": "США"},
            last_message_at=NOW - timedelta(minutes=4)))
        await session.commit()
    return engine, sm


def _push(fake, tmp_path, *, lead_id="", name="cardlink.db"):
    """Один пуш по готовой заявке. Возвращает текст, который увидел менеджер."""
    sent: list[tuple[str, str]] = []

    async def spy(login, text):
        sent.append((login, text))
        return True

    async def scenario():
        engine, sm = await _db(tmp_path, lead_id=lead_id, name=name)
        orig_send, instant_handoff._send = instant_handoff._send, spy
        try:
            await instant_handoff.maybe_notify(KEY, promised="Пригласил в офис",
                                               sessionmaker=sm)
        finally:
            instant_handoff._send = orig_send
        await engine.dispose()
    _with_portal(fake, scenario)
    return sent[0][1] if sent else ""


# --- 1-3: тумблер и отсутствие регресса на служебный аккаунт --------------------

def test_db_toggle_picks_openline_card():
    """Главный кейс. Тумблер включён в БД (env пуст) — берём карточку Открытой линии."""
    asyncio.run(flags.set_flag("bitrix_prefer_openline_lead", True))
    fake = FakeAdapter([I2CRM_2024, OURS, OPENLINE_VISA])
    conv = _mirror(fake)
    assert conv.bitrix_lead_id == OPENLINE_VISA["ID"]
    assert fake.created == [], "карточка есть — свою заводить нельзя"


def test_toggle_off_keeps_old_behaviour():
    """Снятый тумблер = прежнее поведение: первый лид по телефону, ничего не создаём."""
    fake = FakeAdapter([I2CRM_2024, OPENLINE_VISA])
    conv = _mirror(fake)
    assert conv.bitrix_lead_id == I2CRM_2024["ID"]
    assert fake.created == []


def test_no_lead_on_service_account_in_any_branch():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: тумблер снят, лидов нет — свой лид всё равно уходит менеджеру.

    Именно эта ветка породила 604 карточки на служебном 155383. Регресс закрыт в обеих.
    """
    fake = FakeAdapter([])
    _mirror(fake, assigned_to="medina")
    assert fake.created and fake.created[0]["assigned_by_id"] == "96451"


def test_owner_beats_channel_for_assignee():
    """На getvisa менеджеров двое — владелец диалога точнее карты по каналу."""
    fake = FakeAdapter([])
    _mirror(fake, assigned_to="eliza")
    assert fake.created and fake.created[0]["assigned_by_id"] == "110841"


def test_unknown_owner_falls_back_to_bot_map():
    fake = FakeAdapter([])
    _mirror(fake, assigned_to="kto-to")
    assert fake.created and fake.created[0]["assigned_by_id"] == "96451"


# --- 4-7: пуш ------------------------------------------------------------------

def test_push_resolves_card_when_missing(tmp_path):
    """Заявка готова через 4 минуты, карточка в диалоге ещё не записана — найти её."""
    asyncio.run(flags.set_flag("bitrix_prefer_openline_lead", True))
    fake = FakeAdapter([OURS, OPENLINE_VISA])
    text = _push(fake, tmp_path)
    assert f"{PORTAL}/crm/lead/details/{OPENLINE_VISA['ID']}/" in text
    assert fake.lookups == 1


def test_push_never_creates_a_lead(tmp_path):
    """Карточки нет вовсе: строки 🗂 нет, лид НЕ создан — окно против дублей цело."""
    asyncio.run(flags.set_flag("bitrix_prefer_openline_lead", True))
    fake = FakeAdapter([])
    text = _push(fake, tmp_path, name="nolead.db")
    assert "crm/lead/details" not in text and "🗂" not in text
    assert fake.created == []
    assert "Заявка готова" in text, "пуш обязан уйти и без ссылки"


def test_push_does_not_call_portal_when_card_known(tmp_path):
    """Карточка уже записана — лишнего запроса в портал быть не должно."""
    fake = FakeAdapter([OPENLINE_VISA])
    text = _push(fake, tmp_path, lead_id="185405", name="known.db")
    assert f"{PORTAL}/crm/lead/details/185405/" in text
    assert fake.lookups == 0


def test_push_survives_portal_failure(tmp_path):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: портал лежит — заявка всё равно доезжает до менеджера."""
    asyncio.run(flags.set_flag("bitrix_prefer_openline_lead", True))
    fake = FakeAdapter([OPENLINE_VISA], boom=True)
    text = _push(fake, tmp_path, name="boom.db")
    assert "Заявка готова" in text and "Камран" in text
    assert "crm/lead/details" not in text


def test_push_keeps_panel_and_whatsapp_links(tmp_path):
    """Ссылку в панель и WhatsApp не отбираем: туровые Битриксом не пользуются."""
    asyncio.run(flags.set_flag("bitrix_prefer_openline_lead", True))
    text = _push(FakeAdapter([OPENLINE_VISA]), tmp_path, name="links.db")
    assert "https://panel.test/admin/conversation/" in text
    assert "wa.me/996553250718" in text
