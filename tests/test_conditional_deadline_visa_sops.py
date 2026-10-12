"""Source-specific actual visa expiry reviews, never product eligibility."""
import asyncio
from copy import deepcopy

import pytest

from app.config import settings
from tests import test_conditional_deadlines as core
from tests.test_conditional_deadlines import env,clock,enforce_sqlite_foreign_keys


@pytest.mark.parametrize('rule,visa_type,purpose,due',[
    ('KG.DL.INTERNAL_TS_EXIT_REVIEW','TS','tourism','2026-10-27'),
    ('KG.DL.INTERNAL_B_RENEWAL_PREPARATION','B','medical','2026-10-08'),
    ('KG.DL.INTERNAL_RL_RES_PREPARATION','RL','relatives_kg_citizen','2026-10-08'),
    ('KG.DL.INTERNAL_RL_RES_REVIEW','RL','relatives_kg_citizen','2026-10-19'),
    ('KG.DL.INTERNAL_S_RES_REVIEW','S','study','2026-10-19'),
])
def test_actual_visa_source_review_to_existing_task_and_retained_retry(env,tmp_path,monkeypatch,rule,visa_type,purpose,due):
    prepared=core.setup(env,tmp_path,'visa_period')
    if visa_type=='B':
        prepared,context=core.renewal(env,prepared)
    else:
        doc=core.actual.profiles.request()
        doc['profile'].update(citizenship=['RUS'],entry_passport_country='RUS',purpose=purpose,
            current_location='in_kg',in_kg_since='2026-09-03',current_basis_in_kg='visa',
            current_visa_type=visa_type,current_basis_until='2026-11-01')
        profile=core.actual.profiles.save(env,prepared[0],doc=doc,revision=1,key='CURRENT-VISA-PROFILE')
        prepared=(prepared[0],prepared[1],profile)
        core.actual.write(env,core.actual.args(env,prepared,'visa_period'))
    authority=core.authority(env,rule);arguments=core.arguments(env,prepared,rule,authority)
    if visa_type=='B':
        assert core.preview(env,arguments)['report']['reason']=='conditional_deadline_renewal_premises_required'
        core.actual.write(env,context)
    report=core.preview(env,arguments)['report']
    assert report['review_due_on']==due,report
    assert report['scope']=='internal_specialist_review_only' and report['filing_allowed'] is False
    assert report['permission_to_work'] is None and report['permission_to_remain'] is None
    receipt,request=core.write(env,arguments)
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[authority.document])
    task_args={k:v for k,v in arguments.items() if k not in ('applicant_id','authority')}
    task=asyncio.run(core.entry_deadline_tasks.reconcile_deadline_task(env['engine'],**task_args,enable=True))
    assert task['task']['date']==due and task['task']['status']=='planned'
    # A renewed profile with a different purpose does not grant this rule's scope,
    # even after the same actual document has been explicitly reconciled again.
    changed=deepcopy(core.actual.profiles.read(env,prepared[0])['saved']['input'])
    changed['profile']['purpose']='work_hire'
    profile=core.actual.profiles.save(env,prepared[0],doc=changed,revision=2,key='CHANGED-PURPOSE')
    corrected=(prepared[0],prepared[1],profile)
    core.actual.write(env,core.actual.args(env,corrected,'visa_period'))
    assert core.preview(env,arguments)['report']['review_due_on'] is None
    cancelled=asyncio.run(core.entry_deadline_tasks.reconcile_deadline_task(env['engine'],**task_args))
    assert cancelled['task']['id']==task['task']['id'] and cancelled['task']['status']=='cancelled'
    assert asyncio.run(core.service.record(env['engine'],**(request|{'authority':None})))==receipt
    old=asyncio.run(core.entry_deadlines.read_deadline_history(env['engine'],**task_args,revision=1,replay=True))
    assert old['selected']['snapshot']==receipt['snapshot']
    assert old['conditional_current']['review_due_on'] is None
