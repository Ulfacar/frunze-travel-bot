from decimal import Decimal as D
from types import SimpleNamespace as Row

from app.core.report_finance import summarize


def payment(pk, case, amount, currency="USD", kind="payment", corrects=None):
    return Row(id=pk, case_id=case, amount=D(amount), currency=currency,
               kind=kind, corrects_id=corrects, settles_id=None, fx_rate=None, fx_to=None)


def test_partial_full_refund_and_currencies():
    cases = [Row(id=1, agreed_amount=D(100), currency="USD"),
             Row(id=2, agreed_amount=D(100), currency="KGS")]
    result = summarize(cases, [payment(1, 1, 50), payment(2, 1, 10, kind="refund_paid"),
                               payment(3, 2, 100, "KGS")])
    currencies = {r["currency"]: r for r in result["currencies"]}
    assert currencies["USD"]["paid"] == 50
    assert currencies["USD"]["remaining"] == currencies["USD"]["additional"] == 60
    assert currencies["KGS"]["remaining"] == currencies["KGS"]["additional"] == 0


def test_correction_and_unknown_amount():
    cases = [Row(id=1, agreed_amount=D(100), currency="USD"),
             Row(id=2, agreed_amount=None, currency="USD")]
    result = summarize(cases, [payment(1, 1, 50), payment(2, 1, 40, kind="correction", corrects=1),
                               payment(3, 1, 90, "EUR")])
    assert result["currencies"][0]["paid"] == 40
    assert result["unknown_contracts"] == result["unconverted_contracts"] == 1


def test_sale_definitions_and_refund_do_not_duplicate_sale():
    from datetime import datetime, timedelta, timezone
    from app.core.report_finance import sale_dates
    signed = datetime(2026, 11, 1, tzinfo=timezone.utc)
    case = Row(id=1, contact_id=7, agreed_amount=D(100), currency="USD", signed_at=signed)
    rows = [payment(1, 1, 50), payment(2, 1, 50), payment(3, 1, 20, kind="refund_paid")]
    for i, row in enumerate(rows):
        row.recorded_at = signed + timedelta(days=i + 1)
    pre, full = sale_dates([case], {1: rows}, signed + timedelta(days=5))
    assert pre == {7: signed + timedelta(days=1)}
    assert full == {7: signed + timedelta(days=2)}


def test_contract_price_change_does_not_backdate_sale():
    from datetime import datetime, timedelta, timezone
    from app.core.report_finance import sale_dates
    signed = datetime(2026, 11, 1, tzinfo=timezone.utc)
    case = Row(id=1, contact_id=7, agreed_amount=D(50), currency="USD", signed_at=signed)
    paid = payment(1, 1, 50)
    paid.recorded_at = signed + timedelta(days=1)
    change = Row(id=1, case_id=1, recorded_at=signed + timedelta(days=2),
                 payload={"previous_amount": "100", "previous_currency": "USD", "amount": "50", "currency": "USD"})
    pre, full = sale_dates([case], {1: [paid]}, signed + timedelta(days=3), [change])
    assert pre[7] == paid.recorded_at
    assert full[7] == change.recorded_at


def test_sql_loader_scopes_owner_and_direction(tmp_path):
    import asyncio
    from datetime import datetime, timezone, timedelta
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.domain.models import DomainBase, Product, Contact, ServiceCase, ServicePayment, WorkflowVersion
    from app.core.report_finance import load
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "finance.db"))
        sm = async_sessionmaker(engine, expire_on_commit=False)
        at = datetime(2026, 11, 1, tzinfo=timezone.utc)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(DomainBase.metadata.create_all)
            async with sm() as s:
                s.add_all([Product(id=1, code="fixture-visa", name="Fixture", direction="visa"),
                           Product(id=2, code="fixture-tours", name="Fixture", direction="tours")])
                s.add(Contact(id=1))
                await s.flush()
                for product in (1, 2):
                    s.add(WorkflowVersion(id=product, product_id=product, version=1,
                                          stages=[{"code": "signed"}], transitions={}, published_at=at))
                await s.flush()
                for pk, product, owner in ((1, 1, "fixture-a"), (2, 1, "fixture-b"), (3, 2, "fixture-a")):
                    s.add(ServiceCase(id=pk, contact_id=1, product_id=product, workflow_version_id=product,
                                      owner_login=owner, stage="signed", signed_at=at,
                                      agreed_amount=D(100), currency="USD"))
                await s.flush()
                for pk in (1, 2, 3):
                    s.add(ServicePayment(case_id=pk, kind="payment", amount=D(50), currency="USD",
                                         idempotency_key=f"fixture-{pk}", recorded_by="fixture-a", recorded_at=at))
                await s.commit()
            own = await load(sm, "visa", "fixture-a", at + timedelta(days=1))
            team = await load(sm, "visa", None, at + timedelta(days=1))
            assert own["currencies"][0]["paid"] == 50
            assert team["currencies"][0]["paid"] == 100
            assert own["open_tasks"] == 0
        finally:
            await engine.dispose()
    asyncio.run(run())
