"""ГЕЙТ задачи «бот ведёт карточку в Битриксе, менеджер подтверждает одним касанием».

Написан ДО реализации и исполнителем НЕ редактируется. Кажется, что тест неверный —
остановись и спроси, не правь.

## Зачем (разобрано на живом портале 17.08.2026)

Заказчик по турам — Даулет, цель — учёт в конце месяца. Факты на сегодня:

* `bitrix_stage_map` пуст, поэтому все 10 вызовов `crm.update_stage`
  (`runner.py:397,426,464,476,534`, `funnels/tours.py:55,59`, `tickets.py:37`)
  два месяца уходили в никуда. **Все туровые лиды стоят в `NEW`.**
* В отчёте таргетологов за 01.07–12.08: 1585 лидов, **158 продаж на 13,15 млн KGS**.
  В Битриксе за тот же период — **7 сделок**, туровая одна и та с названием «фио».
  Продажа не доходит до CRM, потому что стоит три действия: конвертировать лид,
  выбрать воронку, вписать сумму.
* Стадии лида портала: `NEW` → `UC_S0NTF8` Выявление потребностей → `UC_Y4VY7B`
  Переписка/Недозвоны → `UC_1I1YV0` 1 касание → `UC_T9AEO4` 2 касание → `UC_A492DB`
  3 касание → `UC_PNSIIB` Предложение отправлено → `UC_R8BD0W` Не квалифицированный →
  `CONVERTED` Подписан → `JUNK` Некачественный.
* Воронка туров — категория **27 «FrunzeTravel»**, первая стадия `C27:NEW`
  «Оплата получено». То есть касса заводится по факту оплаты.
* Визовые менеджеры двигают стадии сами (Элиза 110841), туровые — нет.

## Требуется от реализации

    app/integrations/crm/bitrix_pipeline.py
        STAGE_SEQUENCE: tuple[str, ...]      # порядок STATUS_ID, только вперёд
        TERMINAL_STATUSES: frozenset[str]    # CONVERTED / JUNK / UC_R8BD0W — не наши
        async advance(conv_key, internal_stage, *, adapter=None) -> str
        render_dossier(conv, qualification: dict) -> str
        async sync_dossier(conv_key, *, qualification=None, adapter=None) -> bool
        async read_back_once(*, adapter=None) -> dict

`qualification` передаётся явно — данными хода из `DialogState`, а не из карточки
диалога: замер прода 17.08 показал заполненную `conversations.qualification` у 28
диалогов из 322. `None` означает «взять из conv» (для фоновых вызовов).

    app/integrations/crm/bitrix24.py
        async get_lead(lead_id) -> dict          # STATUS_ID + COMMENTS
        async update_comments(lead_id, text) -> None
        async create_deal(fields: dict) -> str

    app/integrations/panel/store.py
        поля диалога: bitrix_stage_by_bot, bitrix_deal_id  (ОБА стора + миграция)

Флаги (оба дефолт False — выкатываемся, ничего не меняя):
    bitrix_pipeline_enabled   — бот двигает стадию и пишет досье
    bitrix_autodeal_enabled   — создание сделки по CONVERTED; выключен = dry-run

Досье пишется в **поле `COMMENTS` лида**, а не комментарием в таймлайн: на портале
доступны только `crm.timeline.comment.get/list/fields` — обновить комментарий нечем,
и досье плодилось бы копиями на каждый ход.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

def _key(bot_id="frunze_tours"):
    """Ключ диалога — `bot_id:телефон`, как в бою."""
    return f"{bot_id}:996700111222"


KEY = _key()
LEAD = "186055"

STAGE_MAP = {
    "qualified": "UC_S0NTF8",
    "offer_sent": "UC_PNSIIB",
    "touch_1": "UC_1I1YV0",
    "touch_2": "UC_T9AEO4",
}


class FakeAdapter:
    """Портал: хранит один лид и записывает ВСЕ пишущие вызовы."""

    def __init__(self, status="NEW", comments=""):
        self.lead = {"ID": LEAD, "STATUS_ID": status, "COMMENTS": comments}
        self.stage_calls: list[tuple[str, str]] = []
        self.comment_calls: list[tuple[str, str]] = []
        self.notes: list[tuple[str, str]] = []
        self.deals: list[dict] = []

    async def list_converted_leads(self, since):
        """Портал отвечает списком проданных — контракт сменился 18.08 вместе с тем,
        что обратное чтение больше не опрашивает каждую карточку по отдельности."""
        await asyncio.sleep(0)
        return [dict(self.lead)] if str(self.lead.get("STATUS_ID")) == "CONVERTED" else []

    async def get_lead(self, lead_id):
        await asyncio.sleep(0)
        return dict(self.lead)

    async def update_stage_status(self, lead_id, status_id):
        await asyncio.sleep(0)
        self.stage_calls.append((str(lead_id), status_id))
        self.lead["STATUS_ID"] = status_id

    async def update_comments(self, lead_id, text):
        await asyncio.sleep(0)
        self.comment_calls.append((str(lead_id), text))
        self.lead["COMMENTS"] = text

    async def add_note(self, lead_id, text):
        self.notes.append((str(lead_id), text))

    async def create_deal(self, fields):
        await asyncio.sleep(0)
        self.deals.append(dict(fields))
        return str(5000 + len(self.deals))

    @property
    def writes(self):
        return len(self.stage_calls) + len(self.comment_calls) + len(self.deals)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bp.settings, "bitrix_stage_map", dict(STAGE_MAP), raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_deal_category_id", "27", raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_deal_stage_id", "C27:NEW", raising=False)
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    yield
    flags.reset()


def _conv(*, lead=LEAD, stage_by_bot="", intercepted=False, qualification=None,
          bot_id="frunze_tours"):
    key = _key(bot_id)
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id=bot_id))
    run(store.add_message(key, sender="client", text="хочу в Анталью"))
    run(store.update_meta(key, bitrix_lead_id=lead, intercepted=intercepted,
                          qualification=qualification or {}))
    if stage_by_bot:
        run(store.update_meta(key, bitrix_stage_by_bot=stage_by_bot))
    return store


def _advance(fake, internal_stage, key=KEY):
    return run(bp.advance(key, internal_stage, adapter=fake))


# --- стадии: движение вперёд ---------------------------------------------------

def test_advance_sets_mapped_status():
    """Квалификация собрана → карточка уезжает в «Выявление потребностей»."""
    fake = FakeAdapter(status="NEW")
    _conv()
    assert _advance(fake, "qualified") == "UC_S0NTF8"
    assert fake.stage_calls == [(LEAD, "UC_S0NTF8")]


def test_advance_remembers_what_bot_set():
    """Поставленный статус запоминается на диалоге — иначе не отличить свой от чужого."""
    fake = FakeAdapter(status="NEW")
    store = _conv()
    _advance(fake, "qualified")
    conv = run(store.get(KEY))
    assert getattr(conv, "bitrix_stage_by_bot", "") == "UC_S0NTF8"


def test_two_events_in_one_turn_do_not_conflict():
    """Замер 17.08 на живом прогоне: квалификация собралась и подборка ушла в ОДНОМ ходу.

    Клиент прислал даты в 20:51:02, в 20:51:14 бот уже отдал 25 вариантов карточками.
    Значит `qualified` и `offer_sent` приходят подряд с интервалом в секунды — правило
    «только вперёд» обязано это пропустить, не откатив и не задублировав.
    """
    fake = FakeAdapter(status="NEW")
    _conv()
    assert _advance(fake, "qualified") == "UC_S0NTF8"
    assert _advance(fake, "offer_sent") == "UC_PNSIIB"
    assert fake.stage_calls == [(LEAD, "UC_S0NTF8"), (LEAD, "UC_PNSIIB")]


def test_advance_never_moves_backwards():
    """Бот уже довёл до «Предложение отправлено» — назад в квалификацию не тянем."""
    fake = FakeAdapter(status="UC_PNSIIB")
    _conv(stage_by_bot="UC_PNSIIB")
    assert _advance(fake, "qualified") == ""
    assert fake.writes == 0


def test_advance_is_idempotent():
    """Повторное событие той же стадии не шлёт второй раз."""
    fake = FakeAdapter(status="UC_S0NTF8")
    _conv(stage_by_bot="UC_S0NTF8")
    assert _advance(fake, "qualified") == ""
    assert fake.stage_calls == []


# --- стадии: человек главнее ---------------------------------------------------

def test_manual_move_freezes_bot_forever():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ, обязан пройти: менеджер сам перенёс на «3 касание».

    Статус в портале не тот, что ставил бот → карточку трогал человек. Бот молчит
    и в этот раз, и во все следующие — даже когда придёт стадия «дальше по порядку».
    """
    fake = FakeAdapter(status="UC_A492DB")
    _conv(stage_by_bot="UC_S0NTF8")
    assert _advance(fake, "offer_sent") == ""
    assert fake.writes == 0
    fake.lead["STATUS_ID"] = "UC_A492DB"
    assert _advance(fake, "touch_2") == ""
    assert fake.writes == 0


