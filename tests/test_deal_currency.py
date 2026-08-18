"""ГЕЙТ: сумма сделки уезжает в портал вместе с валютой.

Написан ДО правки и исполнителем НЕ редактируется. Кажется, что тест неверный —
остановись и спроси, не правь.

## Зачем (сверено с боевым порталом 18.08.2026)

Воронка туров считает в сомах: базовая валюта портала `KGS`, обе живые сделки —
`45000.00 KGS` и `58000.00 KGS`. А `_opportunity` отдавала голое число из бюджета
клиента («2500 USD» → `2500`), и `create_deal` валюту не передавал вовсе. Портал
подставил бы базовую: сделка на бюджет **2500 долларов появилась бы как 2500 сом** —
около 28 долларов, в двадцать раз ниже правды. Заказчик по турам меряет работу именно
суммами в этой воронке.

Курсы в портале настроены (USD и EUR есть, `crm.currency.list`), поэтому пересчёт для
отчётов делает сам Битрикс — свой курс мы не прибиваем, он протухнет.

Второе правило, из той же доктрины «пропустить дешевле, чем соврать»: если сумму
разобрать не удалось, поле не заполняем вовсе. Пустая сумма — вопрос менеджеру,
неверная — испорченный отчёт.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

BOT = "frunze_tours"
KEY = f"{BOT}:996700111333"
LEAD = "186245"


class FakeAdapter:
    def __init__(self, status="CONVERTED"):
        self.lead = {"ID": LEAD, "STATUS_ID": status, "COMMENTS": "", "TITLE": "tours: тест",
                     "ASSIGNED_BY_ID": "96451"}
        self.deals: list[dict] = []

    async def get_lead(self, lead_id):
        await asyncio.sleep(0)
        return dict(self.lead)

    async def update_stage_status(self, lead_id, status_id):
        await asyncio.sleep(0)

    async def update_comments(self, lead_id, text):
        await asyncio.sleep(0)

    async def create_deal(self, fields):
        await asyncio.sleep(0)
        self.deals.append(dict(fields))
        return str(9000 + len(self.deals))


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bp.settings, "bitrix_stage_map",
                        {"qualified": "UC_S0NTF8", "offer_sent": "UC_PNSIIB"}, raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_deal_category_id", "27", raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_deal_stage_id", "C27:NEW", raising=False)
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    run(flags.set_flag("bitrix_autodeal_enabled", True))
    yield
    flags.reset()


def _conv(budget: str, *, value=None, currency=""):
    store = ps.get_conversation_store()
    run(store.ensure(KEY, bot_id=BOT))
    run(store.add_message(KEY, sender="client", text="хочу в Дубай"))
    run(store.update_meta(KEY, bitrix_lead_id=LEAD, qualification={"budget": budget},
                          estimated_value=value, estimated_value_currency=currency))
    return store


def _deal(fake) -> dict:
    run(bp.read_back_once(adapter=fake))
    assert fake.deals, "сделка не создана"
    return fake.deals[-1]


# --- валюта доезжает --------------------------------------------------------

def test_dollar_budget_keeps_dollars():
    """Главный случай: 2500 USD не должны превратиться в 2500 сом."""
    fake = FakeAdapter()
    _conv("2500 USD")
    deal = _deal(fake)
    assert deal.get("CURRENCY_ID") == "USD"
    assert float(deal["OPPORTUNITY"]) == 2500


def test_som_budget_stays_som():
    fake = FakeAdapter()
    _conv("100000 KGS")
    deal = _deal(fake)
    assert deal.get("CURRENCY_ID") == "KGS"
    assert float(deal["OPPORTUNITY"]) == 100000


def test_euro_budget():
    fake = FakeAdapter()
    _conv("1900 EUR")
    deal = _deal(fake)
    assert deal.get("CURRENCY_ID") == "EUR"


def test_words_instead_of_code():
    """Клиент пишет словами, а не кодом валюты — «до 1500 долларов»."""
    fake = FakeAdapter()
    _conv("до 1500 долларов")
    deal = _deal(fake)
    assert deal.get("CURRENCY_ID") == "USD"
    assert float(deal["OPPORTUNITY"]) == 1500


def test_bare_number_follows_search_default():
    """Голое число трактуем как доллары — ровно так же, как в поиске туров.

    Расхождение здесь было бы хуже любого дефолта: клиенту показали цены в долларах,
    а в сделку положили сомы.
    """
    fake = FakeAdapter()
    _conv("2000")
    deal = _deal(fake)
    assert deal.get("CURRENCY_ID") == "USD"


def test_stored_estimate_wins_with_its_own_currency():
    """Готовая оценка чека (readiness) идёт со своей валютой, а не с угаданной."""
    fake = FakeAdapter()
    _conv("2500 USD", value=180000.0, currency="KGS")
    deal = _deal(fake)
    assert float(deal["OPPORTUNITY"]) == 180000
    assert deal.get("CURRENCY_ID") == "KGS"


# --- лучше пусто, чем неправда ----------------------------------------------

def test_unparsable_budget_leaves_sum_empty():
    """Сумму не разобрали — поля нет вовсе. Пустое поле менеджер увидит и заполнит."""
    fake = FakeAdapter()
    _conv("договоримся")
    deal = _deal(fake)
    assert "OPPORTUNITY" not in deal


def test_no_currency_without_sum():
    """Валюта без суммы бессмысленна и в портал не уходит."""
    fake = FakeAdapter()
    _conv("")
    deal = _deal(fake)
    assert "OPPORTUNITY" not in deal and "CURRENCY_ID" not in deal


# --- инварианты сделки ------------------------------------------------------

def test_deal_keeps_category_stage_and_owner():
    fake = FakeAdapter()
    _conv("2500 USD")
    deal = _deal(fake)
    assert deal["CATEGORY_ID"] == "27"
    assert deal["STAGE_ID"] == "C27:NEW"
    assert deal["ASSIGNED_BY_ID"] == "96451"


def test_autodeal_off_creates_nothing():
    """Инвариант: с выключенным флагом сделок не появляется вообще."""
    run(flags.set_flag("bitrix_autodeal_enabled", False))
    fake = FakeAdapter()
    _conv("2500 USD")
    stats = run(bp.read_back_once(adapter=fake))
    assert fake.deals == []
    assert stats["deals_dry_run"] >= 1
