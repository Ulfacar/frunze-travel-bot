import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timezone

import pytest
from sqlalchemy import event,select,text,update,func
from sqlalchemy.orm import Session

from app.domain import entry_quotes as service
from app.domain.entry_quote_policy import policy_from_document
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,EntryStorageUnavailable,_hash,_plain
from app.domain.models import EntryQuoteRevision,DomainBase,DomainError
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_entry_interviews import admins
from tests import test_entry_applications as apps
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_quote_rules import recipe,request,line,na,unknown


def policy(r=None,**changes):
    return policy_from_document(dict(format='kg-quote-policy/1',reference='SYN-QUOTE-AUTH',proof='f'*64,
        operators=['admin'],valid_from='2026-01-01',review_due_on='2027-01-01',recipes=[r or recipe()])|changes)


def subject(env,**changes):return apps.application(env,apps.person(env),**changes)


def preview(env,app,**changes):
    return asyncio.run(service.preview_quote(env['engine'],**(dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],parameters=request(),policy=policy())|changes)))


def args(env,app,*,previewed=None,**changes):
    value=(previewed or preview(env,app))['preview']
    return dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],parameters=value['parameters'],
        expected_revision=value['expected_revision'],request_key='QUOTE-'+str(value['expected_revision']),
        expected_policy_hash=value['policy_hash'],expected_preview_hash=_hash(value),
        calculator_version=value['calculator_version'],policy=policy())|changes


def save(env,app,**changes):return asyncio.run(service.save_quote(env['engine'],**args(env,app,**changes)))


def read(env,app,**changes):
    return asyncio.run(service.read_quotes(env['engine'],**(dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],policy=policy())|changes)))


def counts(env):
    async def run():
        async with env['sm']() as s:return {t.name:await s.scalar(select(func.count()).select_from(t)) for t in DomainBase.metadata.sorted_tables}
    return asyncio.run(run())


def test_preview_is_readonly_saved_unknown_blocks_total_and_other_domain_is_unchanged(env):
    app=subject(env);before=counts(env);p=preview(env,app);assert counts(env)==before
    saved=save(env,app,previewed=p);after=counts(env)
    assert {k:after[k]-before[k] for k in before if after[k]!=before[k]}=={'entry_quote_revisions':1}
    assert saved['receipt']['result']['known_subtotals']=={'USD':'100.00'}
    assert saved['receipt']['result']['totals_by_currency'] is None and not saved['current']['usable']
    assert read(env,app)['history'][0]==saved


def test_complete_quote_is_scoped_to_one_person_and_mixed_currencies(env):
    app=subject(env);r=recipe();r['lines'][2]=line('bank','1.20',currency='KGS');p=policy(r)
    shown=preview(env,app,policy=p,parameters=request(urgent=True));saved=save(env,app,previewed=shown,policy=p)
    assert saved['receipt']['applicant_id']==app['applicant_id'] and saved['receipt']['result']['applicants']==1
    assert saved['receipt']['result']['totals_by_currency']=={'KGS':'1.20','USD':'200.00'}
    assert saved['current']['usable'] and saved['current']['settlement_fx']=='not_available'
    assert not read(env,app,policy=None)['history'][0]['current']['usable']


def test_old_exact_retry_survives_policy_removal_replacement_and_later_revision(env):
    app=subject(env);old=args(env,app);first=asyncio.run(service.save_quote(env['engine'],**old))
    changed=recipe(version='SYN-V2');changed['lines'][0]['amount']='60.00';new_policy=policy(changed)
    second=save(env,app,previewed=preview(env,app,policy=new_policy),policy=new_policy,request_key='NEW')
    retry=asyncio.run(service.save_quote(env['engine'],**(old|{'policy':None})))
    assert retry['receipt']==first['receipt'] and 'quote_superseded' in retry['current']['reasons']
    assert 'quote_policy_unavailable' in retry['current']['reasons'] and counts(env)['entry_quote_revisions']==2
    current=read(env,app,policy=new_policy)
    assert current['history'][0]['receipt']==second['receipt'] and current['history'][1]['receipt']==first['receipt']
    with pytest.raises(EntryStorageConflict,match='request_conflict'):
        asyncio.run(service.save_quote(env['engine'],**(old|{'parameters':request(urgent=True)})))


