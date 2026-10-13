import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from tests.test_entry_process_postgres import template,env
from tests.test_conditional_deadlines import clock
from tests import test_conditional_deadlines as core
from tests.test_specialist_postgres import waiting
from app.domain import conditional_deadlines as service,entry_deadline_tasks as tasks
from app.domain import applicant_profiles


def prepared_task(env,tmp_path,monkeypatch):
    prepared=core.setup(env,tmp_path);rule='KG.DL.REGISTRATION_EXTENSION'
    allowed=core.authority(env,rule);options=core.arguments(env,prepared,rule,allowed)
    saved,request=core.write(env,options)
    from app.config import settings
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[allowed.document])
    task_options={k:v for k,v in options.items() if k not in ('authority','applicant_id')}
    return prepared,request,saved,task_options


def test_task_projection_holds_person_lock_against_actual_profile_writer(env,tmp_path,monkeypatch):
    prepared,request,saved,task_options=prepared_task(env,tmp_path,monkeypatch)
    original=service.current;entered=threading.Event();release=threading.Event()
    async def hold(*a,**kw):
        result=await original(*a,**kw)
        if not entered.is_set():entered.set();assert await asyncio.to_thread(release.wait,30)
        return result
    monkeypatch.setattr(service,'current',hold)
    def enable():return asyncio.run(tasks.reconcile_deadline_task(env['engine'],**task_options,enable=True))
    def profile():
        doc=core.actual.profiles.request()
        doc['profile'].update(citizenship=['RUS'],entry_passport_country='RUS',purpose='work_hire')
        return core.actual.profiles.save(env,prepared[0],doc=doc,revision=prepared[2]['revision'],key='AUDIT-PROFILE-CORRECTION')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(enable)
        try:
            assert entered.wait(30)
            writer=pool.submit(profile)
            waiting(env,writer)
        finally:release.set()
        bound=first.result(timeout=60);writer.result(timeout=60)
    assert bound['task']['status']=='planned'
    current=asyncio.run(tasks.read_deadline_task(env['engine'],**task_options))
    assert current['due_on'] is None
    assert asyncio.run(service.record(env['engine'],**(request|dict(authority=None))))==saved


def test_conditional_reader_keeps_case_before_application_lock_order(env,tmp_path,monkeypatch):
    prepared,request,saved,options=prepared_task(env,tmp_path,monkeypatch)
    original=core.actual.service.scope;entered=threading.Event();release=threading.Event()
    async def hold(*a,**kw):
        result=await original(*a,**kw)
        if threading.current_thread().name.startswith('audit-writer') and not entered.is_set():
            entered.set();assert await asyncio.to_thread(release.wait,30)
        return result
    monkeypatch.setattr(core.actual.service,'scope',hold)
    withdrawal=core.actual.args(env,prepared,policy=None)
    withdrawal['operation']=dict(action='withdraw',confirmed=True,data=dict(on='2026-10-13',reason='wrong_document',proof='d'*64))
    def writer():return core.actual.write(env,withdrawal)
    def reader():return asyncio.run(tasks.read_deadline_task(env['engine'],**options))
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='audit-writer') as wp, ThreadPoolExecutor(max_workers=1) as rp:
        first=wp.submit(writer)
        try:
            assert entered.wait(30)
            second=rp.submit(reader)
            waiting(env,second)
        finally:release.set()
        first.result(timeout=60);view=second.result(timeout=60)
    assert view['due_on'] is None