@pytest.mark.parametrize("status", ["CONVERTED", "JUNK", "UC_R8BD0W"])
def test_terminal_status_is_never_touched(status):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: подписан / брак / не квалифицирован — это слово менеджера."""
    fake = FakeAdapter(status=status)
    _conv(stage_by_bot="UC_S0NTF8")
    assert _advance(fake, "offer_sent") == ""
    assert fake.writes == 0


def test_bot_never_sets_terminal_status_itself():
    """Ни при каких внутренних стадиях бот не ставит CONVERTED/JUNK сам."""
    assert bp.TERMINAL_STATUSES >= {"CONVERTED", "JUNK", "UC_R8BD0W"}
    assert not (set(STAGE_MAP.values()) & bp.TERMINAL_STATUSES)


def test_intercepted_dialog_is_not_moved():
    """Менеджер забрал переписку — карточка тоже его."""
    fake = FakeAdapter(status="NEW")
    _conv(intercepted=True)
    assert _advance(fake, "qualified") == ""
    assert fake.writes == 0


# --- инварианты «поведение не изменилось» --------------------------------------

def test_disabled_by_default_writes_nothing():
    """Флаг снят → ни одного вызова в портал. Это дефолт выкатки."""
    run(flags.set_flag("bitrix_pipeline_enabled", False))
    fake = FakeAdapter(status="NEW")
    _conv()
    assert _advance(fake, "qualified") == ""
    assert fake.writes == 0


def test_per_bot_flag_enables_single_channel():
    """Обкатка идёт на одном канале: глобальный снят, пер-ботовый включён."""
    run(flags.set_flag("bitrix_pipeline_enabled", False))
    run(flags.set_flag("bitrix_pipeline_enabled:frunze_tours_tg", True))
    fake = FakeAdapter(status="NEW")
    _conv(bot_id="frunze_tours_tg")
    assert _advance(fake, "qualified", key=_key("frunze_tours_tg")) == "UC_S0NTF8"


def test_per_bot_flag_does_not_leak_to_other_channels():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: включили тест-бота — боевой канал остаётся нетронутым."""
    run(flags.set_flag("bitrix_pipeline_enabled", False))
    run(flags.set_flag("bitrix_pipeline_enabled:frunze_tours_tg", True))
    fake = FakeAdapter(status="NEW")
    _conv(bot_id="frunze_tours")
    assert _advance(fake, "qualified") == ""
    assert fake.writes == 0