def test_observed_application_head_survives_growth_but_current_quote_becomes_stale(env):
    app=subject(env);r=recipe();r['lines'][2]=na('bank');p=policy(r)
    old=args(env,app,previewed=preview(env,app,policy=p),policy=p);first=asyncio.run(service.save_quote(env['engine'],**old))
    apps.record(env,app);current=read(env,app,policy=p)['history'][0]
    assert current['receipt']==first['receipt'] and current['current']['reasons']==['quote_application_changed']
    assert asyncio.run(service.save_quote(env['engine'],**old))['receipt']==first['receipt']
    with pytest.raises(EntryStorageConflict):
        asyncio.run(service.save_quote(env['engine'],**(old|{'request_key':'STALE','expected_revision':1})))
    second=save(env,app,previewed=preview(env,app,policy=p),policy=p,request_key='NEW-HEAD')
    assert second['receipt']['source_pin']['event_revision']==2 and second['current']['usable']


@pytest.mark.parametrize('status',['approved','refused','closed'])
def test_terminal_application_preserves_history_but_denies_new_calculation(env,status):
    app=subject(env);save(env,app);apps.record(env,app)
    apps.record(env,app,key='TERMINAL',status=status,occurred_on='2026-09-02')
    current=read(env,app);assert not current['can_calculate'] and not current['history'][0]['current']['usable']
    with pytest.raises(EntryStorageInvalid,match='terminal'):preview(env,app)
    if status=='refused':
        successor=apps.application(env,{'id':app['applicant_id']},key='SUCCESSOR',previous=app['id'])
        assert not read(env,app)['can_calculate'] and read(env,successor)['revision']==0


def test_wrong_procedure_case_applicant_and_global_case_request_key_are_rejected(env):
    app=subject(env);old=args(env,app);asyncio.run(service.save_quote(env['engine'],**old))
    other=apps.application(env,apps.person(env,key='OTHER'),key='OTHER')
    with pytest.raises(EntryStorageConflict,match='request_conflict'):
        save(env,other,request_key=old['request_key'])
    with pytest.raises(EntryStorageInvalid):preview(env,app,case_id=env['cases']['other'])
    wrong=recipe(procedure='registration')
    with pytest.raises(EntryStorageInvalid,match='procedure_mismatch'):preview(env,app,policy=policy(wrong))
    with pytest.raises(EntryStorageInvalid):preview(env,app,parameters=request(quantity=3))


@pytest.mark.parametrize('method',['read','preview','save'])
def test_current_identity_revoked_before_any_database_access(env,monkeypatch,method):
    from app.config import settings
    app=subject(env);stored=args(env,app);monkeypatch.setattr(settings,'admin_user','replacement')
    monkeypatch.setattr(settings,'managers',[m for m in settings.managers if m.login!='admin'])
    def forbidden(*a,**kw):raise AssertionError('database accessed after revocation')
    monkeypatch.setattr(service.applications,'_run',forbidden)
    with pytest.raises(PermissionDenied):
        if method=='read':read(env,app)
        elif method=='preview':preview(env,app)
        else:asyncio.run(service.save_quote(env['engine'],**stored))


def test_policy_and_preview_parameters_cannot_change_between_preview_and_save(env):
    app=subject(env);stored=args(env,app)
    with pytest.raises(EntryStorageConflict,match='preview_changed'):
        asyncio.run(service.save_quote(env['engine'],**(stored|{'parameters':request(urgent=True)})))
    with pytest.raises(EntryStorageConflict,match='policy_changed'):
        asyncio.run(service.save_quote(env['engine'],**(stored|{'policy':policy(proof='e'*64)})))
    assert read(env,app)['revision']==0


def test_midnight_expiry_and_backwards_clock_cannot_persist_invalid_history(env,monkeypatch):
    app=subject(env);today=service.applications._today();p=policy(review_due_on=today.isoformat())
    original=service._now;shown=preview(env,app,policy=p);stored=args(env,app,previewed=shown,policy=p)
    monkeypatch.setattr(service,'_now',lambda:datetime(2028,1,1,tzinfo=timezone.utc))
    with pytest.raises(PermissionDenied):asyncio.run(service.save_quote(env['engine'],**stored))
    monkeypatch.setattr(service,'_now',original);save(env,app)
    changed=args(env,app,request_key='BACKWARD')
    monkeypatch.setattr(service,'_now',lambda:datetime(2026,1,2,tzinfo=timezone.utc))
    with pytest.raises(EntryStorageInvalid,match='clock_moved'):asyncio.run(service.save_quote(env['engine'],**changed))
    assert read(env,app)['revision']==1


