"""Original PDF §19.9 page81 combined reminders use actual distinct money facts."""
import asyncio
from datetime import datetime,timezone
from app.config import settings
from app.domain import precontract_cases
from app.domain.models import ServiceCase
from tests.test_admin_kg_entry import env,ADMIN
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests import test_operator_sop_reviews as core, test_work_process_v2 as work
from tests.test_source_sop_products import open_case


def test_work_quote_contract_payment_is_combined_and_old_receipts_survive_signing(env,tmp_path,monkeypatch):
    core.connected.source(env,tmp_path,source_file=core.ROOT/'runs/specialist-source.pdf')
    opening=open_case(env,'REVIEW-WORK-COMMERCIAL')
    person,root,profile=work.setup(env)
    arguments=[]
    for suffix in ('24H','48H'):
        key='WORK_COMMERCIAL_'+suffix
        authority=core.authority(env,core.rules.PREFIX+key,process=work.policy())
        definition=core.rules.definition(authority.policy.document['rule_id'])
        assert definition['stages']==['W03','W04']
        assert all(r['section']=='19.9' and r['printed_page']=='81' for r in definition['source_refs'])
        args=core.args(env,(person,root,profile,authority));arguments.append(args)
        assert core.preview(env,args)['report']['status']=='unknown'
    for fact in ('employer_qualified','quote_sent','offer_accepted'):work.attest(env,root,fact)
    for stage in ('W02','W03'):work.transition(env,root,stage)
    for args in arguments:assert core.preview(env,args)['report']['status']=='available'
    # A real deposit before signature does not create a contract or prove full balance.
    core.processes.money(env,amount='100000',currency='KGS',idempotency_key='WORK-DEPOSIT')
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[a['authority'].document for a in arguments])
    retained=[]
    for args in arguments:
        observed=core.preview(env,args)['report']
        assert observed['status']=='available',observed
        assert observed['evidence']['facts']['permit.signed_contract_recorded'] is False
        assert observed['evidence']['facts']['permit.service_payment_confirmed']['value'] is None
        saved,request=core.write(env,args,key='WORK-'+args['rule_unit_id'][-3:],time=None)
        task=asyncio.run(core.tasks.reconcile_deadline_task(env['engine'],**core.task_args(args),enable=True))
        retained.append((args,saved,request,task))
    async def sign():
        async with env['sm']() as session:
            case=await session.get(ServiceCase,opening['case_id'])
            signed=await precontract_cases.record_signed_contract(session,by=ADMIN,case_id=case.id,
                expected_revision=case.revision,request_key='REVIEW-WORK-SIGN',reference='WORK-CONTRACT',
                signed_at=datetime.now(timezone.utc),amount='100000',currency='KGS')
            await session.commit();return signed
    assert asyncio.run(sign())['case_id']==root['case_id']
    assert work.read(env,root)['selected']['snapshot']['stage']=='W03'
    for args,saved,request,task in retained:
        assert core.preview(env,args)['report']['status']=='unknown'
        assert asyncio.run(core.service.record(env['engine'],**(request|dict(authority=None))))==saved
        current=asyncio.run(core.tasks.reconcile_deadline_task(env['engine'],**core.task_args(args)))
        assert current['task']['id']==task['task']['id'] and current['task']['status']=='cancelled'
