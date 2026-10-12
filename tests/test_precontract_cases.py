import asyncio
from datetime import datetime,timezone
from decimal import Decimal

import pytest
from sqlalchemy import select,func

from app.config import settings,ManagerConfig
from app.domain import precontract_cases as service,service_cases as cases,service_money as money
from app.domain.models import Contact,Product,ServiceCase,ServiceEvent,ServiceCaseOpening,CalendarTask,DomainError,ServicePayment
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_service_cases import run_with_db

ADMIN=Actor('admin',True)
OWNER=Actor('manager',allowed_directions=frozenset({'visa'}))
OTHER=Actor('peer',allowed_directions=frozenset({'visa'}))
STAGES=[dict(code='IN-01',name='Подготовка',first_task=dict(kind='call',comment='Synthetic task',due_in_days=1)),
        dict(code='IN-02',name='Следующий')]
TRANSITIONS={'IN-01':['IN-02'],'IN-02':[]}


@pytest.fixture(autouse=True)
def managers(monkeypatch):
    monkeypatch.setattr(settings,'managers',[ManagerConfig(login=n,name=n,password='SYN-ONLY') for n in ('admin','manager','peer')])


async def prepare(session):
    contact=Contact();session.add(contact);await session.flush()
    product=await cases.create_product(session,code='synthetic_preliminary',name='Synthetic visa service',direction='visa',by=ADMIN)
    await cases.publish_version(session,product.id,STAGES,TRANSITIONS,'admin',by=ADMIN)
    await session.commit()
    return dict(contact_id=contact.id,product_id=product.id,workflow_version_id=product.current_version_id,
        owner_login='manager',by=ADMIN,request_key='SYN-OPEN')


def signing(receipt,**kw):
    return dict(case_id=receipt['case_id'],expected_revision=receipt['revision'],by=ADMIN,reference='SYN-CONTRACT',
        signed_at=datetime(2026,10,13,8,tzinfo=timezone.utc),amount='100.50',currency='KGS',request_key='SYN-SIGN')|kw


async def counts(session):
    return {model.__tablename__:await session.scalar(select(func.count()).select_from(model))
        for model in (ServiceCase,ServiceCaseOpening,ServiceEvent,CalendarTask,ServicePayment)}


def test_open_then_sign_same_case_and_historical_retries_survive_new_workflow_price_and_owner():
    async def run(sm):
        async with sm() as s:
            command=await prepare(s);opened=await service.open_preliminary(s,**command);await s.commit()
            case=await s.get(ServiceCase,opened['case_id']);assert case.signed_at is None and case.idempotency_key is None
            assert (await counts(s))==dict(service_cases=1,service_case_openings=1,service_events=1,calendar_tasks=0,service_payments=0)
            await cases.publish_version(s,command['product_id'],STAGES,TRANSITIONS,'admin',by=ADMIN);await s.commit()
            assert await service.open_preliminary(s,**command)==opened|{'duplicate':True}
            signed=await service.record_signed_contract(s,**signing(opened));await s.commit()
            assert signed['case_id']==opened['case_id'] and signed['workflow_version_id']==command['workflow_version_id']
            assert await service.record_signed_contract(s,**signing(opened))==signed|{'duplicate':True}
            assert (await counts(s))==dict(service_cases=1,service_case_openings=1,service_events=2,calendar_tasks=1,service_payments=0)
            await money.correct_contract_amount(s,case.id,amount='200.00',currency='KGS',by=ADMIN,reason='Synthetic correction')
            await cases.reassign_case(s,case.id,target_login='peer',by=ADMIN,reason='Synthetic reassignment');await s.commit()
            before=await counts(s)
            assert await service.open_preliminary(s,**command)==opened|{'duplicate':True}
            assert await service.record_signed_contract(s,**signing(opened))==signed|{'duplicate':True}
            assert await counts(s)==before
            await s.refresh(case);assert case.owner_login=='peer' and case.agreed_amount==Decimal('200.00')
    run_with_db(run)


