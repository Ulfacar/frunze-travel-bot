import asyncio

import pytest
from sqlalchemy import text, update

from app.domain import knowledge_decisions as decisions
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.models import KnowledgeDecision, DomainError
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import enforce_sqlite_foreign_keys


def data():
    return dict(verdict='confirmed',reason='source_matches',evidence_kind='official_source',evidence_ref='SYNTHETIC-REVIEW-01',
                proof='a'*64,verified_on='2026-09-01',review_due_on='2026-12-01',confirmed=True)


def read(env,unit='KG.DL.TEST',version=None,**kwargs):
    return asyncio.run(decisions.read_knowledge_decisions(env['engine'],actor=ADMIN,version_id=version or env['version'],unit_id=unit,**kwargs))


def write(env,decision=None,unit='KG.DL.TEST',version=None,revision=None,key=None):
    if revision is None:revision=read(env,unit,version)['current_revision']
    return asyncio.run(decisions.record_knowledge_decision(env['engine'],actor=ADMIN,version_id=version or env['version'],unit_id=unit,
        expected_revision=revision,request_key=key or f'review-{revision}',decision=decision or data()))


def sql(env,statement,**params):
    async def run():
        async with env['engine'].begin() as conn:
            r=await conn.execute(text(statement),params)
            return r.fetchall() if r.returns_rows else None
    return asyncio.run(run())


def test_review_confirm_reject_correction_keeps_sources_and_history(env):
    before=read(env)
    first=write(env)
    rejected=write(env,{**data(),'verdict':'rejected','reason':'source_conflict','review_due_on':None,'proof':'b'*64})
    third=write(env,{**data(),'evidence_kind':'owner_decision','evidence_ref':'DEC-07-SYNTHETIC','proof':'c'*64})
    current=read(env)
    assert current['selected']==third and len(current['history'])==3
    assert read(env,revision=1)['selected']==first and read(env,revision=2)['selected']==rejected
    assert current['unit']==before['unit'] and current['version']==before['version']
    assert all(not r['may_quote'] and not r['publication_approved'] for r in current['history'])
    assert sql(env,'SELECT active_version_id FROM knowledge_sets')[0][0] is None
    assert sql(env,'SELECT status FROM knowledge_versions')[0][0]=='draft'


def test_retry_cas_and_actor_identity(env):
    first=write(env,key='same');write(env,{**data(),'proof':'b'*64})
    assert write(env,revision=0,key='same')==first
    with pytest.raises(EntryStorageConflict):write(env,{**data(),'proof':'c'*64},revision=0,key='same')
    with pytest.raises(EntryStorageConflict):write(env,revision=0,key='stale')
    with pytest.raises(EntryStorageConflict):
        asyncio.run(decisions.record_knowledge_decision(env['engine'],actor=Actor('other-admin',True),version_id=env['version'],
            unit_id='KG.DL.TEST',expected_revision=0,request_key='same',decision=data()))
    with pytest.raises(EntryStorageInvalid):write(env,unit='KG.DL.MISSING',revision=0)


@pytest.mark.parametrize('changes',[
    {'confirmed':False},{'proof':'not-a-hash'},{'evidence_ref':'<script>'},{'verified_on':'2099-01-01'},
    {'review_due_on':None},{'review_due_on':'2026-08-01'},{'reason':'source_conflict'},
    {'verdict':'rejected','reason':'source_conflict'},{'extra':'arbitrary payload'}])
def test_invalid_dates_evidence_and_unknown_fields_leave_no_history(env,changes):
    with pytest.raises(EntryStorageInvalid):write(env,{**data(),**changes},revision=0)
    assert read(env)['current_revision']==0


def test_expired_review_record_is_preserved_and_explicitly_expired(env):
    row=write(env,{**data(),'review_due_on':'2026-09-05'})
    assert row['expired'] and not row['may_quote']
    assert read(env)['selected']==row


def test_corrupt_history_and_bounded_chain_fail_closed(env,monkeypatch):
    row=write(env)
    monkeypatch.setattr(decisions,'MAX_BYTES',1)
    with pytest.raises(EntryStorageInvalid,match='history_limit'):read(env)
    monkeypatch.setattr(decisions,'MAX_BYTES',2*1024*1024)
    sql(env,'UPDATE knowledge_decisions SET unit_hash=:hash WHERE id=:id',hash='0'*64,id=row['id'])
    with pytest.raises(EntryStorageInvalid,match='integrity_failed'):read(env)
    with pytest.raises(EntryStorageInvalid):write(env,revision=0,key='review-0')