def test_empty_stage_map_soft_skips(monkeypatch):
    """Карта пуста — прежнее поведение: тихий пропуск, без исключений."""
    monkeypatch.setattr(bp.settings, "bitrix_stage_map", {}, raising=False)
    fake = FakeAdapter(status="NEW")
    _conv()
    assert _advance(fake, "qualified") == ""
    assert fake.writes == 0


def test_unmapped_handoff_stage_does_not_move_card():
    """`manager_handoff` намеренно не замаплен: у портала нет стадии «передан менеджеру»."""
    fake = FakeAdapter(status="UC_PNSIIB")
    _conv(stage_by_bot="UC_PNSIIB")
    assert _advance(fake, "manager_handoff") == ""
    assert fake.writes == 0


def test_no_lead_id_is_not_an_error():
    """Карточка ещё не найдена (ждём лид Открытой линии) — молча выходим."""
    fake = FakeAdapter(status="NEW")
    _conv(lead="")
    assert _advance(fake, "qualified") == ""
    assert fake.writes == 0


# --- досье ---------------------------------------------------------------------

def test_dossier_goes_to_comments_not_timeline():
    """Досье — поле карточки, а не комментарий: обновлять комментарии портал не даёт."""
    fake = FakeAdapter(status="NEW", comments="")
    _conv(qualification={"направление": "Анталья", "бюджет": "100000 KGS",
                         "даты": "10.09", "взрослых": "2"})
    assert run(bp.sync_dossier(KEY, qualification=None, adapter=fake)) is True
    assert len(fake.comment_calls) == 1
    assert fake.notes == []