@pytest.mark.parametrize('change',[{'reference':'CHANGED'},{'amount':'101.00'},{'request_key':'SECOND'},
    {'signed_at':datetime(2026,10,14,tzinfo=timezone.utc)},{'expected_revision':2}])
def test_changed_signature_cannot_be_replayed_or_create_second_contract(change):
    async def run(sm):
        async with sm() as s:
            command=await prepare(s);opened=await service.open_preliminary(s,**command)
            await service.record_signed_contract(s,**signing(opened));await s.commit();before=await counts(s)
            with pytest.raises(DomainError,match='conflict'):await service.record_signed_contract(s,**signing(opened,**change))
            await s.commit();assert await counts(s)==before
    run_with_db(run)


def test_current_access_and_scope_enforced_on_open_and_signed_retry():
    async def run(sm):
        async with sm() as s:
            command=await prepare(s);opened=await service.open_preliminary(s,**command);await s.commit()
            for by in (OTHER,Actor('none')):
                with pytest.raises(PermissionDenied):await service.open_preliminary(s,**(command|{'by':by}))
                with pytest.raises(PermissionDenied):await service.record_signed_contract(s,**signing(opened,by=by))
            assert (await counts(s))['service_events']==1
    run_with_db(run)


@pytest.mark.parametrize('change',[{'expected_revision':999},{'amount':'0'},{'amount':True},{'amount':'1.001'},
    {'amount':None},{'currency':'bad-code'},{'signed_at':datetime(2026,10,13)}, {'reference':''}])
def test_invalid_or_stale_signature_does_not_mutate_preliminary_case(change):
    async def run(sm):
        async with sm() as s:
            command=await prepare(s);opened=await service.open_preliminary(s,**command);await s.commit();before=await counts(s)
            with pytest.raises(DomainError):await service.record_signed_contract(s,**signing(opened,**change))
            await s.commit();assert await counts(s)==before
            assert (await s.get(ServiceCase,opened['case_id'])).signed_at is None
    run_with_db(run)


def test_failed_initial_task_rolls_back_signature_but_keeps_callers_write(monkeypatch):
    async def fail(*args,**kwargs):raise RuntimeError('SYN-TASK-FAIL')
    async def run(sm):
        async with sm() as s:
            command=await prepare(s);opened=await service.open_preliminary(s,**command);await s.commit()
            extra=Contact();s.add(extra);await s.flush();extra_id=extra.id
            with monkeypatch.context() as patch:
                patch.setattr(cases,'_create_initial_tasks',fail)
                with pytest.raises(RuntimeError,match='SYN-TASK-FAIL'):await service.record_signed_contract(s,**signing(opened))
            await s.commit()
            case=await s.get(ServiceCase,opened['case_id']);assert case.signed_at is None and case.agreed_amount is None
            assert await s.get(Contact,extra_id) is not None and (await counts(s))['service_events']==1
            await service.record_signed_contract(s,**signing(opened));await s.commit()
            assert (await counts(s))['calendar_tasks']==1
    run_with_db(run)


def test_unknown_amount_and_existing_explicit_payment_stay_distinct():
    async def run(sm):
        async with sm() as s:
            command=await prepare(s);opened=await service.open_preliminary(s,**command)
            await money.record_payment(s,opened['case_id'],amount='25',currency='USD',by=OWNER,idempotency_key='SYN-PAY')
            await s.commit()
            case=await s.get(ServiceCase,opened['case_id'])
            await service.record_signed_contract(s,**signing(opened,expected_revision=case.revision,amount=None,currency=None,amount_unknown_reason='Await explicit amount'))
            await s.commit();await s.refresh(case)
            assert case.agreed_amount is None and case.amount_unknown_reason=='Await explicit amount'
            assert (await counts(s))['service_payments']==1
    run_with_db(run)
