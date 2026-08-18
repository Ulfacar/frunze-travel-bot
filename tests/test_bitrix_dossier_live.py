"""ГЕЙТ задачи «карточка успевает за клиентом, который передумал».

Написан ДО реализации и исполнителем НЕ редактируется. Кажется, что тест неверный —
остановись и спроси, не правь. ТЗ: `docs/task-bitrix-dossier-live.md`.

## Зачем (замер 18.08.2026 на боевом портале, лиды 186239/186241/186243)

Прогон настоящего бота по сценарию «клиент передумал» (`scripts/sim_tour_card.py`):

* Досье в карточке ЖИВОЕ: за 6 ходов обновилось 5 раз, Турция → ОАЭ доехала, состав
  2 → 4 доехал, бюджет 1500 → 2500 доехал. **Это поведение ломать нельзя.**
* Ход 6: клиент сменил вылет Бишкек → Алматы, бот пересчитал поиск из Алматы, а в
  карточке города вылета нет ВООБЩЕ — `render_dossier` его не выводит.
* Смена страны после отправленной подборки прошла молча: менеджеру не ушло ничего,
  хотя отправленные варианты по Турции стали мусором.

Частота на истории: 74 диалога из 985 (23.06–17.08) называют два и более направления —
верхняя граница 1.3 в сутки, и это ДО фильтра «только после отправленной подборки».

## Требуется от реализации

    app/integrations/crm/bitrix_pipeline.py
        render_dossier(conv, qualification)      # + строка «Вылет» между Направлением и Бюджетом

    app/core/offer_change_notice.py
        FLAG = "offer_change_notice_enabled"     # рантайм-флаг, дефолт False
        SIGNIFICANT: tuple[str, ...]             # что считаем существенным
        significant_diff(old, new) -> dict[str, tuple[str, str]]
        render_notice(*, name, phone, changed, link, bitrix_link) -> str
        async maybe_notify(conv_key, *, old, new, send=None) -> bool

`send` — инъекция транспорта `(login: str, text: str) -> bool`; по умолчанию берётся
`app.core.instant_handoff._send`, своего telegram-кода не писать.

    app/integrations/panel/store.py + app/integrations/crm/db.py
        поле диалога offer_facts (JSON, дефолт {}) — снимок значимых полей на момент
        последнего уведомления; колонка через _ensure_columns, БЕЗ alembic-ревизии.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

BOT = "frunze_tours"
KEY = f"{BOT}:996700000078"
LEAD = "186241"

STAGE_MAP = {
    "qualified": "UC_S0NTF8",
    "offer_sent": "UC_PNSIIB",
    "touch_1": "UC_1I1YV0",
    "touch_2": "UC_T9AEO4",
}
OFFER_STAGE = STAGE_MAP["offer_sent"]

TURKEY = {"destination": "Турция", "region": "Анталья", "departure_city": "Бишкек",
          "budget": "1500 USD", "dates": "5-11 сентября", "tourists": "2"}
DUBAI = dict(TURKEY, destination="ОАЭ", region="Дубай")


class FakeAdapter:
    """Портал: один лид, все пишущие вызовы записываются."""

    def __init__(self, status=OFFER_STAGE, comments=""):
        self.lead = {"ID": LEAD, "STATUS_ID": status, "COMMENTS": comments}
        self.stage_calls: list[tuple[str, str]] = []
        self.comment_calls: list[tuple[str, str]] = []

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


class Outbox:
    """Транспорт уведомлений: письма складываются, наружу ничего не уходит."""

    def __init__(self, fail=False):
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    async def __call__(self, login: str, text: str) -> bool:
        await asyncio.sleep(0)
        if self.fail:
            raise RuntimeError("telegram недоступен")
        self.sent.append((login, text))
        return True


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bp.settings, "bitrix_stage_map", dict(STAGE_MAP), raising=False)
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    yield
    flags.reset()


def _conv(*, qualification=None, stage_by_bot=OFFER_STAGE, owner="ademi",
          intercepted=False, offer_facts=None, lead=LEAD):
    store = ps.get_conversation_store()
    run(store.ensure(KEY, bot_id=BOT))
    run(store.add_message(KEY, sender="client", text="хотим в Анталью"))
    run(store.update_meta(KEY, bitrix_lead_id=lead, intercepted=intercepted,
                          qualification=dict(qualification or TURKEY),
                          assigned_to=owner))
    if stage_by_bot:
        run(store.update_meta(KEY, bitrix_stage_by_bot=stage_by_bot))
    if offer_facts is not None:
        run(store.update_meta(KEY, offer_facts=dict(offer_facts)))
    return store


# --- досье: город вылета -------------------------------------------------------

def test_dossier_shows_departure_city():
    """Замер 18.08: клиент ушёл на вылет из Алматы, в карточке города не было вообще."""
    store = _conv()
    conv = run(store.get(KEY))
    text = bp.render_dossier(conv, dict(DUBAI, departure_city="Алматы"))
    assert "Вылет: Алматы" in text


def test_dossier_skips_departure_line_when_unknown():
    """Пустой строки «Вылет:» в карточке менеджера быть не должно."""
    store = _conv()
    conv = run(store.get(KEY))
    quali = {k: v for k, v in TURKEY.items() if k != "departure_city"}
    assert "Вылет" not in bp.render_dossier(conv, quali)


def test_dossier_keeps_field_order():
    """Порядок строк читают глазами: направление → вылет → бюджет → даты → состав."""
    store = _conv()
    conv = run(store.get(KEY))
    text = bp.render_dossier(conv, TURKEY)
    order = [text.index(label) for label in ("Направление", "Вылет", "Бюджет", "Даты", "Состав")]
    assert order == sorted(order)


def test_dossier_still_carries_old_fields():
    """Инвариант: прежние строки досье никуда не делись — менеджеры их читают."""
    store = _conv()
    conv = run(store.get(KEY))
    text = bp.render_dossier(conv, TURKEY)
    for label in ("Направление:", "Бюджет:", "Даты:", "Состав:", "Диалог:"):
        assert label in text


# --- уведомление о существенной смене ------------------------------------------

def _notify(old, new, *, outbox=None, conv_kwargs=None):
    from app.core import offer_change_notice as ocn
    _conv(**(conv_kwargs or {}))
    box = outbox if outbox is not None else Outbox()
    ok = run(ocn.maybe_notify(KEY, old=dict(old), new=dict(new), send=box))
    return ok, box


def test_notice_on_destination_change_after_offer():
    """Клиент передумал после отправленной подборки — менеджер обязан узнать."""
    run(flags.set_flag("offer_change_notice_enabled", True))
    ok, box = _notify(TURKEY, DUBAI)
    assert ok is True
    assert len(box.sent) == 1


def test_notice_names_old_and_new_value():
    """«было → стало»: менеджеру важно, ЧТО поменялось, а не факт изменения."""
    run(flags.set_flag("offer_change_notice_enabled", True))
    _ok, box = _notify(TURKEY, DUBAI)
    body = box.sent[0][1]
    assert "Турция" in body and "ОАЭ" in body and "→" in body


def test_notice_goes_to_dialog_owner():
    run(flags.set_flag("offer_change_notice_enabled", True))
    _ok, box = _notify(TURKEY, DUBAI)
    assert box.sent[0][0] == "ademi"


def test_departure_city_change_notifies():
    """Смена города вылета так же обесценивает подборку, как и смена страны."""
    run(flags.set_flag("offer_change_notice_enabled", True))
    ok, box = _notify(TURKEY, dict(TURKEY, departure_city="Алматы"))
    assert ok is True and len(box.sent) == 1


def test_no_notice_before_offer_sent():
    """Пока подборка не ушла, смена параметров — обычный ход разговора, не событие."""
    run(flags.set_flag("offer_change_notice_enabled", True))
    ok, box = _notify(TURKEY, DUBAI, conv_kwargs={"stage_by_bot": STAGE_MAP["qualified"]})
    assert ok is False and box.sent == []


def test_no_notice_on_budget_change():
    """Бюджет бот пересчитывает сам — будить человека незачем (закон 5: шум убивает сторож)."""
    run(flags.set_flag("offer_change_notice_enabled", True))
    ok, box = _notify(TURKEY, dict(TURKEY, budget="2500 USD"))
    assert ok is False and box.sent == []


def test_no_notice_on_party_change():
    run(flags.set_flag("offer_change_notice_enabled", True))
    ok, box = _notify(TURKEY, dict(TURKEY, tourists="4", children_ages="7, 10"))
    assert ok is False and box.sent == []


def test_notice_not_repeated_for_same_change():
    """Один и тот же переезд Турция → ОАЭ шлётся один раз, а не на каждом ходу."""
    from app.core import offer_change_notice as ocn
    run(flags.set_flag("offer_change_notice_enabled", True))
    _conv()
    box = Outbox()
    first = run(ocn.maybe_notify(KEY, old=dict(TURKEY), new=dict(DUBAI), send=box))
    second = run(ocn.maybe_notify(KEY, old=dict(TURKEY), new=dict(DUBAI), send=box))
    assert first is True and second is False
    assert len(box.sent) == 1


def test_notice_silent_without_owner():
    """Владельца нет — слать некому; снимок НЕ фиксируем, уйдёт когда владелец появится."""
    from app.core import offer_change_notice as ocn
    run(flags.set_flag("offer_change_notice_enabled", True))
    _conv(owner="")
    box = Outbox()
    assert run(ocn.maybe_notify(KEY, old=dict(TURKEY), new=dict(DUBAI), send=box)) is False
    store = ps.get_conversation_store()
    run(store.update_meta(KEY, assigned_to="ademi"))
    assert run(ocn.maybe_notify(KEY, old=dict(TURKEY), new=dict(DUBAI), send=box)) is True


def test_notice_flag_off_by_default():
    """Дефолт False: выкатываемся, ничего не меняя."""
    ok, box = _notify(TURKEY, DUBAI)
    assert ok is False and box.sent == []


def test_notice_failure_never_raises():
    """Сбой телеги не должен ронять живой ход — досье важнее уведомления."""
    run(flags.set_flag("offer_change_notice_enabled", True))
    ok, box = _notify(TURKEY, DUBAI, outbox=Outbox(fail=True))
    assert ok is False


def test_significant_diff_reports_only_significant_keys():
    from app.core import offer_change_notice as ocn
    changed = ocn.significant_diff(TURKEY, dict(DUBAI, budget="9999 USD", tourists="8"))
    assert set(changed) <= set(ocn.SIGNIFICANT)
    assert "budget" not in changed and "tourists" not in changed


def test_dossier_write_survives_broken_notice(monkeypatch):
    """Досье пишется первым и не зависит от уведомления — порядок задан ТЗ §4.6."""
    from app.core import offer_change_notice as ocn

    async def boom(*a, **kw):
        raise RuntimeError("уведомление сломалось")

    monkeypatch.setattr(ocn, "maybe_notify", boom)
    run(flags.set_flag("offer_change_notice_enabled", True))
    fake = FakeAdapter()
    _conv()
    assert run(bp.sync_dossier(KEY, qualification=dict(DUBAI), adapter=fake)) is True
    assert len(fake.comment_calls) == 1


# --- инварианты: были зелёными ДО работы, обязаны остаться ----------------------

def test_human_comments_never_overwritten():
    fake = FakeAdapter(comments="Звонил, просил перезвонить в среду")
    _conv()
    assert run(bp.sync_dossier(KEY, qualification=dict(TURKEY), adapter=fake)) is False
    assert fake.comment_calls == []


def test_intercepted_conversation_writes_nothing():
    fake = FakeAdapter()
    _conv(intercepted=True)
    assert run(bp.sync_dossier(KEY, qualification=dict(TURKEY), adapter=fake)) is False
    assert fake.comment_calls == []


def test_terminal_status_writes_nothing():
    fake = FakeAdapter(status="CONVERTED")
    _conv()
    assert run(bp.sync_dossier(KEY, qualification=dict(TURKEY), adapter=fake)) is False
    assert fake.comment_calls == []


def test_pipeline_flag_off_writes_nothing():
    run(flags.set_flag("bitrix_pipeline_enabled", False))
    fake = FakeAdapter()
    _conv()
    assert run(bp.sync_dossier(KEY, qualification=dict(TURKEY), adapter=fake)) is False
    assert fake.comment_calls == []


def test_dossier_updates_after_offer_stage():
    """Главный инвариант замера: досье живое и после того, как стадия уже поставлена."""
    fake = FakeAdapter()
    _conv()
    assert run(bp.sync_dossier(KEY, qualification=dict(TURKEY), adapter=fake)) is True
    assert run(bp.sync_dossier(KEY, qualification=dict(DUBAI), adapter=fake)) is True
    assert "ОАЭ" in fake.comment_calls[-1][1]