@pytest.mark.parametrize('at',['before_commit','after_commit'])
def test_commit_uncertainty_preserves_original_receipt(env,at):
    app=subject(env);stored=args(env,app);calls=[]
    def fault(session):
        if not calls:calls.append(True);raise RuntimeError('synthetic commit fault')
    event.listen(Session,at,fault)
    try:
        with pytest.raises(EntryStorageUnavailable):asyncio.run(service.save_quote(env['engine'],**stored))
    finally:event.remove(Session,at,fault)
    saved=asyncio.run(service.save_quote(env['engine'],**stored))
    assert read(env,app)['revision']==1 and read(env,app)['history'][0]['receipt']==saved['receipt']


def test_concurrent_identical_and_competing_saves_preserve_one_revision(env):
    app=subject(env);stored=args(env,app)
    def run(values):
        try:return asyncio.run(service.save_quote(env['engine'],**values))
        except EntryStorageConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[stored,stored]))
    assert results[0]==results[1] and read(env,app)['revision']==1
    first=args(env,app);second=first|{'request_key':'COMPETING'}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[first,second]))
    assert results.count('conflict')==1 and read(env,app)['revision']==2


def test_orm_and_bulk_mutations_cannot_rewrite_quote(env):
    app=subject(env);saved=save(env,app)
    async def run():
        async with env['sm']() as s:
            row=await s.get(EntryQuoteRevision,saved['receipt']['id']);row.created_by='replacement'
            with pytest.raises(DomainError):await s.commit()
        async with env['sm']() as s:
            with pytest.raises(DomainError):await s.execute(update(EntryQuoteRevision).values(created_by='replacement'))
    asyncio.run(run());assert read(env,app)['history'][0]['receipt']==saved['receipt']


@pytest.mark.parametrize('kind',['total','omitted_line','source','reducer'])
def test_fully_rehashed_semantic_tamper_is_rejected(env,kind):
    app=subject(env);saved=save(env,app)
    async def tamper():
        async with env['sm']() as s:
            row=await s.get(EntryQuoteRevision,saved['receipt']['id']);result=_plain(row.result);command=_plain(row.command);pin=_plain(row.source_pin)
            if kind=='total':result['complete']=True;result['totals_by_currency']={'USD':'1.00'}
            if kind=='omitted_line':result['lines'].pop()
            if kind=='source':pin['event_hash']='0'*64
            if kind=='reducer':command['calculator_version']='kg-quote-calculator/99'
            row.result=result;row.command=command;row.source_pin=pin;row.request_hash=_hash(command);row.snapshot_hash=_hash(service._payload(row))
            values=dict(result=result,command=command,source_pin=pin,request_hash=row.request_hash,snapshot_hash=row.snapshot_hash)
            s.expunge(row)
        async with env['engine'].begin() as conn:await conn.execute(EntryQuoteRevision.__table__.update().where(EntryQuoteRevision.id==saved['receipt']['id']).values(**values))
    asyncio.run(tamper())
    with pytest.raises(EntryStorageInvalid):read(env,app)


def test_history_capacity_preserves_reads_and_exact_retry(env,monkeypatch):
    app=subject(env);stored=args(env,app);first=asyncio.run(service.save_quote(env['engine'],**stored))
    monkeypatch.setattr(service,'MAX_REVISIONS',1)
    assert not read(env,app)['can_calculate']
    assert asyncio.run(service.save_quote(env['engine'],**stored))['receipt']==first['receipt']
    with pytest.raises(EntryStorageInvalid,match='history_limit'):save(env,app)
    assert read(env,app)['revision']==1


def test_policy_object_is_immutable_and_unknown_catalog_never_defaults_to_real_prices(env):
    p=policy();doc=p.document();doc['recipes'][0]['lines'][0]['amount']='1.00'
    assert p.document()['recipes'][0]['lines'][0]['amount']=='50.00'
    app=subject(env)
    with pytest.raises(PermissionDenied):preview(env,app,policy=None)
    assert not read(env,app,policy=None)['can_calculate']