def test_dossier_contains_facts_manager_needs():
    """Сверка должна занимать секунды: направление, бюджет, даты, состав — в тексте."""
    _conv()
    conv = run(ps.get_conversation_store().get(KEY))
    text = bp.render_dossier(conv, {"направление": "Анталья", "бюджет": "100000 KGS",
                                    "даты": "10.09", "взрослых": "2"})
    for fact in ("Анталья", "100000", "10.09", "2"):
        assert fact in text


def test_dossier_marked_as_written_by_bot():
    """Маркер обязателен — по нему отличаем свой текст от написанного человеком."""
    _conv()
    conv = run(ps.get_conversation_store().get(KEY))
    assert bp.render_dossier(conv, {"направление": "Анталья"}).startswith(bp.DOSSIER_MARKER)


def test_dossier_uses_passed_qualification_not_stale_conv():
    """Факты берём из состояния ХОДА, а не из карточки диалога.

    Замер 17.08 на проде: `conversations.qualification` заполнена у 28 диалогов из 322.
    Живые данные лежат в `DialogState` (Redis, TTL 7 дней), а в панель попадают не
    всегда. Досье, построенное по `conv`, было бы пустым в 91% случаев.
    """
    fake = FakeAdapter(status="NEW", comments="")
    _conv(qualification={})                       # в панели пусто — как на проде
    assert run(bp.sync_dossier(KEY, qualification={"направление": "Кемер"},
                               adapter=fake)) is True
    assert "Кемер" in fake.lead["COMMENTS"]


