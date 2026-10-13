import asyncio
import json

import pytest
from sqlalchemy import select, text

from app.domain import precontract_cases as service, service_cases as cases
from app.domain.entry_storage import _hash, _plain
from app.domain.models import Contact, DomainError, ServiceCase, ServiceEvent, ServiceCaseOpening
from tests.test_precontract_cases import prepare, signing, counts, managers
from tests.test_service_cases import run_with_db
from app.domain.permissions import Actor


@pytest.mark.parametrize('damage', ['revision', 'owner_shape'])
def test_rehashed_impossible_signature_receipt_is_refused(damage):
    async def run(sm):
        async with sm() as s:
            values = await prepare(s)
            opened = await service.open_preliminary(s, **values)
            signed = await service.record_signed_contract(s, **signing(opened))
            await s.commit()
            assert await service.record_signed_contract(s, **signing(opened)) == signed | {'duplicate': True}
            event = await s.scalar(select(ServiceEvent).where(ServiceEvent.event_type == 'contract_signed'))
            payload = _plain(event.payload)
            if damage == 'revision':
                payload['revision'] = payload['operation']['result']['revision'] = 999
            else:
                payload['operation']['result']['owner_login'] = {'not': 'a manager identity'}
            core = {k: payload['operation'][k] for k in ('command', 'result')}
            payload['operation']['snapshot_hash'] = _hash(core)
            await s.execute(text('UPDATE service_events SET payload=:payload WHERE id=:id'),
                            {'id': event.id, 'payload': json.dumps(payload)})
            await s.commit()
            s.expire_all()
            with pytest.raises(DomainError, match='evidence'):
                await service.record_signed_contract(s, **signing(opened))
    run_with_db(run)


def test_cancelled_signature_rolls_back_own_changes_and_preserves_caller(monkeypatch):
    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError('synthetic controlled cancellation')
    async def run(sm):
        async with sm() as s:
            values = await prepare(s)
            opened = await service.open_preliminary(s, **values)
            await s.commit()
            extra = Contact(); s.add(extra); await s.flush(); extra_id = extra.id
            with monkeypatch.context() as patch:
                patch.setattr(cases, '_create_initial_tasks', cancelled)
                with pytest.raises(asyncio.CancelledError):
                    await service.record_signed_contract(s, **signing(opened))
            await s.commit()
            assert await s.get(Contact, extra_id) is not None
            assert (await s.get(ServiceCase, opened['case_id'])).signed_at is None
            assert (await counts(s))['calendar_tasks'] == 0
            assert (await counts(s))['service_events'] == 1
            saved = await service.record_signed_contract(s, **signing(opened))
            await s.commit()
            assert await service.record_signed_contract(s, **signing(opened)) == saved | {'duplicate': True}
    run_with_db(run)


@pytest.mark.parametrize('damage',['revision','stage'])
def test_opening_must_describe_actual_first_workflow_stage_and_initial_revision(damage):
    async def run(sm):
        async with sm() as s:
            values=await prepare(s);opened=await service.open_preliminary(s,**values);await s.commit()
            assert await service.open_preliminary(s,**values)==opened|{'duplicate':True}
            row=await s.get(ServiceCaseOpening,opened['opening_id'])
            document=_plain(row.document)
            document['result'][damage]=999 if damage=='revision' else 'IN-02'
            payload=service.opening_payload(row);payload['document']=document
            await s.execute(text('UPDATE service_case_openings SET document=:doc,snapshot_hash=:hash WHERE id=:id'),
                {'doc':json.dumps(document),'hash':_hash(payload),'id':row.id})
            if damage=='revision':
                await s.execute(text('UPDATE service_events SET payload=:payload WHERE id=:id'),
                    {'payload':json.dumps({'revision':999,'workflow_version_id':values['workflow_version_id']}),'id':opened['event_id']})
            else:
                await s.execute(text('UPDATE service_events SET to_stage=:stage WHERE id=:id'),{'stage':'IN-02','id':opened['event_id']})
            await s.commit();s.expire_all()
            with pytest.raises(DomainError):await service.open_preliminary(s,**values)
            with pytest.raises(DomainError):await service.record_signed_contract(s,**signing(opened))
    run_with_db(run)


@pytest.mark.parametrize('login',['ADMIN',' admin ','Admin'])
def test_noncanonical_actor_refuses_before_committing_unusable_operation(login):
    async def run(sm):
        async with sm() as s:
            values=await prepare(s);before=await counts(s)
            with pytest.raises(DomainError,match='canonical'):
                await service.open_preliminary(s,**(values|{'by':Actor(login,True)}))
            await s.commit();assert await counts(s)==before
            opened=await service.open_preliminary(s,**values);await s.commit();before=await counts(s)
            with pytest.raises(DomainError,match='canonical'):
                await service.record_signed_contract(s,**signing(opened,by=Actor(login,True)))
            await s.commit();assert await counts(s)==before
            assert await service.open_preliminary(s,**values)==opened|{'duplicate':True}
    run_with_db(run)
