"""Explicit package collection withdrawal must remain a current stop."""
import asyncio
from app.config import settings
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests import test_operator_sop_reviews as core, test_entry_document_packages as packages


def test_actual_package_privacy_blocks_new_review_but_preserves_original(env,tmp_path,monkeypatch):
    prepared=core.setup(env,tmp_path);args=core.args(env,prepared);app=prepared[1]
    packages.setup(env,app=app,product='TS')
    packages.write(env,app,'consent',dict(status='granted',on='2026-10-13',reference='OWN-CONSENT',proof='a'*64))
    assert core.preview(env,args)['report']['status']=='available'
    saved,request=core.write(env,args)
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[prepared[-1].document])
    first=asyncio.run(core.tasks.reconcile_deadline_task(env['engine'],**core.task_args(args),enable=True))
    packages.write(env,app,'consent',dict(status='withdrawn',on='2026-10-13',reference='WITHDRAWN',proof='b'*64))
    fresh=core.preview(env,args)['report']
    assert fresh['status']=='unknown',fresh
    assert asyncio.run(core.service.record(env['engine'],**(request|dict(authority=None))))==saved
    current=asyncio.run(core.tasks.reconcile_deadline_task(env['engine'],**core.task_args(args)))
    assert current['task']['id']==first['task']['id'] and current['task']['status']=='cancelled'
