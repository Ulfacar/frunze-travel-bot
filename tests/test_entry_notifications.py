"""Real scoped draft journal, literal source rendering and adversarial history."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json

import pytest
from sqlalchemy import Text,cast,event,func,select,text,update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.domain import entry_notifications as service
from app.domain.entry_notification_policy import policy_from_document
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,EntryStorageUnavailable,_hash,_plain
from app.domain.models import DomainBase,DomainError,EntryNotificationDraft
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_entry_interviews import admins
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests import test_entry_applications as apps


def policy(**changes):
    return policy_from_document(dict(format='kg-notification-storage-policy/1',reference='SYN-DRAFT',proof='a'*64,
        privacy_reference='SYN-PRIVACY',privacy_proof='b'*64,source_reference='SYN-SOURCE',source_proof='c'*64,
        operators=['admin','reviewer'],valid_from='2026-01-01',review_due_on='2027-01-01',
        renderer_version=service.rules.VERSION,catalog_sha256=service.rules.renderer('kg-notification-renderer/1').CATALOG_SHA256,
        templates=[f'KG.TPL.A{i:02}' for i in range(1,14)])|changes)


def parameters(template='KG.TPL.A06',values=None):
    return dict(template_id=template,values=values if values is not None else {'p01':'2026-10-01','p02':'SYN-12','p03':'5','p04':'2026-10-08'})


def subject(env):return apps.application(env,apps.person(env))


def preview(env,app,**changes):
    return asyncio.run(service.preview_draft(env['engine'],**(dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],parameters=parameters(),policy=policy())|changes)))


def args(env,app,*,previewed=None,**changes):
    value=(previewed or preview(env,app))['preview']
    return dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],parameters=value['parameters'],
        expected_revision=value['expected_revision'],request_key='DRAFT-'+str(value['expected_revision']),
        expected_policy_hash=value['policy_hash'],expected_preview_hash=_hash(value),renderer_version=value['renderer_version'],policy=policy())|changes


def save(env,app,**changes):return asyncio.run(service.save_draft(env['engine'],**args(env,app,**changes)))


def read(env,app,**changes):
    return asyncio.run(service.read_drafts(env['engine'],**(dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],policy=policy())|changes)))


def counts(env):
    async def run():
        async with env['sm']() as session:return {t.name:await session.scalar(select(func.count()).select_from(t)) for t in DomainBase.metadata.sorted_tables}
    return asyncio.run(run())


def test_readonly_preview_one_saved_row_and_no_outgoing_side_effects(env):
    app=subject(env);before=counts(env);shown=preview(env,app);assert counts(env)==before
    saved=save(env,app,previewed=shown);after=counts(env)
    assert {k:after[k]-before[k] for k in before if before[k]!=after[k]}=={'entry_notification_drafts':1}
    assert saved['receipt']['applicant_id']==app['applicant_id']
    result=saved['receipt']['result'];assert not result['send_allowed'] and not result['publication_approved']
    assert result['unresolved']==[] and result['input_provenance']=='manual_unverified'
    assert read(env,app)['history'][0]==saved


@pytest.mark.parametrize('template',[f'KG.TPL.A{i:02}' for i in range(1,14)])
def test_all_source_templates_preserve_placeholders_marks_and_never_allow_send(env,template):
    app=subject(env);shown=preview(env,app,parameters=parameters(template,{}));saved=save(env,app,previewed=shown)
    legacy=__import__('app.knowledge.template_preview',fromlist=['preview'])
    expected=legacy.preview(legacy.load_catalog(),template_id=template,values={})
    result=saved['receipt']['result']
    assert result['text']==expected['text'] and result['unresolved']==expected['unresolved']
    assert result['confirmation_status']==expected['confirmation_status']
    assert not result['send_allowed'] and not result['publication_approved']
    if template in ('KG.TPL.A08','KG.TPL.A11'):assert result['confirmation_status']=='blocked'


@pytest.mark.parametrize('status,template',[('approved','KG.TPL.A07'),('refused','KG.TPL.A09')])
def test_terminal_outcome_allows_internal_draft_without_changing_outcome(env,status,template):
    app=subject(env);apps.record(env,app);apps.record(env,app,'decision',status=status,occurred_on='2026-09-02')
    before=apps.read(env,app)
    shown=preview(env,app,parameters=parameters(template,{}));save(env,app,previewed=shown)
    assert apps.read(env,app)==before


def test_old_retry_survives_policy_removal_and_new_different_template_is_not_supersession(env):
    app=subject(env);a=args(env,app);first=asyncio.run(service.save_draft(env['engine'],**a))
    shown=preview(env,app,parameters=parameters('KG.TPL.A01',{}));save(env,app,previewed=shown)
    retry=asyncio.run(service.save_draft(env['engine'],**(a|{'policy':None})))
    assert retry['receipt']==first['receipt'] and not retry['current']['context_current']
    assert read(env,app)['history'][-1]['current']['context_current']
    with pytest.raises(EntryStorageConflict):asyncio.run(service.save_draft(env['engine'],**(a|{'parameters':parameters('KG.TPL.A01',{})})))


def test_application_growth_preserves_old_receipt_but_rejects_stale_preview(env):
    app=subject(env);first=save(env,app);a=args(env,app);apps.record(env,app)
    with pytest.raises(EntryStorageConflict,match='preview_changed'):asyncio.run(service.save_draft(env['engine'],**a))
    current=read(env,app);assert current['history'][0]['receipt']==first['receipt']
    assert current['history'][0]['current']['reasons']==['notification_application_changed']
    assert save(env,app)['receipt']['revision']==2


@pytest.mark.parametrize('change',[{'policy':None},{'policy':'invalid'},
    {'policy':policy_from_document(dict(format='kg-notification-storage-policy/1',reference='SYN',proof='a'*64,privacy_reference='SYN',privacy_proof='a'*64,source_reference='SYN',source_proof='a'*64,operators=['admin'],valid_from='2025-01-01',review_due_on='2025-12-31',renderer_version='kg-notification-renderer/1',catalog_sha256='a'*64,templates=['KG.TPL.A01']))}])
def test_missing_invalid_expired_authority_denies_preview(env,change):
    app=subject(env)
    with pytest.raises(PermissionDenied):preview(env,app,**change)
    assert read(env,app)['revision']==0


def test_policy_catalog_template_and_current_identity_gates(env,monkeypatch):
    app=subject(env)
    for p in (policy(catalog_sha256='e'*64),policy(templates=['KG.TPL.A01']),policy(renderer_version='kg-notification-renderer/99')):
        with pytest.raises(EntryStorageInvalid):preview(env,app,policy=p)
    a=args(env,app)
    monkeypatch.setattr(settings,'admin_user','other')
    monkeypatch.setattr(settings,'managers',[m for m in settings.managers if m.login!='admin'])
    with pytest.raises(PermissionDenied):asyncio.run(service.save_draft(None,**a))
    with pytest.raises(PermissionDenied):asyncio.run(service.read_drafts(None,actor=ADMIN,case_id=1,application_id=1))


@pytest.mark.parametrize('value',[{'p01':True},{'p01':1.5},{'p01':None},{'p01':{'amount':{},'currency':'USD'}},
    {'p01':'x'*501},{'p01':'\ud800'},{'p01':{'unexpected':'x'}},{'unknown':'x'}])
def test_invalid_unbounded_or_untyped_input_is_rejected_before_storage(env,value):
    app=subject(env)
    with pytest.raises(EntryStorageInvalid):preview(env,app,parameters=parameters(values=value))
    assert read(env,app)['revision']==0


def test_scope_and_person_substitution_cannot_reuse_confirmation(env):
    app=subject(env);a=args(env,app)
    with pytest.raises(EntryStorageInvalid):asyncio.run(service.save_draft(env['engine'],**(a|{'case_id':env['cases']['other']})))
    other=apps.application(env,apps.person(env,key='second'),key='second')
    with pytest.raises(EntryStorageConflict):asyncio.run(service.save_draft(env['engine'],**(a|{'application_id':other['id']})))
    assert read(env,app)['revision']==read(env,other)['revision']==0


def test_concurrent_identical_and_competing_confirmations(env):
    app=subject(env);a=args(env,app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saved=list(pool.map(lambda _:asyncio.run(service.save_draft(env['engine'],**a)),range(2)))
    assert saved[0]['receipt']==saved[1]['receipt'] and read(env,app)['revision']==1
    a=args(env,app)
    def write(key):
        try:return asyncio.run(service.save_draft(env['engine'],**(a|{'request_key':key})))
        except EntryStorageConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(write,['LEFT','RIGHT']))
    assert sum(v=='conflict' for v in out)==1 and read(env,app)['revision']==2


@pytest.mark.parametrize('at',['before_commit','after_commit'])
def test_commit_ambiguity_preserves_exact_retry(env,at):
    app=subject(env);a=args(env,app)
    def fault(session):raise RuntimeError('synthetic uncertain commit')
    event.listen(Session,at,fault)
    try:
        with pytest.raises(EntryStorageUnavailable):asyncio.run(service.save_draft(env['engine'],**a))
    finally:event.remove(Session,at,fault)
    saved=asyncio.run(service.save_draft(env['engine'],**a))
    assert saved['receipt']['revision']==1
    assert asyncio.run(service.save_draft(env['engine'],**(a|{'policy':None})))['receipt']==saved['receipt']


def test_insert_failure_rolls_back_all_draft_data(env):
    app=subject(env);a=args(env,app);before=counts(env)
    def fault(session,context):
        if any(isinstance(v,EntryNotificationDraft) for v in session.new):raise RuntimeError('synthetic insert failure')
    event.listen(Session,'after_flush',fault)
    try:
        with pytest.raises(EntryStorageUnavailable):asyncio.run(service.save_draft(env['engine'],**a))
    finally:event.remove(Session,'after_flush',fault)
    assert counts(env)==before and save(env,app)['receipt']['revision']==1


@pytest.mark.parametrize('kind',['text','send','source','unresolved','bool_pin','bool_revision','renderer'])
def test_fully_rehashed_corruption_is_rejected_by_semantic_replay(env,kind):
    app=subject(env);save(env,app)
    async def corrupt():
        async with env['sm']() as session:
            row=await session.scalar(select(EntryNotificationDraft));payload=service._payload(row)
            if kind=='text':payload['result']['text']='forged'
            if kind=='send':payload['result']['send_allowed']=True
            if kind=='source':payload['result']['source_sha256']='a'*64
            if kind=='unresolved':payload['result']['unresolved']=['p01']
            if kind=='bool_pin':payload['source_pin']['event_revision']=True
            if kind=='bool_revision':payload['command']['expected_revision']=False
            if kind=='renderer':payload['command']['renderer_version']='kg-notification-renderer/99'
            payload['request_hash']=_hash(payload['command'])
            async with env['engine'].begin() as conn:
                await conn.execute(text('UPDATE entry_notification_drafts SET command=:command,result=:result,source_pin=:pin,request_hash=:request,snapshot_hash=:snapshot WHERE id=:id'),
                    dict(command=json.dumps(payload['command']),result=json.dumps(payload['result']),pin=json.dumps(payload['source_pin']),request=payload['request_hash'],snapshot=_hash(payload),id=row.id))
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):read(env,app)
    with pytest.raises(EntryStorageInvalid):save(env,app)


def test_old_renderer_replays_after_current_source_unavailable(env,monkeypatch):
    app=subject(env);a=args(env,app);first=asyncio.run(service.save_draft(env['engine'],**a))
    monkeypatch.setattr(service.rules,'VERSION','kg-notification-renderer/99')
    current=read(env,app,policy=None)
    assert current['history'][0]['receipt']==first['receipt'] and not current['can_save']
    assert asyncio.run(service.save_draft(env['engine'],**(a|{'policy':None})))['receipt']==first['receipt']
    with pytest.raises(EntryStorageInvalid):preview(env,app,policy=policy())


def test_capacity_preserves_read_and_exact_retry_but_refuses_new_save(env,monkeypatch):
    app=subject(env);a=args(env,app);first=asyncio.run(service.save_draft(env['engine'],**a))
    monkeypatch.setattr(service,'MAX_REVISIONS',1)
    assert read(env,app)['history'][0]['receipt']==first['receipt']
    assert asyncio.run(service.save_draft(env['engine'],**(a|{'policy':None})))['receipt']==first['receipt']
    with pytest.raises(EntryStorageInvalid,match='history_limit'):save(env,app)


def test_unicode_json_expansion_never_makes_a_successful_append_unreadable(env,monkeypatch):
    app=subject(env)
    values={key:'\U0001f642'*500 for key in ('p01','p02','p10','p11','p12','p20')}
    parameters_full=parameters('KG.TPL.A07',values)
    shown=preview(env,app,parameters=parameters_full);first_args=args(env,app,previewed=shown)
    first=asyncio.run(service.save_draft(env['engine'],**first_args))
    async def size():
        async with env['sm']() as session:
            row=await session.scalar(select(EntryNotificationDraft))
            semantic=len(service.canonical(service._payload(row)).encode())
            encoded=await session.scalar(select(sum(func.length(cast(getattr(EntryNotificationDraft,k),Text)) for k in service.JSON_FIELDS)))
            return semantic,encoded
    semantic,encoded=asyncio.run(size());assert encoded>2*semantic
    monkeypatch.setattr(service,'MAX_HISTORY_BYTES',2*semantic+4096)
    second=save(env,app,previewed=preview(env,app,parameters=parameters_full))
    assert read(env,app)['revision']==2
    assert asyncio.run(service.save_draft(env['engine'],**(first_args|{'policy':None})))['receipt']==first['receipt']
    with pytest.raises(EntryStorageInvalid,match='history_limit'):
        save(env,app,previewed=preview(env,app,parameters=parameters_full))
    assert read(env,app)['history'][0]['receipt']==second['receipt']


@pytest.mark.parametrize('limit',['MAX_EVENT_BYTES','MAX_HISTORY_BYTES'])
def test_size_limit_rolls_back_and_refuses_oversize_stored_read(env,monkeypatch,limit):
    app=subject(env);a=args(env,app);before=counts(env);old=getattr(service,limit)
    monkeypatch.setattr(service,limit,10)
    with pytest.raises(EntryStorageInvalid,match='history_limit'):asyncio.run(service.save_draft(env['engine'],**a))
    assert counts(env)==before
    monkeypatch.setattr(service,limit,old);save(env,app);monkeypatch.setattr(service,limit,10)
    with pytest.raises(EntryStorageInvalid,match='history_limit'):read(env,app)


@pytest.mark.parametrize('lock',['service_cases','entry_applications'])
@pytest.mark.parametrize('expiry',[True,False])
def test_policy_day_is_checked_after_row_lock(env,monkeypatch,lock,expiry):
    app=subject(env);initial=datetime(2026,10,11,17,59,59,tzinfo=timezone.utc)
    current=[initial];monkeypatch.setattr(service,'_now',lambda:current[0])
    allowed=policy(review_due_on='2026-10-11' if expiry else '2027-01-01')
    shown=preview(env,app,policy=allowed);a=args(env,app,previewed=shown,policy=allowed)
    original=AsyncSession.scalar
    async def waited(self,statement,*pos,**kw):
        result=await original(self,statement,*pos,**kw)
        if getattr(statement,'_for_update_arg',None) is not None and lock in str(statement):current[0]=initial+timedelta(seconds=2)
        return result
    monkeypatch.setattr(AsyncSession,'scalar',waited)
    with pytest.raises((PermissionDenied,EntryStorageConflict)):asyncio.run(service.save_draft(env['engine'],**a))
    assert read(env,app)['revision']==0


def test_immutable_orm_and_bulk_writes(env):
    app=subject(env);save(env,app)
    async def run():
        async with env['sm']() as session:
            row=await session.scalar(select(EntryNotificationDraft));row.created_by='forged'
            with pytest.raises(DomainError):await session.flush()
        async with env['sm']() as session:
            with pytest.raises(DomainError):await session.execute(update(EntryNotificationDraft).values(created_by='forged'))
    asyncio.run(run())


def test_template_assets_are_in_runtime_package():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    docker=(root/'Dockerfile').read_text()
    for directory in ('templates_v1_1','template_renderers'):
        assert f'COPY knowledge/kg_entry/{directory}/ ./knowledge/kg_entry/{directory}/' in docker
    assert service.rules.render(parameters(),version='kg-notification-renderer/1')['catalog_sha256']==policy().document()['catalog_sha256']