def test_orm_and_bulk_cannot_rewrite_a_decision(env):
    row=write(env)
    async def change():
        async with env['sm']() as session:
            stored=await session.get(KnowledgeDecision,row['id']);stored.unit_hash='0'*64
            with pytest.raises(DomainError):await session.flush()
            await session.rollback()
            with pytest.raises(DomainError):await session.execute(update(KnowledgeDecision).values(unit_hash='0'*64))
    asyncio.run(change());assert read(env)['selected']==row


@pytest.mark.parametrize('actor',[None,{},Actor('manager'),Actor('system',True)])
def test_authorization_before_engine_or_payload(actor):
    with pytest.raises(PermissionDenied):asyncio.run(decisions.review_catalog(None,actor=actor))
    with pytest.raises(PermissionDenied):asyncio.run(decisions.read_knowledge_decisions(None,actor=actor,version_id=1,unit_id='bad'))
    with pytest.raises(PermissionDenied):asyncio.run(decisions.record_knowledge_decision(None,actor=actor,version_id=1,unit_id='bad',expected_revision=0,request_key='bad',decision={}))


def test_new_bundle_never_inherits_previous_decision_and_blocked_values_stay_blocked(env,tmp_path):
    import shutil,yaml
    from app.domain.knowledge_import import create_kg_entry_set,import_bundle
    from tests.test_admin_kg_entry import FIX
    first=write(env)
    folder=tmp_path/'new-source';shutil.copytree(FIX/'synthetic_bundle',folder)
    units=yaml.safe_load((folder/'units.yaml').read_text('utf-8'));unit=next(r for r in units if r['unit_id']=='KG.DL.TEST')
    unit.update(blocked_value={'source':unit['value'],'reason':'Synthetic conflict'},value=None,confirmation_status='blocked',conflict_ref='SRC-TEST',label='verify')
    (folder/'units.yaml').write_text(yaml.safe_dump(units,allow_unicode=True),'utf-8')
    async def load():
        set_id=await create_kg_entry_set(env['engine'],actor=ADMIN)
        return await import_bundle(env['engine'],actor=ADMIN,set_id=set_id,directory=folder,source=FIX/'synthetic_source.txt')
    imported=asyncio.run(load());assert imported.accepted,imported.report
    assert read(env,version=imported.version_id)['selected'] is None
    second=write(env,version=imported.version_id)
    assert second['unit_hash']!=first['unit_hash']
    current=read(env,version=imported.version_id)
    assert current['unit']['value'] is None and current['unit']['confirmation_status']=='blocked' and not current['may_quote']
    assert read(env)['selected']==first


def test_concurrent_reviews_and_lost_acknowledgement(env,monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSessionTransaction
    async def race():
        args=dict(actor=ADMIN,version_id=env['version'],unit_id='KG.DL.TEST',expected_revision=0,request_key='raced',decision=data())
        return await asyncio.gather(*(decisions.record_knowledge_decision(env['engine'],**args) for _ in range(2)),return_exceptions=True)
    results=asyncio.run(race());assert any(isinstance(r,dict) for r in results)
    assert all(isinstance(r,(dict,EntryStorageConflict)) for r in results),results
    assert read(env)['current_revision']==1
    original=AsyncSessionTransaction.__aexit__;once=True
    async def lost(self,*args):
        nonlocal once
        result=await original(self,*args)
        if once:once=False;raise RuntimeError('synthetic lost acknowledgement')
        return result
    monkeypatch.setattr(AsyncSessionTransaction,'__aexit__',lost)
    with pytest.raises(EntryStorageUnavailable):write(env,revision=1,key='lost')
    assert write(env,revision=1,key='lost')['revision']==2 and read(env)['current_revision']==2


def test_catalog_read_only_version_selection_and_search(env):
    result=asyncio.run(decisions.review_catalog(env['engine'],actor=ADMIN,query='KG.DL.'))
    assert result['version_id']==env['version'] and result['total']==1 and result['units'][0]['unit_id']=='KG.DL.TEST'
    assert not result['has_next'] and read(env)['current_revision']==0
