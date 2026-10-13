"""Current real ledger/package/portal heads versus unchanged source stage."""
import asyncio

from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys, record
from tests import test_operator_sop_reviews as core, test_entry_document_packages as packages


def test_completed_payment_documents_and_approved_attempt_are_stale_waits(env,tmp_path):
    prepared=core.setup(env,tmp_path);person,app,profile,_=prepared
    packages.setup(env,app=app,product='TS')
    packages.write(env,app,'consent',dict(status='granted',on='2026-09-03',reference='CURRENT-OWN-CONSENT',proof='c'*64))
    core.processes.attest(env,app,'profile_review_complete',profile_id=profile['qualification_id'])
    for fact,value in [('conversation_started',True),('manager_review_required',False),
        ('eligibility','eligible'),('visa_required',True),('quote_sent',True),('offer_accepted',True),
        ('invoice_issued',True),('checklist_sent',True),('portal_draft_created',True),
        ('email_verified',True),('portal_payment_confirmed',True)]:
        core.processes.attest(env,app,fact,value,profile_id=profile['qualification_id'] if fact in ('eligibility','visa_required') else None)
    for stage in ('V02','V04','V06','V07','V08'):core.processes.transition(env,app,stage)
    def request(key,package=None):
        return core.args(env,(person,app,profile,core.authority(env,core.rules.PREFIX+key,package=package)))
    pay=request('PAYMENT_24H')
    assert core.preview(env,pay)['report']['status']=='available'
    original,command=core.write(env,pay,key='PAYMENT-WAIT')
    core.processes.money(env,amount='100000',currency='KGS',idempotency_key='REVIEWER-PAYMENT')
    assert core.processes.read(env,app)['selected']['snapshot']['stage']=='V08'
    assert core.preview(env,pay)['report']['status']=='unknown'
    assert asyncio.run(core.service.record(env['engine'],**(command|dict(authority=None))))==original
    for stage in ('V09','V10'):core.processes.transition(env,app,stage)
    docs=request('DOCUMENTS_D1')
    assert core.preview(env,docs)['report']['status']=='available'
    allowed=packages.complete(env,app);packages.approve(env,app,allowed)
    docs=request('DOCUMENTS_D1',allowed)
    assert core.processes.read(env,app)['selected']['snapshot']['stage']=='V10'
    assert core.preview(env,docs)['report']['status']=='unknown'
    for stage in ('V12','V14','V15'):core.processes.transition(env,app,stage,package_policy=allowed)
    record(env,app,'submit',reference='RV000001')
    for stage in ('V16','V17'):core.processes.transition(env,app,stage,package_policy=allowed)
    status=request('APPLICATION_STATUS',allowed)
    assert core.preview(env,status)['report']['status']=='available'
    record(env,app,'approve',status='approved',reference='RV000001',occurred_on='2026-09-02')
    assert core.processes.read(env,app)['selected']['snapshot']['stage']=='V17'
    assert core.preview(env,status)['report']['status']=='unknown'
