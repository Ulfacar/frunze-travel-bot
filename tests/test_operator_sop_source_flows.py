"""Real source SOP stages feed manual review receipts and actual owned tasks."""
import asyncio
from pathlib import Path

from app.domain import entry_deadline_tasks as tasks, entry_deadlines
from tests.test_admin_kg_entry import env,ADMIN
from tests.test_entry_applications import enforce_sqlite_foreign_keys,record
from tests.test_entry_interviews import admins
from tests.test_entry_channel_stops import activation
from tests import test_operator_sop_reviews as core, test_entry_processes as process
from tests import test_entry_source_scenarios as visa, test_work_process_v2 as work
from tests import test_entry_issued as issued, test_applicant_profiles as profiles
from tests.test_entry_process_dependencies import regularization_at_u06
from tests.test_source_sop_products import operator_sop


def source(env,tmp_path):
    core.connected.source(env,tmp_path,source_file=Path(__file__).resolve().parents[1]/'runs/specialist-source.pdf')


def review(env,root,key,allowed,monkeypatch,*,process_policy=None,time='16:00'):
    authority=core.authority(env,core.rules.PREFIX+key,process=process_policy,package=allowed)
    arguments=dict(actor=ADMIN,case_id=root['case_id'],applicant_id=root['applicant_id'],application_id=root['id'],
        rule_unit_id=authority.policy.document['rule_id'],authority=authority)
    from app.config import settings
    current=list(settings.kg_operator_sop_authorities)
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[a for a in current if a['policy']['rule_id']!=arguments['rule_unit_id']]+[authority.document])
    preview=core.preview(env,arguments)
    assert preview['report']['status']=='available',preview
    saved,request=core.write(env,arguments,key='source-'+key,time=time)
    task=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**core.task_args(arguments),enable=True))
    assert task['task']['status']=='planned' and task['task']['at']==saved['snapshot']['schedule']['at']
    assert saved['snapshot']['report']['operational_due_on'] is None
    return arguments,saved,request,task


def test_visa_full_source_receipt_wait_becomes_stale_after_actual_ack(env,tmp_path,monkeypatch):
    source(env,tmp_path);original=process.transition;captured=[]
    def transition(environment,root,target,**kwargs):
        result=original(environment,root,target,**kwargs)
        if target=='V22':captured.append(review(env,root,'RECEIPT_REVIEW',kwargs['package_policy'],monkeypatch))
        return result
    monkeypatch.setattr(process,'transition',transition)
    visa.visa_sop(env,preliminary=True)
    assert len(captured)==1
    arguments,saved,request,task=captured[0]
    current=asyncio.run(tasks.read_deadline_task(env['engine'],**core.task_args(arguments)))
    assert current['current']['task']['id']==task['task']['id'] and current['current']['task']['status']=='cancelled'
    assert asyncio.run(core.service.record(env['engine'],**(request|{'authority':None})))==saved


def test_work_resident_status_uses_own_child_and_employer_followup_role(env,tmp_path,monkeypatch):
    source(env,tmp_path);original=work.transition;captured=[]
    def transition(environment,root,target,**kwargs):
        result=original(environment,root,target,**kwargs)
        if target in ('W18','W21'):
            key='RES_STATUS' if target=='W18' else 'EMPLOYER_TAX'
            captured.append(review(env,root,key,kwargs['package_policy'],monkeypatch,process_policy=work.policy(),time=None))
        return result
    monkeypatch.setattr(work,'transition',transition)
    root,_,_,_=work.complete_work_flow(env,monkeypatch)
    assert len(captured)==2
    first,second=captured
    assert first[1]['snapshot']['report']['evidence']['active_role']=='resident'
    assert second[1]['snapshot']['report']['evidence']['active_role']=='resident_registration'
    assert first[1]['snapshot']['report']['evidence']['active_application_id']!=root['id']
    for arguments,saved,request,task in captured:
        replay=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**core.task_args(arguments),replay=True))
        assert replay['selected']==saved


def test_student_annual_review_is_selected_time_not_invented_document_expiry(env,tmp_path,monkeypatch):
    source(env,tmp_path);story=operator_sop(env,'student');root=story['root'];allowed=story['policy'];on=process.today()
    issued.write(env,root,'file',dict(fingerprint='a'*64,passport_fingerprint='b'*64,on=on))
    process.transition(env,root,'V21',package_policy=allowed)
    issued.review(env,root,on=on)
    for channel in ('messenger','email','crm'):
        issued.write(env,root,'delivery',dict(version=1,fingerprint='a'*64,on=on,channel=channel,proof='c'*64,pamphlet='d'*64))
    process.transition(env,root,'V22',package_policy=allowed)
    issued.write(env,root,'receipt',dict(version=1,fingerprint='a'*64,on=on,proof='e'*64,identity_checked=True))
    process.transition(env,root,'V23',package_policy=allowed)
    issued.write(env,root,'travel',dict(direction='entry',on=on,proof='f'*64,source='stamp',passport_fingerprint='b'*64))
    process.transition(env,root,'V24',package_policy=allowed)
    arguments,saved,request,task=review(env,root,'STUDENT_ANNUAL',allowed,monkeypatch,time=None)
    assert saved['snapshot']['schedule']['calculated'] is False and saved['snapshot']['schedule']['official'] is False
    assert task['task']['at'] is None
    # Keep all own source facts; changing only student purpose invalidates it.
    doc=profiles.request();doc['as_of']=on;doc['profile']['purpose']='tourism'
    profiles.save(env,story['subject'],doc=doc,revision=1,key='student-purpose-changed')
    current=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**core.task_args(arguments)))
    assert current['task']['status']=='cancelled'
    assert asyncio.run(core.service.record(env['engine'],**request))==saved


def test_u09_own_exit_branch_unknown_ban_end_remains_unknown(env,tmp_path,monkeypatch):
    source(env,tmp_path);root,child,allowed,_=regularization_at_u06(env,'exit_visa','exit_visa','L')
    record(env,child,'approve',status='approved',occurred_on='2026-09-02',reference=f"PS{child['id']:06}")
    issued.file(env,child);issued.review(env,child)
    process.transition(env,root,'U07',package_policy=allowed)
    issued.write(env,child,'travel',dict(direction='exit',on='2026-09-05',proof='7'*64,source='official_record',passport_fingerprint='b'*64))
    process.transition(env,root,'U08',package_policy=allowed)
    process.attest(env,root,'completion_reviewed',role='exit_visa')
    process.transition(env,root,'U09',package_policy=allowed)
    arguments,saved,request,task=review(env,root,'ENTRY_BAN_REVIEW',allowed,monkeypatch,time=None)
    assert saved['snapshot']['report']['evidence']['active_application_id']==child['id']
    assert saved['snapshot']['report']['operational_due_on'] is None
    assert saved['snapshot']['schedule']['calculated'] is False