def test_dossier_overwrites_our_own_legacy_comments():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ наоборот: старый формат `create_lead` — это МЫ, не человек.

    Живая карточка 186199 (17.08): в COMMENTS лежит `destination: Турция\\nregion:
    Анталья\\n…` — это `_format_qualification` при создании лида. Маркера там нет, и
    правило «нет маркера → не трогаем» заморозило бы досье во всех наших карточках.
    """
    legacy = ("destination: Турция\nregion: Анталья\ndeparture_city: Бишкек\n"
              "tourists: 2 взрослых\nbudget: 3000$")
    fake = FakeAdapter(status="NEW", comments=legacy)
    _conv()
    assert run(bp.sync_dossier(KEY, qualification={"направление": "Анталья"},
                               adapter=fake)) is True
    assert fake.lead["COMMENTS"].startswith(bp.DOSSIER_MARKER)


def test_dossier_has_no_astral_characters():
    """Проверено на живом портале 17.08: Битрикс МОЛЧА съедает эмодзи в COMMENTS.

    `crm.lead.update` с текстом, начинающимся на 🤖, вернул `result: true`, а поле стало
    пустым — база портала обрывается на первом 4-байтовом символе. Ошибки нет ни в API,
    ни в логах, поэтому досье исчезало бесследно. Ни маркер, ни собранный текст не
    имеют права содержать символы вне BMP.
    """
    assert all(ord(ch) < 0x10000 for ch in bp.DOSSIER_MARKER)
    _conv()
    conv = run(ps.get_conversation_store().get(KEY))
    text = bp.render_dossier(conv, {"направление": "Анталья 🏖️", "бюджет": "100000 💰"})
    assert all(ord(ch) < 0x10000 for ch in text), "эмодзи из реплики клиента обнулят поле"


def test_dossier_survives_emoji_from_client():
    """Клиент пишет эмодзи в пожеланиях — досье обязано записаться, а не исчезнуть."""
    fake = FakeAdapter(status="NEW", comments="")
    _conv()
    assert run(bp.sync_dossier(KEY, qualification={"направление": "Кемер 🌴"},
                               adapter=fake)) is True
    assert fake.lead["COMMENTS"].strip()
    assert "Кемер" in fake.lead["COMMENTS"]


def test_marker_survives_the_portal_bbcode_parser():
    """Проверено на карточке 186199 17.08: портал вырезал `[бот]` как BBCode-тег.

    В поле осталось «Досье:» вместо «[бот] Досье:». Маркер, который не переживает
    запись, хуже отсутствующего: на следующем ходу бот не узнаёт свой текст, считает
    его человеческим и замолкает навсегда. Скобкам в маркере не место.
    """
    assert "[" not in bp.DOSSIER_MARKER and "]" not in bp.DOSSIER_MARKER


def test_our_own_record_beats_whatever_portal_did_to_the_text():
    """Кто писал досье — помним МЫ, а не угадываем по тексту в портале.

    Портал уже дважды исказил наш текст: съел эмодзи (поле обнулилось) и вырезал
    «[бот]» как BBCode-тег. Каждое искажение ломало распознавание, и бот замолкал по
    карточке навсегда — проверено на проде 17.08, `sync_dossier` вернул False на
    собственном же досье. Пока источник истины — чужой изменяемый текст, этот класс
    багов неисчерпаем.
    """
    fake = FakeAdapter(status="NEW", comments="Досье:\nНаправление: что угодно")
    store = _conv()
    run(store.update_meta(KEY, bitrix_dossier_by_bot=True))
    assert run(bp.sync_dossier(KEY, qualification={"направление": "Аланья"},
                               adapter=fake)) is True
    assert "Аланья" in fake.lead["COMMENTS"]


def test_dossier_write_is_remembered_on_the_conversation():
    """Первая запись отмечается у нас — иначе помнить нечего."""
    fake = FakeAdapter(status="NEW", comments="")
    store = _conv()
    run(bp.sync_dossier(KEY, qualification={"направление": "Кемер"}, adapter=fake))
    assert getattr(run(store.get(KEY)), "bitrix_dossier_by_bot", False) is True


def test_own_dossier_is_recognised_after_round_trip():
    """Досье, прочитанное обратно из портала, обязано опознаваться как своё."""
    _conv()
    conv = run(ps.get_conversation_store().get(KEY))
    written = bp.render_dossier(conv, {"направление": "Кемер"})
    fake = FakeAdapter(status="NEW", comments=written)   # ровно то, что вернёт портал
    assert run(bp.sync_dossier(KEY, qualification={"направление": "Аланья"},
                               adapter=fake)) is True
    assert "Аланья" in fake.lead["COMMENTS"]


def test_dossier_never_overwrites_human_text():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: менеджер написал в поле сам — не трогаем никогда."""
    fake = FakeAdapter(status="NEW", comments="созвон в 14:00, просит море рядом")
    _conv(qualification={"направление": "Анталья"})
    assert run(bp.sync_dossier(KEY, qualification=None, adapter=fake)) is False
    assert fake.writes == 0


def test_dossier_updates_its_own_previous_version():
    """Своё досье перезаписываем — в карточке всегда одна свежая версия."""
    fake = FakeAdapter(status="NEW", comments=bp.DOSSIER_MARKER + " старое")
    _conv(qualification={"направление": "Анталья"})
    assert run(bp.sync_dossier(KEY, qualification=None, adapter=fake)) is True
    assert fake.lead["COMMENTS"].startswith(bp.DOSSIER_MARKER)
    assert "старое" not in fake.lead["COMMENTS"]


# --- фоновый запуск: те же грабли, что у зеркала --------------------------------

def test_fire_without_running_loop_is_silent():
    """Нет event loop — тихо выходим, а НЕ роняем ход бота.

    `fire` зовётся из `_attach_tour_cards`, то есть из горячего пути ответа клиенту.
    Голый `asyncio.create_task` там бросает RuntimeError. У зеркала это уже решено
    (`bitrix_mirror.fire`), и решение обязано быть таким же.
    """
    bp.fire(KEY, "qualified", {"направление": "Анталья"})   # без asyncio.run — не должно упасть


