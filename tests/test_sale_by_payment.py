"""B3 — продажа = полная оплата по договору (решение Алана 14.10, ТЗ §20). CRITICAL.

Приёмка из `ai/tasks/2026-10-14-b3-sale-full-payment.md`:

    S1 договор 500 USD, оплата 500 USD      → won, основание с делом
    S2 частичная 300 из 500                 → не won
    S3 USD при договоре в KGS без курса     → не won, деньги в «без курса»
    S4 повтор той же оплаты (тот же ключ)   → одна запись, одна продажа
    S6 полная оплата, потом возврат         → won остаётся, одна пометка (Алан 15.10)
    S7 переплата 600 при договоре 500       → won один раз, переплата видна отдельно

S5 (чужое направление) и S8 (вечерняя ссылка) — в `test_admin_workday.py` и
`test_sale_check.py`: там живут маршруты.

Плюс ловушки, которых в карточке нет, но которые стоили бы отчёта:
флаг OFF ничего не пишет; уже поставленный `lost` не перезатирается; диалог другого
направления с тем же номером не трогается; сбой хранилища панели не теряет оплату и
дозакрывается на следующем пересчёте.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import settings
from app.core import flags, sale_by_payment
from app.domain.models import Contact, ContactIdentity, ServiceEvent, ServicePayment
from app.domain.service_authz import Actor
from app.domain.service_cases import seed_products, sign_contract
from app.domain.service_money import (
    SALE_EVENT, SALE_RESTORED_EVENT, SALE_REVERSAL_EVENT, Balance, balance_of,
    correct_contract_amount, is_fully_paid, overpaid_by, record_payment,
    record_refund_paid,
)
from app.integrations.panel.store import MemoryConversationStore
from tests.test_service_cases import SYSTEM_ACTOR, run_with_db

OWNER = Actor(manager_id="ademi", allowed_directions=("tours",))
CHIEF = Actor(manager_id="chief", allowed_directions=("tours", "visa"), is_full_admin=True)
PHONE = "996700000001"
KEY = f"frunze_tours:{PHONE}"


@pytest.fixture
def flag_on(monkeypatch):
    flags.reset()
    monkeypatch.setattr(settings, "sale_by_full_payment_enabled", True, raising=False)
    yield
    flags.reset()


# ---------------- правило как чистая функция --------------------------------------------
def _balance(**kw) -> Balance:
    base = dict(currency="USD", agreed=Decimal("500.00"))
    base.update(kw)
    return Balance(**base)


@pytest.mark.parametrize("balance, expected", [
    (_balance(paid=Decimal("500.00")), True),                                   # S1
    (_balance(paid=Decimal("300.00")), False),                                  # S2
    (_balance(paid=Decimal("0.00"), unconverted={"USD": Decimal("500.00")},
              currency="KGS", agreed=Decimal("50000.00")), False),               # S3
    (_balance(paid=Decimal("600.00")), True),                                   # S7
    (_balance(paid=Decimal("500.00"), refunded=Decimal("200.00")), False),      # S6
    (_balance(agreed=None, paid=Decimal("500.00")), False),                     # сумма неизвестна
    (_balance(paid=Decimal("500.00"), broken_entries=(7,)), False),             # сломанная строка
    (_balance(paid=Decimal("500.00"), refund_due=Decimal("500.00")), True),     # обязательство ≠ возврат
])
def test_rule_full_payment_in_contract_currency(balance, expected):
    assert is_fully_paid(balance) is expected


def test_overpayment_is_a_separate_number():
    assert overpaid_by(_balance(paid=Decimal("600.00"))) == Decimal("100.00")
    assert overpaid_by(_balance(paid=Decimal("500.00"))) == Decimal("0.00")
    assert overpaid_by(_balance(agreed=None, paid=Decimal("1.00"))) == Decimal("0.00")


# ---------------- сквозной путь: домен + хранилище панели ---------------------------------
async def _contract(session, *, amount="500.00", currency="USD", phone=PHONE):
    contact = Contact()
    session.add(contact)
    await session.flush()
    session.add(ContactIdentity(contact_id=contact.id, identity_type="phone",
                                normalized_value=phone, provider_scope=""))
    products = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
    tour = next(p for p in products if p.direction == "tours")
    case = await sign_contract(
        session, contact_id=contact.id, product_id=tour.id,
        owner_login=OWNER.manager_id, by=OWNER, reference="B3-1",
        amount=Decimal(amount), currency=currency, idempotency_key="b3-case-1")
    await session.flush()
    return case


async def _dialog(store, key=KEY, *, bot="frunze_tours", funnel="tours", outcome=""):
    await store.ensure(key, channel="whatsapp", bot_id=bot, phone=key.split(":")[-1])
    await store.update_meta(key, funnel=funnel)
    if outcome:
        await store.update_meta(key, outcome=outcome)


async def _pay(sm, case_id, amount, currency, key, *, by=OWNER, fx_rate=None):
    async with sm() as session:
        row = await record_payment(session, case_id, amount=Decimal(amount), currency=currency,
                                   by=by, idempotency_key=key, fx_rate=fx_rate)
        await session.commit()
        return row.id


async def _events(sm, case_id):
    async with sm() as session:
        rows = await session.scalars(select(ServiceEvent).where(
            ServiceEvent.case_id == case_id))
        return [(r.event_type, r.payload) for r in rows]


def _audit(store, action):
    return [a for a in store._audit if a["action"] == action]


def test_s1_full_payment_marks_the_dialog_won_with_the_case_as_reason(flag_on):
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        result = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        assert result == "won"
        conv = await store.get(KEY)
        assert conv.outcome == "won"
        assert conv.sale_amount == 500.0 and conv.sale_currency == "USD"
        sale = _audit(store, "sale_full_payment")
        assert len(sale) == 1 and sale[0]["user_id"] == KEY
        assert f"case={case.id}" in sale[0]["detail"] and "500.00 USD" in sale[0]["detail"]
        assert len(_audit(store, "sale_fp_dialog")) == 1
        events = [e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]
        assert len(events) == 1
        assert events[0][1]["agreed"] == "500.00" and events[0][1]["overpaid"] == "0.00"

    run_with_db(scenario)


def test_s2_partial_payment_is_not_a_sale(flag_on):
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "300.00", "USD", "p1")
        result = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        assert result == "not_full"
        assert (await store.get(KEY)).outcome == ""
        assert store._audit == []
        assert not [e for e in await _events(sm, case.id) if e[0] in (SALE_EVENT,)]

    run_with_db(scenario)


def test_s3_foreign_currency_without_a_rate_does_not_count(flag_on):
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session, amount="50000.00", currency="KGS")
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        result = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        assert result == "not_full"
        assert (await store.get(KEY)).outcome == ""
        async with sm() as session:
            balance = await balance_of(session, case.id, by=OWNER)
        assert balance.unconverted == {"USD": Decimal("500.00")}
        assert balance.paid == Decimal("0.00")

    run_with_db(scenario)


def test_s4_the_same_payment_twice_is_one_record_and_one_sale(flag_on):
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        first = await _pay(sm, case.id, "500.00", "USD", "same-key")
        r1 = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        second = await _pay(sm, case.id, "500.00", "USD", "same-key")
        r2 = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        assert (r1, r2) == ("won", "already")
        assert first == second
        async with sm() as session:
            count = len(list(await session.scalars(select(ServicePayment))))
        assert count == 1
        assert len(_audit(store, "sale_full_payment")) == 1
        assert len(_audit(store, "sale_fp_dialog")) == 1
        assert len([e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]) == 1

    run_with_db(scenario)


def test_s7_overpayment_is_one_sale_with_the_excess_visible(flag_on):
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "600.00", "USD", "p1")
        result = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        assert result == "won"
        events = [e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]
        assert len(events) == 1 and events[0][1]["overpaid"] == "100.00"
        # Сумма продажи — по договору, не по переплате: отчёт не должен раздуваться.
        assert (await store.get(KEY)).sale_amount == 500.0
        async with sm() as session:
            assert (await balance_of(session, case.id, by=OWNER)).needs_attention

    run_with_db(scenario)


def test_s6_refund_after_the_sale_keeps_won_and_flags_once(flag_on):
    """Решение Алана 15.10: финал не откатывается автоматом, только пометка."""
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "won"
        async with sm() as session:
            await record_refund_paid(session, case.id, amount=Decimal("200.00"), currency="USD",
                                     by=CHIEF, idempotency_key="r1", reason="возврат")
            await session.commit()
        r_first = await sale_by_payment.evaluate_after_money_write(
            case.id, CHIEF, "chief", sessionmaker=sm, store=store)
        async with sm() as session:
            await record_refund_paid(session, case.id, amount=Decimal("100.00"), currency="USD",
                                     by=CHIEF, idempotency_key="r2", reason="ещё возврат")
            await session.commit()
        r_second = await sale_by_payment.evaluate_after_money_write(
            case.id, CHIEF, "chief", sessionmaker=sm, store=store)
        assert (r_first, r_second) == ("reversal", "not_full")
        assert (await store.get(KEY)).outcome == "won"
        reversal = _audit(store, "sale_fp_reversal")
        assert len(reversal) == 1 and reversal[0]["user_id"] == KEY
        kinds = [e[0] for e in await _events(sm, case.id)]
        assert kinds.count(SALE_EVENT) == 1 and kinds.count(SALE_REVERSAL_EVENT) == 1
        # Деньги снова покрыли договор: пометка «восстановлено», продажа не удваивается.
        await _pay(sm, case.id, "300.00", "USD", "p2")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "already"
        kinds = [e[0] for e in await _events(sm, case.id)]
        assert kinds.count(SALE_EVENT) == 1 and kinds.count(SALE_RESTORED_EVENT) == 1
        assert len(_audit(store, "sale_full_payment")) == 1

    run_with_db(scenario)


def test_flag_off_reads_and_writes_nothing(monkeypatch):
    flags.reset()
    monkeypatch.setattr(settings, "sale_by_full_payment_enabled", False, raising=False)

    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        result = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        assert result == "off"
        assert (await store.get(KEY)).outcome == ""
        assert store._audit == []
        assert not [e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]

    run_with_db(scenario)


def test_a_manual_final_outcome_is_not_overwritten(flag_on):
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store, outcome="lost")
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        result = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        assert result == "conflict"
        assert (await store.get(KEY)).outcome == "lost"
        assert len(_audit(store, "sale_full_payment")) == 1   # продажа по делу — факт
        assert len(_audit(store, "sale_fp_conflict")) == 1
        assert _audit(store, "sale_fp_dialog") == []
        # Повторный пересчёт не спамит конфликтом второй раз.
        await _pay(sm, case.id, "1.00", "USD", "p2")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "already"
        assert len(_audit(store, "sale_fp_conflict")) == 1

    run_with_db(scenario)


def test_without_a_dialog_the_sale_is_still_recorded_on_the_case(flag_on):
    async def scenario(sm):
        store = MemoryConversationStore()
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        result = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        assert result == "no_dialog"
        sale = _audit(store, "sale_full_payment")
        assert len(sale) == 1 and sale[0]["user_id"] == ""
        assert len([e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]) == 1

    run_with_db(scenario)


def test_only_dialogs_of_the_case_direction_are_marked(flag_on):
    """Тот же номер пишет и по визам, и по турам: туровый договор не продаёт визу."""
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        await _dialog(store, f"getvisa:{PHONE}", bot="getvisa", funnel="visa")
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "won"
        assert (await store.get(KEY)).outcome == "won"
        assert (await store.get(f"getvisa:{PHONE}")).outcome == ""

    run_with_db(scenario)


def test_a_panel_store_failure_keeps_the_payment_and_heals_on_the_next_pass(flag_on):
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")

        class Broken(Exception):
            pass

        real_claim = store.claim_outcome

        async def boom(user_id, outcome):
            raise Broken("панель недоступна")

        store.claim_outcome = boom
        result = await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store)
        assert result == "error"
        async with sm() as session:
            assert (await balance_of(session, case.id, by=OWNER)).paid == Decimal("500.00")
        assert (await store.get(KEY)).outcome == ""
        # Следующая денежная операция дозакрывает диалог без второй продажи.
        store.claim_outcome = real_claim
        await _pay(sm, case.id, "1.00", "USD", "p2")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "won"
        assert (await store.get(KEY)).outcome == "won"
        assert len([e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]) == 1
        # Запись о продаже в журнале — одна: её считает отчёт пилота (ревью 15.10, п.1).
        assert len(_audit(store, "sale_full_payment")) == 1
        assert len(_audit(store, "sale_fp_dialog")) == 1

    run_with_db(scenario)


def test_a_journal_failure_after_the_event_is_healed_without_a_second_sale(flag_on):
    """Панель упала на самой записи о продаже: событие в домене есть, журнала нет."""
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        real_add = store.add_audit

        async def boom(*args, **kwargs):
            raise RuntimeError("журнал недоступен")

        store.add_audit = boom
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "error"
        assert (await store.get(KEY)).outcome == ""
        # Журнал пишется под блокировкой дела, до коммита: событие откатилось вместе с ним.
        assert not [e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]
        store.add_audit = real_add
        await _pay(sm, case.id, "1.00", "USD", "p2")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "won"
        assert len(_audit(store, "sale_full_payment")) == 1
        assert (await store.get(KEY)).outcome == "won"
        # Третий проход: ничего нового.
        await _pay(sm, case.id, "1.00", "USD", "p3")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "already"
        assert len(_audit(store, "sale_full_payment")) == 1

    run_with_db(scenario)


def test_a_domain_commit_failure_after_the_journal_does_not_double_the_sale(flag_on):
    """Аудит 15.10, блокер B1: журнал панели закоммичен, коммит домена упал. Следующий
    проход записывает событие, но строка `sale_full_payment` остаётся одна."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")

        class BoomOnce(AsyncSession):
            armed = True

            async def commit(self):
                if BoomOnce.armed:
                    BoomOnce.armed = False
                    await self.rollback()
                    raise RuntimeError("обрыв соединения на коммите")
                await super().commit()

        boom_sm = async_sessionmaker(sm.kw["bind"], class_=BoomOnce, expire_on_commit=False)
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=boom_sm, store=store) == "error"
        assert len(_audit(store, "sale_full_payment")) == 1       # журнал уже закоммичен
        assert not [e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]
        assert (await store.get(KEY)).outcome == ""
        await _pay(sm, case.id, "1.00", "USD", "p2")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "won"
        assert len(_audit(store, "sale_full_payment")) == 1
        assert len([e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]) == 1
        assert (await store.get(KEY)).outcome == "won"

    run_with_db(scenario)


