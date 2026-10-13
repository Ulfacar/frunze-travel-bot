"""Cross-case quarantined document arrival must serialize current SOP admission."""
import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import event
from sqlalchemy.orm import Session
from tests.test_entry_process_postgres import template,env
from tests.test_specialist_postgres import waiting
from tests import test_operator_sop_reviews as core
from tests import test_entry_processes as processes
from tests.test_entry_quarantine import arguments as upload_arguments
from tests.test_quarantine_multipart import PDF
from app.domain.entry_quarantine import record_upload
from app.domain.models import EntryDeadlineRevision


def test_cross_case_quarantine_waits_for_current_sop_admission(env,tmp_path,monkeypatch):
    core.connected.source(env,tmp_path,source_file=core.ROOT/'runs/specialist-source.pdf')
    other_env=env|dict(cases=env['cases']|dict(visa=env['cases']['other']))
    other=processes.packages.setup(other_env,key='cross-case-upload')
    app,package=processes.visa_ready(env,fingerprint=hashlib.sha256(PDF).hexdigest())
    processes.money(env,amount='100000',currency='KGS',idempotency_key='full')
    for stage in ('V09','V10','V12','V14'):processes.transition(env,app,stage,package_policy=package)
    allowed=core.authority(env,core.rules.PREFIX+'READY_SUBMISSION_REVIEW',package=package)
    args=dict(actor=core.ADMIN,case_id=app['case_id'],applicant_id=app['applicant_id'],application_id=app['id'],
        rule_unit_id=allowed.policy.document['rule_id'],authority=allowed)
    assert core.preview(env,args)['report']['status']=='available'
    uploads=upload_arguments(other_env,other)
    entered=threading.Event();release=threading.Event()
    def pause(session,ctx):
        if session.info.get('audit_paused'):return
        if any(isinstance(r,EntryDeadlineRevision) and r.request_key=='audit-quarantine' for r in session.new):
            session.info['audit_paused']=True;entered.set();assert release.wait(30)
    event.listen(Session,'after_flush',pause)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(lambda:core.write(env,args,key='audit-quarantine'))
            try:
                assert entered.wait(60)
                second=pool.submit(lambda:asyncio.run(record_upload(env['engine'],**uploads)))
                waiting(env,second)
            finally:release.set()
            first.result(timeout=60);second.result(timeout=60)
    finally:release.set();event.remove(Session,'after_flush',pause)
    assert core.preview(env,args)['report']['status']=='unknown'


def test_existing_case_locked_hook_cancels_without_reverse_global_wait(env,tmp_path,monkeypatch):
    from app.config import settings
    from app.domain import entry_deadline_tasks as tasks
    from app.domain.models import EntryApplicationEvent
    own=core.setup(env,tmp_path);args=core.args(env,own);app=own[1]
    processes.packages.setup(env,app=app)
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[own[-1].document])
    saved,request=core.write(env,args);ta=core.task_args(args)
    bound=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta,enable=True))
    uploads=upload_arguments(env,app)
    entered=threading.Event();release=threading.Event()
    def pause(session,ctx):
        if session.info.get('audit_case_paused'):return
        if any(isinstance(r,EntryApplicationEvent) and r.request_key=='AUDIT-SUBMIT' for r in session.new):
            session.info['audit_case_paused']=True;entered.set();assert release.wait(30)
    event.listen(Session,'after_flush',pause)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(lambda:processes.record(env,app,'AUDIT-SUBMIT',reference='AD123456'))
            try:
                if not entered.wait(30):
                    first.result(timeout=5)
                    raise AssertionError('application pause was not reached')
                second=pool.submit(lambda:asyncio.run(record_upload(env['engine'],**uploads)))
                # Quarantine owns the global lock and waits on this exact case.
                waiting(env,second)
            finally:release.set()
            first.result(timeout=60);second.result(timeout=60)
    finally:release.set();event.remove(Session,'after_flush',pause)
    current=asyncio.run(tasks.read_deadline_task(env['engine'],**ta))['current']
    assert current['task']['id']==bound['task']['id'] and current['task']['status']=='cancelled'
    assert current['task']['at']=='2026-11-01T18:30:00+00:00'
    assert asyncio.run(core.service.record(env['engine'],**(request|dict(authority=None))))==saved