def test_fire_keeps_strong_reference_to_task():
    """Ссылку на задачу держим сами: иначе loop хранит weakref и GC съедает работу.

    Ровно этот шрам записан в `bitrix_mirror.fire`. Стадия не поставилась бы молча
    и невоспроизводимо.
    """
    async def _go():
        store = ps.get_conversation_store()          # готовим диалог внутри loop:
        await store.ensure(KEY, bot_id="frunze_tours")   # хелпер `_conv` синхронный и
        await store.update_meta(KEY, bitrix_lead_id=LEAD)  # звать его отсюда нельзя
        bp.fire(KEY, "qualified", {})
        assert bp._tasks, "задача должна храниться в модуле, иначе её соберёт GC"
        await asyncio.sleep(0)

    run(_go())


# --- обратное чтение и учёт ----------------------------------------------------

def test_read_back_writes_nothing_to_portal():
    """Чтение статусов — только чтение. Дефолт `bitrix_autodeal_enabled` = False."""
    fake = FakeAdapter(status="CONVERTED")
    _conv(stage_by_bot="UC_PNSIIB")
    run(bp.read_back_once(adapter=fake))
    assert fake.deals == []
    assert fake.stage_calls == []


def test_read_back_records_sale_on_converted():
    """«Подписан» в портале → продажа фиксируется у нас, для месячного отчёта."""
    fake = FakeAdapter(status="CONVERTED")
    store = _conv(stage_by_bot="UC_PNSIIB")
    stats = run(bp.read_back_once(adapter=fake))
    conv = run(store.get(KEY))
    assert (conv.outcome or "") == "won"
    assert stats.get("won", 0) == 1


def test_autodeal_creates_deal_in_tours_funnel():
    """С включённым флагом одна кнопка менеджера превращается в сделку кат.27."""
    run(flags.set_flag("bitrix_autodeal_enabled", True))
    fake = FakeAdapter(status="CONVERTED")
    _conv(stage_by_bot="UC_PNSIIB", qualification={"бюджет": "120000"})
    run(bp.read_back_once(adapter=fake))
    assert len(fake.deals) == 1
    deal = fake.deals[0]
    assert str(deal.get("CATEGORY_ID")) == "27"
    assert deal.get("STAGE_ID") == "C27:NEW"


def test_autodeal_is_created_once():
    """Второй тик не плодит дубль — id сделки помнится на диалоге."""
    run(flags.set_flag("bitrix_autodeal_enabled", True))
    fake = FakeAdapter(status="CONVERTED")
    store = _conv(stage_by_bot="UC_PNSIIB")
    run(bp.read_back_once(adapter=fake))
    run(bp.read_back_once(adapter=fake))
    assert len(fake.deals) == 1
    conv = run(store.get(KEY))
    assert getattr(conv, "bitrix_deal_id", "")


def test_read_back_covers_cards_the_bot_never_moved():
    """Учёт считает ВСЕ продажи, а не только карточки, которые двигал бот.

    Цель задачи — месячная цифра для владельца. Карточка, где бот заморожен ручным
    переносом менеджера или где менеджер вёл лид сам, обязана попасть в учёт: продажа
    по ней такая же настоящая.
    """
    fake = FakeAdapter(status="CONVERTED")
    store = _conv(stage_by_bot="")                 # бот эту карточку не трогал ни разу
    stats = run(bp.read_back_once(adapter=fake))
    assert stats.get("checked", 0) == 1
    assert (run(store.get(KEY)).outcome or "") == "won"


def test_read_back_skips_dialogs_without_lead():
    """Диалогов без карточки в портале обратное чтение не касается."""
    fake = FakeAdapter(status="CONVERTED")
    _conv(lead="")
    stats = run(bp.read_back_once(adapter=fake))
    assert stats.get("checked", 0) == 0


def test_old_dialog_joins_pipeline_on_new_message():
    """Включение по событию: диалог заведён до фичи, новое сообщение вводит его в строй.

    Никакой миграции старых карточек — но и отсечки по дате создания тоже нет,
    иначе вернувшийся клиент навсегда остался бы в старом режиме.
    """
    fake = FakeAdapter(status="NEW")
    store = _conv(stage_by_bot="")
    run(store.add_message(KEY, sender="client", text="а на сентябрь есть?"))
    assert _advance(fake, "qualified") == "UC_S0NTF8"
