"""ГЕЙТ задачи «бот пишет в ту карточку, которую открывает менеджер».

Написан ДО реализации и исполнителем НЕ редактируется. Кажется, что тест неверный —
остановись и спроси, не правь.

## Зачем (разобрано на живом портале 06.08.2026)

В Битрикс идут ДВА параллельных потока лидов на одного клиента:

* интеграция Wappi через Открытые линии — `SOURCE_ID` вида `25|02A4708D-EC6C`
  (линия | профиль). Ответственный проставлен очередью линии: Медина 96451,
  Элиза 110841, Адеми 155313, Айсина 155267. **Девочки работают ЗДЕСЬ.**
* наш бот — `SOURCE_ID` = `CALL`, 604 лида, ВСЕ на служебном аккаунте 155383,
  под которым выпущен вебхук. **Сюда не смотрит никто.**

Переписка бота есть — 26 комментариев в карточке проверено живьём. Просто лежит
в карточке, которой менеджер не видит: в Битриксе менеджер видит только свои лиды.

Причина дублей — ГОНКА: из 12 наших лидов у 6 есть близнец от Wappi, созданный в ту
же минуту (соседние ID). Оба создаются за секунды друг от друга, ни один не успевает
увидеть чужой. Поиск по телефону в коде есть и работает (формат с `+` и без — оба
находятся), просто в момент проверки чужого лида ещё нет.

## Требуется от реализации

    app/integrations/crm/bitrix_mirror.py
        _pick_lead(leads: list[dict]) -> str
            Выбрать целевой лид: лид Открытой линии приоритетнее нашего.
        async _resolve_lead(...) -> str
            Найти лид Открытой линии; если нет — подождать, и только по истечении
            окна создать свой (с ответственным) и выгрузить в него ВСЮ историю.

    app/integrations/crm/bitrix24.py
        async find_leads_by_phone(phone) -> list[dict]   # id + SOURCE_ID
        create_lead(..., assigned_by_id=...)

Флаг: `bitrix_prefer_openline_lead` (дефолт False — поведение не меняется).
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import flags
from app.integrations.crm import bitrix_mirror
from app.integrations.panel import store as ps

KEY = "getvisa:996700111222"
PHONE = "996700111222"

# Как выглядит SOURCE_ID лида Открытой линии на живом портале: "<линия>|<профиль Wappi>".
OPENLINE = {"ID": "185305", "SOURCE_ID": "25|02A4708D-EC6C"}
OPENLINE_VISA = {"ID": "185301", "SOURCE_ID": "27|2F099BC3-478D"}
OURS = {"ID": "185307", "SOURCE_ID": "CALL"}
OLD_MANUAL = {"ID": "63493", "SOURCE_ID": "CALL"}


class FakeAdapter:
    def __init__(self, leads=None):
        self.leads = list(leads or [])
        self.created: list[dict] = []
        self.comments: list[tuple[str, str]] = []

    async def find_leads_by_phone(self, phone):
        await asyncio.sleep(0)                 # уступаем управление — воспроизводим гонку
        return list(self.leads)

    async def find_lead_id_by_phone(self, phone):
        await asyncio.sleep(0)
        return self.leads[0]["ID"] if self.leads else ""

    async def create_lead(self, contact, funnel, data, assigned_by_id=""):
        await asyncio.sleep(0)
        self.created.append({"contact": contact, "funnel": funnel,
                             "assigned_by_id": assigned_by_id})
        new = {"ID": "900", "SOURCE_ID": "CALL"}
        self.leads.append(new)
        return new["ID"]

    async def add_note(self, lead_id, text):
        self.comments.append((str(lead_id), text))


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_mirror_enabled", True)
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_prefer_openline_lead", True, raising=False)
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_openline_wait_seconds", 600, raising=False)
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_assignee_by_bot",
                        {"getvisa": "96451", "frunze_tours": "155313",
                         "frunze_tours_sezim": "155267"}, raising=False)
    yield
    flags.reset()


def _mirror(fake, sender="client", text="привет", bot_id="getvisa"):
    """Повторяет прод-порядок: реплика сначала ложится в панель, потом зеркалится.

    В оркестраторе `_log_in` идёт ДО `bitrix_mirror.fire` — значит к моменту зеркала
    текущее сообщение уже в истории. Без этого тест проверял бы не то, что бывает в бою.
    """
    import app.integrations.crm.bitrix24 as b24
    store = ps.get_conversation_store()
    run(store.ensure(KEY, bot_id=bot_id))
    run(store.add_message(KEY, sender=sender, text=text))
    orig, b24.Bitrix24Crm = b24.Bitrix24Crm, (lambda: fake)
    try:
        run(bitrix_mirror.mirror_message(KEY, sender=sender, text=text, phone=PHONE,
                                         funnel="visa", bot_id=bot_id))
    finally:
        b24.Bitrix24Crm = orig


# --- выбор карточки ------------------------------------------------------------

def test_prefers_openline_lead_over_ours():
    """Главный кейс. Есть оба лида — пишем в тот, который открывает менеджер."""
    assert bitrix_mirror._pick_lead([OURS, OPENLINE]) == "185305"
    assert bitrix_mirror._pick_lead([OPENLINE, OURS]) == "185305"


def test_uses_existing_lead_when_no_openline():
    """Лида Открытой линии нет, но есть старый ручной — пишем в него, новый не плодим."""
    assert bitrix_mirror._pick_lead([OLD_MANUAL]) == "63493"


def test_no_leads_at_all():
    assert bitrix_mirror._pick_lead([]) == ""


def test_openline_source_is_recognised_for_every_line():
    """Формат «линия|профиль» — единственный признак лида Открытой линии.
    Ошибка здесь = снова пишем не туда, поэтому проверяем все три живые линии."""
    for lead in (OPENLINE, OPENLINE_VISA, {"ID": "1", "SOURCE_ID": "23|6A74FB33-16AA"}):
        assert bitrix_mirror._pick_lead([OURS, lead]) == lead["ID"]


def test_writes_comment_into_openline_lead_and_creates_nothing():
    fake = FakeAdapter([OPENLINE])
    _mirror(fake)
    assert fake.created == [], "лид Открытой линии есть — свой создавать нельзя"
    assert [lid for lid, _ in fake.comments] == ["185305"]


# --- гонка: лида ещё нет --------------------------------------------------------

def test_first_message_does_not_create_lead():
    """Ждём, пока Wappi создаст свой. Ничего не теряем: переписка есть у нас в панели.

    Из 12 наших лидов у 6 близнец появился в ту же минуту — если не подождать,
    дубль гарантирован в половине случаев.
    """
    fake = FakeAdapter([])
    _mirror(fake)
    assert fake.created == [], "на первом сообщении свой лид не создаём"
    assert fake.comments == []


def test_openline_lead_appearing_later_is_picked_up():
    """Wappi создал лид через несколько секунд — со второго сообщения пишем туда."""
    fake = FakeAdapter([])
    _mirror(fake, text="первое")
    fake.leads.append(OPENLINE)              # Wappi успел
    _mirror(fake, text="второе")
    assert fake.created == []
    assert [lid for lid, _ in fake.comments] == ["185305", "185305"], \
        "после находки выгружаем ВСЮ историю, а не только последнюю реплику"


def test_own_lead_created_after_wait_window_with_full_history(monkeypatch):
    """Окно вышло, Wappi лида так и не создал — создаём свой и не теряем историю."""
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_openline_wait_seconds", 0, raising=False)
    fake = FakeAdapter([])
    _mirror(fake, text="первое")
    _mirror(fake, text="второе")
    assert len(fake.created) == 1, "ровно один свой лид"
    assert len(fake.comments) >= 2, "история выгружена целиком"


def test_fallback_lead_gets_right_assignee(monkeypatch):
    """Свой лид обязан попасть менеджеру, а не служебному аккаунту 155383 —
    иначе повторяем ровно ту ошибку, из-за которой 604 карточки никто не видит."""
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_openline_wait_seconds", 0, raising=False)
    fake = FakeAdapter([])
    _mirror(fake, bot_id="frunze_tours")
    assert fake.created and fake.created[0]["assigned_by_id"] == "155313"


def test_unknown_bot_creates_lead_without_assignee(monkeypatch):
    """Бота нет в карте — лид всё равно создаём (не терять данные), просто без владельца."""
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_openline_wait_seconds", 0, raising=False)
    fake = FakeAdapter([])
    _mirror(fake, bot_id="unknown_bot")
    assert fake.created and not fake.created[0]["assigned_by_id"]


# --- инварианты, которые нельзя нарушить ---------------------------------------

def test_never_two_leads_for_one_dialog(monkeypatch):
    """Два сообщения подряд не должны породить два лида (гонка client/bot хуков)."""
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_openline_wait_seconds", 0, raising=False)
    fake = FakeAdapter([])
    _mirror(fake, sender="client", text="раз")
    _mirror(fake, sender="bot", text="два")
    _mirror(fake, sender="client", text="три")
    assert len(fake.created) == 1


def test_flag_off_keeps_old_behaviour(monkeypatch):
    """Дефолт — прежнее поведение: выкатываем выключенным.

    Прежний код брал ПЕРВЫЙ найденный лид, не разбирая, чей он. Здесь первым идёт наш
    (OURS) — со снятым флагом он и должен выиграть, с поднятым выигрывает лид
    Открытой линии. Это и есть разница, которую переключает флаг.
    """
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix_prefer_openline_lead", False, raising=False)
    fake = FakeAdapter([OURS, OPENLINE])
    _mirror(fake)
    assert fake.created == [], "лид по телефону найден — создавать не надо"
    assert [lid for lid, _ in fake.comments] == ["185307"], "старое поведение: первый попавшийся"


def test_mirror_never_raises():
    """Зеркало не имеет права уронить диалог с клиентом."""
    class Boom(FakeAdapter):
        async def find_leads_by_phone(self, phone):
            raise RuntimeError("портал лёг")

    _mirror(Boom([]))          # не должно бросить


def test_no_message_is_sent_to_the_client():
    """Пишем ТОЛЬКО комментарий в карточку.

    В чат Открытой линии писать нельзя: Битрикс перешлёт это клиенту через коннектор,
    и человек получит одну и ту же реплику дважды — от бота и от Битрикса.
    """
    fake = FakeAdapter([OPENLINE])
    _mirror(fake)
    assert not hasattr(fake, "sent_to_client")
    assert all(isinstance(t, str) for _, t in fake.comments)


def test_text_is_passed_through_unchanged():
    """Текст реплики не препарируем.

    Через REST комментарии возвращаются с «:f09f988a:» вместо 😊 — это ВНУТРЕННЕЕ
    представление эмодзи в Битриксе, а не наша поломка: в нашей панели лежит
    настоящий 😊, и клиент получает его правильно. Скорее всего менеджер видит
    нормальный смайлик, поэтому «чинить» тут нечего — правка сломала бы рабочее.
    Проверено 06.08; если окажется, что в интерфейсе виден мусор — отдельная задача.
    """
    fake = FakeAdapter([OPENLINE])
    _mirror(fake, sender="bot", text="Здравствуйте! Я Медина 😊")
    assert "Здравствуйте! Я Медина 😊" in fake.comments[-1][1]
