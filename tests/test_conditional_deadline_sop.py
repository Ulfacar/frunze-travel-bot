"""Original-source REG SOP continues into own actual certificate and CRM task."""
import asyncio

from app.config import settings
from app.domain import entry_deadline_tasks
from tests import test_conditional_deadlines as core
from tests import test_source_sop_aftercare as sop
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_interviews import admins
from tests.test_entry_channel_stops import activation


def test_original_eaeu_registration_sop_actual_certificate_review_task_and_withdrawal(env,tmp_path,monkeypatch):
    core.connected.source(env,tmp_path,source_file=core.ROOT/'runs/specialist-source.pdf')
    subject=sop.person(env,'CONNECTED-EAEU-WORKER',role='employee')
    document=sop.profiles.request();document['as_of']=sop.process.today()
    document['profile'].update(citizenship=['RUS'],entry_passport_country='RUS',purpose='work_hire',
        current_location='in_kg',in_kg_since='2026-09-03',current_basis_in_kg='visa_free')
    profile=sop.profiles.save(env,subject,doc=document)
    interview,_=sop.handoff(env,subject,purpose='work_hire')
    app=sop.application(env,subject,'CONNECTED-TAX-PENDING',procedure='registration')
    package_policy,_=sop.explicit_package(env,app,'REG',facts={'in_kg':True,'visa_free':True,
        'registration_worker':True,'eaeu_worker':True,'tax_in_esuvm':False,'host_is_owner':False,
        'matrix_d02_0_applies':True,'matrix_d15_0_applies':True,'matrix_d16_0_applies':True},critical='t32_02')
    end=sop.finish_registration(env,app,profile,package_policy,key='CONNECTED-EAEU')
    assert end['snapshot']['stage']=='R08'
    prepared=(subject,app,profile)
    rule='KG.DL.INTERNAL_EAEU_REG_REVIEW';authority=core.authority(env,rule)
    arguments=core.arguments(env,prepared,rule,authority)
    assert core.preview(env,arguments)['report']['reason']=='conditional_deadline_actual_anchor_required'
    # The process's certificate boolean is insufficient: record its actual own
    # period, independently of approval timestamp, with explicit document proof.
    fact=core.actual.args(env,prepared)
    fact['operation']['data']['on']=sop.process.today()
    anchor=core.actual.write(env,fact)
    receipt,request=core.write(env,arguments,key='CONNECTED-REG-REVIEW')
    assert receipt['summary']['review_due_on']=='2026-10-19'
    assert receipt['summary']['operational_due_on'] is None
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[authority.document])
    task_args={k:v for k,v in arguments.items() if k not in ('applicant_id','authority')}
    task=asyncio.run(entry_deadline_tasks.reconcile_deadline_task(env['engine'],**task_args,enable=True))
    assert task['task']['date']=='2026-10-19' and task['task']['status']=='planned'
    assert task['task']['owner']=='medina'
    removal=core.actual.args(env,prepared,policy=None)
    removal['operation']=dict(action='withdraw',confirmed=True,
        data=dict(on=sop.process.today(),reason='wrong_document',proof='d'*64))
    core.actual.write(env,removal)
    cancelled=asyncio.run(entry_deadline_tasks.reconcile_deadline_task(env['engine'],**task_args))
    assert cancelled['task']['id']==task['task']['id'] and cancelled['task']['status']=='cancelled'
    assert asyncio.run(core.service.record(env['engine'],**(request|{'authority':None})))==receipt
    sop.evidence('connected-eaeu-actual-period',section='19.10',case_id=app['case_id'],applicant_id=subject['id'],
        application_id=app['id'],interview_id=interview['interview_id'],registration_stage=end['snapshot']['stage'],
        actual_anchor_id=anchor['id'],conditional_receipt_id=receipt['id'],task_id=task['task']['id'],
        source_pending_term_days=60,actual_period='2026-09-03/2026-11-01',review_due_on='2026-10-19',
        task_after_withdrawal='cancelled',delegation='synthetic_only',external_delivery='not_sent')