def test_byte_capacity_preserves_full_history_and_original_retry(env,monkeypatch):
    app=subject(env);stored=args(env,app);first=asyncio.run(service.save_quote(env['engine'],**stored))
    async def size():
        async with env['sm']() as s:
            row=await s.get(EntryQuoteRevision,first['receipt']['id'])
            return len(service.canonical(service._payload(row)).encode())
    monkeypatch.setattr(service,'MAX_HISTORY_BYTES',asyncio.run(size()))
    assert asyncio.run(service.save_quote(env['engine'],**stored))['receipt']==first['receipt']
    with pytest.raises(EntryStorageInvalid,match='history_limit'):save(env,app)
    assert read(env,app)['revision']==1


def test_new_operator_cannot_reuse_another_actors_request_key(env):
    app=subject(env);p=policy(operators=['admin','reviewer']);shown=preview(env,app,policy=p)
    stored=args(env,app,previewed=shown,policy=p);asyncio.run(service.save_quote(env['engine'],**stored))
    with pytest.raises(EntryStorageConflict,match='request_conflict'):
        asyncio.run(service.save_quote(env['engine'],**(stored|{'actor':Actor(manager_id='reviewer',is_full_admin=True)})))
    assert read(env,app,policy=p)['revision']==1


def test_retained_calculator_history_retry_and_new_active_version(env,monkeypatch):
    app=subject(env);r=recipe();r['lines'][2]=na('bank');p=policy(r)
    old=args(env,app,previewed=preview(env,app,policy=p),policy=p)
    first=asyncio.run(service.save_quote(env['engine'],**old));assert first['current']['usable']
    v1=service.rules.CALCULATORS['kg-quote-calculator/1'];v2='kg-quote-calculator/2'
    def new_calculator(*a,**kw):return v1(*a,**kw)|{'calculator_version':v2}
    monkeypatch.setitem(service.rules.CALCULATORS,v2,new_calculator)
    monkeypatch.setattr(service.rules,'VERSION',v2)
    current=read(env,app,policy=p)['history'][0]
    assert current['receipt']==first['receipt'] and current['current']['reasons']==['quote_calculator_changed']
    assert asyncio.run(service.save_quote(env['engine'],**old))==current
    shown=preview(env,app,policy=p)
    assert shown['preview']['calculator_version']==v2 and shown['preview']['result']['calculator_version']==v2
    second=save(env,app,previewed=shown,policy=p)
    assert second['current']['usable'] and second['receipt']['result']['calculator_version']==v2
    assert read(env,app,policy=p)['history'][1]['receipt']==first['receipt']


@pytest.mark.parametrize('kind',['source_rewinds','untyped_revision','untyped_pin','untyped_result','null_version'])
def test_impossible_fully_rehashed_history_fails_closed(env,kind):
    app=subject(env);apps.record(env,app);save(env,app);second=save(env,app)
    async def tamper():
        async with env['sm']() as s:
            row=await s.get(EntryQuoteRevision,second['receipt']['id'])
            command=_plain(row.command);pin=_plain(row.source_pin);result=_plain(row.result)
            if kind=='source_rewinds':
                application,person,events,_=await service._scope(s,env['cases']['visa'],app['id'])
                shown=service._preview_data(application,person,events[0],revision=row.revision-1,
                    policy=policy_from_document(_plain(row.policy)),request=command['parameters'],
                    on=service.applications._local_day(row.created_at).isoformat(),version=command['calculator_version'])
                pin=shown['source_pin'];command['preview_hash']=_hash(shown)
            elif kind=='untyped_revision':command['expected_revision']=True
            elif kind=='untyped_pin':assert pin['attempt']==1;pin['attempt']=True
            elif kind=='untyped_result':assert result['applicants']==1;result['applicants']=True
            else:command['calculator_version']=None
            row.command=command;row.source_pin=pin;row.result=result
            row.request_hash=_hash(command);row.snapshot_hash=_hash(service._payload(row))
            values=dict(command=command,source_pin=pin,result=result,request_hash=row.request_hash,snapshot_hash=row.snapshot_hash)
            s.expunge(row)
        async with env['engine'].begin() as conn:
            await conn.execute(EntryQuoteRevision.__table__.update().where(EntryQuoteRevision.id==second['receipt']['id']).values(**values))
    asyncio.run(tamper())
    with pytest.raises(EntryStorageInvalid):read(env,app)
