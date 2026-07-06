"""Зеркалирование диалога в Bitrix (лид + комментарии). Адаптер мокаем — портал не трогаем."""
import asyncio

from app.integrations.crm import bitrix_mirror
from app.integrations.panel import store as ps


class FakeAdapter:
    def __init__(self):
        self.created = []
        self.comments = []
        self.found = ""          # что вернёт поиск по телефону
        self.raise_on = None     # 'find' | 'create' | 'note' → бросить

    async def find_lead_id_by_phone(self, phone):
        await asyncio.sleep(0)               # уступаем управление — воспроизводим гонку
        if self.raise_on == "find":
            raise RuntimeError("boom")
        return self.found

    async def create_lead(self, contact, funnel, data):
        await asyncio.sleep(0)               # уступаем управление — воспроизводим гонку
        if self.raise_on == "create":
            raise RuntimeError("boom")
        self.created.append((contact, funnel, data))
        return "700"

    async def add_note(self, lead_id, text):
        if self.raise_on == "note":
            raise RuntimeError("boom")
        self.comments.append((lead_id, text))


def _setup(monkeypatch, fake, *, enabled=True, webhook="https://portal/rest/1/tok"):
    ps._memory_store._conv.clear()
    from app.core import flags
    flags.reset()
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix24_webhook_url", webhook)
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_mirror_enabled", enabled)
    monkeypatch.setattr("app.integrations.crm.bitrix24.Bitrix24Crm", lambda: fake)
    store = ps.get_conversation_store()
    asyncio.run(store.add_message("getvisa:99", "client", "привет", channel="whatsapp",
                                  bot_id="getvisa", chat_id="99@c.us", phone="996700099"))
    asyncio.run(store.update_meta("getvisa:99", funnel="visa", qualification={"name": "Иван"}))
    return store


def test_mirror_disabled_without_webhook(monkeypatch):
    fake = FakeAdapter()
    _setup(monkeypatch, fake, webhook="")
    asyncio.run(bitrix_mirror.mirror_message(
        "getvisa:99", sender="bot", text="ответ", phone="996700099", funnel="visa"))
    assert fake.created == [] and fake.comments == []


def test_mirror_disabled_by_flag(monkeypatch):
    fake = FakeAdapter()
    _setup(monkeypatch, fake, enabled=False)
    asyncio.run(bitrix_mirror.mirror_message(
        "getvisa:99", sender="bot", text="ответ", phone="996700099", funnel="visa"))
    assert fake.created == [] and fake.comments == []


def test_mirror_creates_lead_and_comments(monkeypatch):
    fake = FakeAdapter()
    store = _setup(monkeypatch, fake)
    asyncio.run(bitrix_mirror.mirror_message(
        "getvisa:99", sender="bot", text="Здравствуйте!", phone="996700099", funnel="visa"))
    assert len(fake.created) == 1                      # создан лид
    assert fake.comments == [("700", "[Бот] Здравствуйте!")]
    conv = asyncio.run(store.get("getvisa:99"))
    assert conv.bitrix_lead_id == "700"               # id закэширован на карточке


def test_mirror_reuses_cached_lead(monkeypatch):
    fake = FakeAdapter()
    store = _setup(monkeypatch, fake)
    asyncio.run(store.update_meta("getvisa:99", bitrix_lead_id="555"))
    asyncio.run(bitrix_mirror.mirror_message(
        "getvisa:99", sender="client", text="ещё вопрос", phone="996700099", funnel="visa"))
    assert fake.created == []                           # не создаём — есть кэш
    assert fake.comments == [("555", "[Клиент] ещё вопрос")]


def test_mirror_dedup_by_phone(monkeypatch):
    fake = FakeAdapter()
    fake.found = "888"                                 # лид уже есть в Bitrix
    store = _setup(monkeypatch, fake)
    asyncio.run(bitrix_mirror.mirror_message(
        "getvisa:99", sender="manager", text="я на связи", phone="996700099", funnel="visa"))
    assert fake.created == []                           # нашли по телефону → не дублируем
    assert fake.comments == [("888", "[Менеджер] я на связи")]
    assert asyncio.run(store.get("getvisa:99")).bitrix_lead_id == "888"


def test_mirror_never_raises_on_adapter_error(monkeypatch):
    fake = FakeAdapter()
    fake.raise_on = "create"
    _setup(monkeypatch, fake)
    # Не должно бросить — сбой Bitrix не роняет диалог.
    asyncio.run(bitrix_mirror.mirror_message(
        "getvisa:99", sender="bot", text="ответ", phone="996700099", funnel="visa"))
    assert fake.comments == []


def test_mirror_no_duplicate_lead_under_concurrency(monkeypatch):
    """Гонка: client-хук и bot-хук на быстрый ответ создали бы 2 лида — лок держит ОДИН."""
    fake = FakeAdapter()
    store = _setup(monkeypatch, fake)

    async def both():
        await asyncio.gather(
            bitrix_mirror.mirror_message("getvisa:99", sender="client", text="привет",
                                         phone="996700099", funnel="visa"),
            bitrix_mirror.mirror_message("getvisa:99", sender="bot", text="здравствуйте",
                                         phone="996700099", funnel="visa"),
        )

    asyncio.run(both())
    assert len(fake.created) == 1                      # ровно один лид, несмотря на 2 хука
    assert len(fake.comments) == 2                     # оба комментария легли
    assert all(cid == "700" for cid, _ in fake.comments)
    assert asyncio.run(store.get("getvisa:99")).bitrix_lead_id == "700"


def test_mirror_skips_empty_text(monkeypatch):
    fake = FakeAdapter()
    _setup(monkeypatch, fake)
    asyncio.run(bitrix_mirror.mirror_message(
        "getvisa:99", sender="bot", text="   ", phone="996700099", funnel="visa"))
    assert fake.created == [] and fake.comments == []
