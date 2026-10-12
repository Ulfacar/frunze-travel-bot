"""Dated passport evidence must not refresh an older document check.

The first two inventory cases reproduce the independent E6-25 review finding.
Receipt tests deliberately emulate pre-guard admission, retaining replay/hash
semantics; independent review also checks the archived old runtime.
"""
import asyncio
from copy import deepcopy

import pytest

from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests import test_entry_documents as inventory
from tests import test_entry_document_packages as packages
from tests import test_entry_issued as issued
from tests import test_entry_processes as processes
from app.domain.entry_process_evidence import Evidence,Sources
from app.domain.models import _now


def evidence(env,app,method,fact,policy=None,observed=None):
    async def run(session):
        case=await packages.service.applications._case(session,env['cases']['visa'],lock=True)
        subject=await packages.service.applications._application(session,case.id,app['id'],lock=True)
        context=Evidence(Sources(session,case,subject),{'links':{'visa':app['id']}},[],None,policy,
            at=_now(),historical=observed is not None,observed=observed)
        packet=await getattr(context,method)(subject,fact)
        return packet,context.observed
    return asyncio.run(packages.service.applications._run(env['engine'],run))


def prepared(env, kind):
    api=inventory if kind=='inventory' else packages
    app=api.setup(env)
    api.receive(env,app)
    receipt=api.check(env,app,key='old-check',revision=2)
    return api,app,receipt


def change(env,api,app,kind,method,on='2026-09-03'):
    if method=='explicit':
        return api.write(env,app,'passport_change',dict(on=on,reason='replacement'))
    return api.write(env,app,'receive',dict(item='d02_0' if kind=='inventory' else 't08_01',
        fingerprint='c'*64,on=on,source='client_copy'))


def row(api,view):
    rows=view['selected']['summary']['items' if api is inventory else 'rows']
    return next(r for r in rows if r['id']==('d03_0' if api is inventory else 't08_02'))


@pytest.mark.parametrize('kind',['inventory','package'])
@pytest.mark.parametrize('method',['explicit','received'])
def test_backdated_check_after_passport_change_is_rejected(env,kind,method):
    api,app,old=prepared(env,kind)
    change(env,api,app,kind,method)
    assert row(api,api.read(env,app))['effective_status']=='recheck'
    with pytest.raises(EntryStorageInvalid,match='invalid_document.*date'):
        api.check(env,app,key='backdated')
    assert api.read(env,app)['current_revision']==4
    assert api.check(env,app,key='old-check',revision=2)==old
    assert row(api,api.read(env,app,revision=old['revision']))['effective_status']=='checked'


@pytest.mark.parametrize('kind',['inventory','package'])
@pytest.mark.parametrize('on',['2026-09-03','2026-09-04'])
def test_same_or_later_day_check_is_current(env,kind,on):
    api,app,old=prepared(env,kind)
    change(env,api,app,kind,'explicit')
    # A later-recorded older passport fact must not lower the date boundary.
    change(env,api,app,kind,'explicit',on='2026-09-01')
    with pytest.raises(EntryStorageInvalid,match='invalid_document.*date'):
        api.check(env,app,key='still-old')
    data={**old['operation']['data'],'on':on}
    current=api.write(env,app,'review',data,key='new-check',revision=5)
    assert row(api,api.read(env,app))['effective_status']=='checked'
    assert api.write(env,app,'review',data,key='new-check',revision=5)==current


@pytest.mark.parametrize('kind',['inventory','package'])
def test_legacy_stale_receipt_remains_exact_but_current_summary_requires_recheck(env,monkeypatch,kind):
    api,app,old=prepared(env,kind)
    change(env,api,app,kind,'explicit')
    with monkeypatch.context() as context:
        context.setattr(api.service,'_passport_date',lambda *args:None)
        stale=api.check(env,app,key='legacy-stale',revision=4)
    assert api.check(env,app,key='legacy-stale',revision=4)==stale
    view=api.read(env,app)
    assert view['selected']['snapshot']==stale['snapshot']
    assert row(api,view)['status']=='checked'
    assert row(api,view)['effective_status']=='recheck'
    assert row(api,api.read(env,app,revision=old['revision']))['effective_status']=='checked'
    api.write(env,app,'review',{**old['operation']['data'],'on':'2026-09-04'})
    assert row(api,api.read(env,app))['effective_status']=='checked'


def test_legacy_passport_date_survives_full_package_import(env):
    app=inventory.setup(env)
    inventory.receive(env,app)
    inventory.write(env,app,'passport_change',dict(on='2026-09-03',reason='replacement'))
    packages.setup(env,product='TS',app=app,legacy_revision=3)
    with pytest.raises(EntryStorageInvalid,match='invalid_document_package_date'):
        packages.check(env,app,item='matrix_d03_0')
    packages.write(env,app,'review',dict(item='matrix_d03_0',fingerprint='a'*64,version=1,
        on='2026-09-04',outcome='checked',reason=None,alternative=None))