def test_an_unsigned_preliminary_case_is_never_a_sale(flag_on):
    """Аудит 15.10, зам. 2: без подписи договора продажа не считается (FLOW-02)."""
    from app.domain.models import ServiceCase

    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        async with sm() as session:
            # Подпись снимается прямо на объекте: доменного пути «распечатать» нет, а
            # предварительное дело без подписи рождается в другом модуле.
            row = await session.get(ServiceCase, case.id)
            row.signed_at = None
            await session.commit()
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "unsigned"
        assert (await store.get(KEY)).outcome == ""
        assert store._audit == []
        assert not [e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]

    run_with_db(scenario)


def test_healing_never_marks_dialogs_that_appeared_after_the_sale(flag_on):
    """Аудит 15.10, H1: новое обращение клиента после продажи — отдельный лид, `won` ему
    не ставится; старому диалогу исход второй раз не навязывается."""
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session)
            await session.commit()
        await _pay(sm, case.id, "600.00", "USD", "p1")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "won"
        # Новое обращение того же клиента в другом туровом канале.
        new_key = f"frunze_tours_tg:{PHONE}"
        await _dialog(store, new_key, bot="frunze_tours_tg")
        # Старому диалогу человек поставил другой исход (прямо в хранилище: кнопка
        # панели меняет won только на lost, а защёлка и от него защищает).
        store._conv[KEY].outcome = "office"
        async with sm() as session:
            await record_refund_paid(session, case.id, amount=Decimal("100.00"), currency="USD",
                                     by=CHIEF, idempotency_key="r1", reason="переплата")
            await session.commit()
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, CHIEF, "chief", sessionmaker=sm, store=store) == "already"
        assert (await store.get(new_key)).outcome == ""
        assert (await store.get(new_key)).sale_amount is None
        assert (await store.get(KEY)).outcome == "office"
        assert len(_audit(store, "sale_fp_dialog")) == 1
        assert len(_audit(store, "sale_full_payment")) == 1

    run_with_db(scenario)


def test_correcting_the_contract_amount_down_can_complete_the_sale(flag_on):
    """Триггер — любая денежная операция, не только оплата: договор 600, оплачено 500,
    руководитель поправил сумму до 500 — продажа."""
    async def scenario(sm):
        store = MemoryConversationStore()
        await _dialog(store)
        async with sm() as session:
            case = await _contract(session, amount="600.00")
            await session.commit()
        await _pay(sm, case.id, "500.00", "USD", "p1")
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, OWNER, "ademi", sessionmaker=sm, store=store) == "not_full"
        async with sm() as session:
            await correct_contract_amount(session, case.id, amount=Decimal("500.00"),
                                          currency="USD", by=CHIEF, reason="скидка")
            await session.commit()
        assert await sale_by_payment.evaluate_after_money_write(
            case.id, CHIEF, "chief", sessionmaker=sm, store=store) == "won"
        assert (await store.get(KEY)).outcome == "won"
        events = [e for e in await _events(sm, case.id) if e[0] == SALE_EVENT]
        assert len(events) == 1 and events[0][1]["agreed"] == "500.00"

    run_with_db(scenario)