def test_old_stale_package_approval_cannot_authorize_current_acceptance(env,monkeypatch):
    app=packages.setup(env)
    policy=packages.complete(env,app)
    packages.write(env,app,'passport_change',dict(on='2026-09-03',reason='replacement'))
    with monkeypatch.context() as context:
        context.setattr(packages.service,'_passport_date',lambda *args:None)
        rows=packages.read(env,app)['selected']['summary']['rows']
        for item in rows:
            if item['status']=='checked':
                packages.check(env,app,item=item['id'],fingerprint=item['fingerprint'],alternative=item['alternative'])
        before=packages.read(env,app)['current_revision']
        old=packages.approve(env,app,policy,key='old-approval',revision=before)
        assert packages.read(env,app,policy=policy)['current_acceptance']['accepted']
    assert packages.write(env,app,'approve',old['operation']['data'],policy=policy,
        key='old-approval',revision=before)==old
    assert not packages.read(env,app,policy=policy)['current_acceptance']['accepted']
    packet,observed=evidence(env,app,'package','documents_accepted',policy)
    assert packet['value'] is False and observed['rules_version']==2
    assert evidence(env,app,'package','documents_accepted',policy,observed)==(packet,observed)
    legacy=deepcopy(observed); legacy.pop('rules_version')
    legacy['streams'].pop(f"documents:{app['id']}")
    old_packet,old_observed=evidence(env,app,'package','documents_accepted',policy,legacy)
    assert old_packet['value'] is True and old_observed==legacy
    with pytest.raises(EntryStorageInvalid,match='document_package_incomplete'):
        packages.approve(env,app,policy,key='new-approval')


@pytest.mark.parametrize('receipt_on,current',[
    ('2026-09-05',False),('2026-09-07',True),('2026-09-09',True)])
def test_dated_issued_receipt_is_retained_without_refreshing_identity(env,receipt_on,current):
    # Independent E6-25 E07 finding: an old receipt is a real dated fact, but
    # cannot prove an identity check against a later passport revision.
    app=issued.setup(env)
    issued.file(env,app); issued.review(env,app); issued.delivery(env,app)
    issued.write(env,app,'passport_change',dict(passport_fingerprint='e'*64,on='2026-09-06'))
    issued.write(env,app,'passport_change',dict(passport_fingerprint='b'*64,on='2026-09-07'))
    issued.review(env,app,on='2026-09-08')
    data=dict(version=1,fingerprint='a'*64,on=receipt_on,proof='f'*64,identity_checked=True)
    old=issued.write(env,app,'receipt',data,key='dated-receipt',revision=6)
    assert old['summary']['receipt_recorded']
    assert old['summary']['receipt_current_and_checked'] is current
    assert issued.write(env,app,'receipt',data,key='dated-receipt',revision=6)==old
    assert issued.read(env,app)['selected']['snapshot']==old['snapshot']
    packet,observed=evidence(env,app,'issued_fact','receipt_confirmed')
    assert packet['value'] is current and observed['rules_version']==2
    assert evidence(env,app,'issued_fact','receipt_confirmed',observed=observed)==(packet,observed)
    legacy=deepcopy(observed); legacy.pop('rules_version')
    assert evidence(env,app,'issued_fact','receipt_confirmed',observed=legacy)[0]['value'] is True
    if not current:
        updated=issued.write(env,app,'receipt',{**data,'on':'2026-09-09','proof':'1'*64})
        assert updated['summary']['receipt_current_and_checked']
        assert issued.read(env,app,revision=old['revision'])['selected']['snapshot']==old['snapshot']
        assert issued.write(env,app,'receipt',data,key='dated-receipt',revision=6)==old


def test_old_process_journal_replays_and_new_events_pin_date_semantics(env,monkeypatch):
    class LegacyEvidence(Evidence):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if not self.historical:
                self.rules_version=1
                self.observed.pop('rules_version',None)
    with monkeypatch.context() as context:
        context.setattr(processes.service,'Evidence',LegacyEvidence)
        app=processes.setup(env)
        processes.attest(env,app,'conversation_started')
        old=processes.transition(env,app,'V02')
        assert 'rules_version' not in old['evidence']['observed']
    assert processes.read(env,app)['selected']['snapshot']==old['snapshot']
    new=processes.attest(env,app,'conversation_started',value=False)
    assert new['evidence']['observed']['rules_version']==2
    assert processes.read(env,app)['selected']['snapshot']==new['snapshot']
    assert processes.read(env,app,revision=old['revision'])['selected']['snapshot']==old['snapshot']
