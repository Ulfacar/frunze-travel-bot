"""Actual original source + explicit SYNTHETIC delegation; connected real journals."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain import conditional_deadlines as service, conditional_deadline_rules as rules
from app.domain import conditional_deadline_sources as sources, entry_anchors, entry_deadlines, entry_deadline_tasks
from app.domain.conditional_deadline_policy import ConditionalAuthority
from app.domain.entry_storage import _hash, EntryStorageInvalid, EntryStorageConflict
from app.domain.knowledge_publication import _policy
from app.domain.models import EntryDeadlineRevision, EntryConditionalEvidence
from app.knowledge.work_calendar import WorkCalendars
from tests.test_admin_kg_entry import env, ADMIN, FIX
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests import test_entry_anchors as actual, test_connected_qualification as connected
from tests.test_knowledge_publication import POLICY, preview as publication_preview

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    from app.domain import entry_applications, applicant_profiles, applicant_stay_history, knowledge_decisions, knowledge_publication
    at = datetime(2026,10,13,10,tzinfo=timezone.utc)
    for module in (service, sources, entry_anchors, entry_applications, applicant_profiles, applicant_stay_history, knowledge_decisions, knowledge_publication):
        monkeypatch.setattr(module, '_now', lambda:at)


def authority(env, rule):
    manifest = publication_preview(env, ids=env['published'])['manifest']; spec = rules.definition(rule)
    unit = next((u for u in env['bundle']['units'] if u['unit_id']==rule), spec)
    calendars = WorkCalendars(json.loads((FIX/'synthetic_work_calendars.json').read_text('utf-8')))
    ap = actual.policy()
    p = rules.ConditionalPolicy(dict(format=rules.FORMAT, reference='SYNTHETIC-CONDITIONAL', proof='f'*64,
        operators=['admin'], valid_from='2026-01-01', review_due_on='2026-12-31', rule_id=rule,
        definition_hash=_hash(spec), source_hash=rules.SOURCE_HASH,
        **{k:manifest[k] for k in ('bundle_hash','projection_hash','catalog_hash')}, rule_hash=_hash(unit),
        publication_policy_hash=_hash(_policy(POLICY)), required_units=['KG.REG.DEFAULT'], anchor_policy_hash=ap.digest,
        calendar_hash=calendars.content_hash, calendar_reference='SYNTHETIC-CALENDAR', calendar_proof='e'*64,
        calendar_valid_from='2026-01-01', calendar_review_due_on='2027-12-31', count_anchor_day=False,
        boundary_inclusive=True, code_anchor='official_code_received_on' if spec['anchor_kind']=='registration_payment_code' else 'not_applicable',
        period_counting='both_boundary_dates' if rule=='KG.DL.INTERNAL_EAEU_REG_REVIEW' else 'not_applicable',
        absence_counting='elapsed_dates' if spec['anchor_kind']=='actual_absence' else 'not_applicable',
        absence_handling='observed_review_day' if spec['anchor_kind']=='actual_absence' else 'not_applicable'))
    return ConditionalAuthority(p, ap, POLICY, calendars)


def setup(env, tmp_path, kind='registration_period'):
    connected.source(env, tmp_path, source_file=ROOT/'runs/specialist-source.pdf')
    prepared = actual.setup(env, kind)
    if kind == 'registration_period':
        doc=actual.profiles.request();doc['profile'].update(citizenship=['RUS'],entry_passport_country='RUS',purpose='work_hire',
            current_location='in_kg',in_kg_since='2026-09-03',current_basis_in_kg='visa_free')
        saved=actual.profiles.save(env,prepared[0],doc=doc,revision=1,key='CURRENT-REG-PROFILE')
        prepared=(prepared[0],prepared[1],saved)
    request = actual.args(env, prepared, kind)
    if kind=='registration_payment_code': request['operation']['data']['value']={'event_meaning':'official_code_received_on'}
    actual.write(env, request)
    return prepared


def renewal(env, prepared):
    doc=actual.profiles.request();doc['profile'].update(citizenship=['RUS'],entry_passport_country='RUS',
        purpose='medical',current_location='in_kg',in_kg_since='2026-09-03',current_basis_in_kg='visa',
        current_visa_type='B',current_basis_until='2026-11-01')
    updated=actual.profiles.save(env,prepared[0],doc=doc,revision=1,key='VISA-RENEWAL-PROFILE')
    prepared=(prepared[0],prepared[1],updated)
    period=actual.write(env,actual.args(env,prepared,'visa_period'))
    args=actual.args(env,prepared,'visa_renewal_context','RENEWAL')
    args['operation']['data']['value']=dict(period_anchor_id=period['id'],period_anchor_hash=period['snapshot_hash'],
        intent='same_product_renewal',current_type='B',target_type='B',current_purpose='medical',target_purpose='medical',
        current_inviter_ref='f'*64,target_inviter_ref='f'*64,premise_proof='e'*64)
    return prepared,args


def arguments(env, prepared, rule, allowed):
    subject, app, _ = prepared
    return dict(actor=ADMIN, case_id=app['case_id'], applicant_id=subject['id'], application_id=app['id'],
        rule_unit_id=rule, authority=allowed)


def preview(env, args): return asyncio.run(service.preview(env['engine'], **args))


def write(env, args, *, key='conditional-one'):
    current = preview(env, args)
    request = args | dict(expected_revision=current['revision'], request_key=key,
        operation=dict(action='conditional_review', confirmed=True, evidence_hash=current['report']['evidence_hash']))
    return asyncio.run(service.record(env['engine'], **request)), request


def test_actual_period_to_existing_receipt_task_withdrawal_and_old_retry(env,tmp_path,monkeypatch):
    prepared=setup(env,tmp_path); rule='KG.DL.INTERNAL_EAEU_REG_REVIEW'; allowed=authority(env,rule)
    args=arguments(env,prepared,rule,allowed)
    result=preview(env,args)['report']
    assert result['status']=='calculated',result
    assert result['review_due_on']=='2026-10-19' and result['operational_due_on'] is None
    assert sum(r['counted'] for r in result['calculations'][0]['calculation']['calendar_trace'])==10
    saved,request=write(env,args)
    from app.config import settings
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[allowed.document])
    task_args={k:v for k,v in args.items() if k not in ('applicant_id','authority')}
    task=asyncio.run(entry_deadline_tasks.reconcile_deadline_task(env['engine'],**task_args,enable=True))
    assert task['task']['date']=='2026-10-19' and task['task']['status']=='planned'
    withdraw=actual.args(env,prepared,policy=None)
    withdraw['operation']=dict(action='withdraw',confirmed=True,data=dict(on='2026-10-13',reason='wrong_document',proof='d'*64))
    actual.write(env,withdraw)
    task=asyncio.run(entry_deadline_tasks.reconcile_deadline_task(env['engine'],**task_args))
    assert task['task']['status']=='cancelled' and task['attention']=='unknown_date'
    assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==saved
    cleared=asyncio.run(service.record(env['engine'],**(args|dict(authority=None,expected_revision=1,request_key='clear',
        operation=dict(action='conditional_clear',confirmed=True,evidence_hash=saved['snapshot_hash'])))))
    assert cleared['summary']['review_due_on'] is None
    replay=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**task_args,revision=1,replay=True))
    assert replay['selected']['snapshot']==saved['snapshot']
    assert replay['conditional_current']['review_due_on'] is None
    async def counts():
        async with env['sm']() as session:
            return len((await session.scalars(select(EntryDeadlineRevision))).all()),len((await session.scalars(select(EntryConditionalEvidence))).all())
    assert asyncio.run(counts())==(2,2)


def test_code_actual_meaning_and_source_authority_fail_closed(env,tmp_path):
    prepared=setup(env,tmp_path,'registration_payment_code');rule='KG.DL.REGISTRATION_CODE_PAYMENT'
    allowed=authority(env,rule);args=arguments(env,prepared,rule,allowed)
    result=preview(env,args)['report'];assert result['review_due_on']=='2026-09-09',result['reason']
    saved,request=write(env,args)
    wrong=deepcopy(allowed.document);wrong['policy']['code_anchor']='official_code_issued_on'
    from app.domain.conditional_deadline_policy import from_document
    assert preview(env,args|{'authority':from_document(wrong)})['report']['review_due_on'] is None
    assert preview(env,args|{'authority':None})['report']['review_due_on'] is None
    assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==saved


@pytest.mark.parametrize('rule,expected',[
    ('KG.DL.VISA_EXTENSION','2026-10-23'),('KG.DL.RC_BEFORE_EP_END','2026-10-16'),
    ('KG.DL.EP_BEFORE_RC_END','2026-10-21'),('KG.DL.INTERNAL_RES_PREPARATION','2026-10-07'),
    ('KG.DL.REGISTRATION_EXTENSION','2026-10-30'),('KG.DL.DISMISSAL_NOTIFICATION','2026-11-02'),
    ('KG.DL.EXIT_AFTER_EP_END','2026-11-29'),('KG.DL.INTERNAL_DISMISSAL_EXIT_PLAN','2026-11-29')])
def test_source_offsets_use_explicit_counting(rule,expected,env,tmp_path):
    connected.source(env,tmp_path,source_file=ROOT/'runs/specialist-source.pdf')
    allowed=authority(env,rule)
    result=rules.calculate(allowed.policy,'2026-10-30',allowed.calendars,on='2026-10-13')
    assert result['due']==expected


def test_source_absence_29_30_31_is_trigger_not_filing_deadline(env,tmp_path):
    connected.source(env,tmp_path,source_file=ROOT/'runs/specialist-source.pdf')
    allowed=authority(env,'KG.DL.INTERNAL_ABSENCE_REG_REVIEW')
    for returned,count in [('2026-09-30',29),('2026-10-01',30),('2026-10-02',31)]:
        result=rules.absence_threshold(allowed.policy,'2026-09-01',returned)
        assert result==dict(days=count,threshold=30,triggered=count>=30,filing_due_on=None)


def test_real_visa_period_requires_renewal_premises_and_reconciles_identity(env,tmp_path):
    prepared=setup(env,tmp_path,'visa_period');prepared,context=renewal(env,prepared)
    rule='KG.DL.VISA_EXTENSION';allowed=authority(env,rule);args=arguments(env,prepared,rule,allowed)
    assert preview(env,args)['report']['reason']=='conditional_deadline_renewal_premises_required'
    actual.write(env,context)
    result=preview(env,args)['report'];assert result['review_due_on']=='2026-10-26',result
    saved,request=write(env,args)
    changed=deepcopy(context);changed.update(expected_revision=3,request_key='NEW-INVITER')
    changed['operation']['data']['value']['target_inviter_ref']='1'*64
    actual.write(env,changed)
    result=preview(env,args)['report'];assert result['reason']=='conditional_deadline_renewal_premises_conflict'
    assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==saved


def test_all_remaining_source_periods_and_events_connect_to_saved_receipts(env,tmp_path):
    connected.source(env,tmp_path,source_file=ROOT/'runs/specialist-source.pdf')
    for index,(kind,rule,due) in enumerate([
        ('permit_period','KG.DL.RC_BEFORE_EP_END','2026-10-19'),
        ('permit_period','KG.DL.INTERNAL_RES_PREPARATION','2026-10-08'),
        ('resident_period','KG.DL.EP_BEFORE_RC_END','2026-10-22'),
        ('registration_period','KG.DL.REGISTRATION_EXTENSION','2026-11-01'),
        ('employment_ended','KG.DL.DISMISSAL_NOTIFICATION','2026-09-08'),
        ('employment_ended','KG.DL.INTERNAL_DISMISSAL_EXIT_PLAN','2026-10-05'),
        ('permit_terminated','KG.DL.EXIT_AFTER_EP_END','2026-10-05'),
        ('address_change','KG.DL.REREGISTRATION','2026-09-18')]):
        prepared=actual.setup(env,kind,key='SOURCE'+str(index));actual.write(env,actual.args(env,prepared,kind))
        allowed=authority(env,rule);args=arguments(env,prepared,rule,allowed)
        result=preview(env,args)['report'];assert result['review_due_on']==due,(rule,result)
        saved,request=write(env,args,key='SOURCE'+str(index))
        assert saved['summary']['operational_due_on'] is None
        assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==saved


def test_actual_absence_29_30_31_own_history_controls_real_saved_review(env,tmp_path):
    from tests import test_applicant_stay_history as stay
    connected.source(env,tmp_path,source_file=ROOT/'runs/specialist-source.pdf')
    rule='KG.DL.INTERNAL_ABSENCE_REG_REVIEW';allowed=authority(env,rule)
    for count,exited in [(29,'2026-09-14'),(30,'2026-09-13'),(31,'2026-09-12')]:
        subject=actual.person(env,'ABSENCE'+str(count));app=actual.application(env,subject,'RETURN'+str(count),procedure='registration')
        doc=actual.profiles.request();doc['profile'].update(current_location='in_kg',in_kg_since='2026-10-13',
            current_basis_in_kg='visa_free',entry_date='2026-10-13',exit_date='2026-12-01')
        doc['as_of']='2026-10-13'
        saved=actual.profiles.save(env,subject,doc=doc,key='RETURN'+str(count))
        document=stay.document(history_complete=True,intervals=[
            stay.interval(ref='before-return',entry_date='2026-08-01',exit_date=exited),
            stay.interval(ref='returned',entry_date='2026-10-13',exit_date=None)])
        document['as_of']='2026-10-13'
        stay.save(env,subject,saved,doc=document)
        args=arguments(env,(subject,app,saved),rule,allowed);report=preview(env,args)['report']
        assert report['trigger']==dict(days=count,threshold=30,triggered=count>=30,filing_due_on=None),report
        if count==29:assert report['review_due_on'] is None
        else:
            receipt,request=write(env,args,key='ABSENCE'+str(count))
            assert receipt['summary']['review_due_on']=='2026-10-13' and receipt['summary']['operational_due_on'] is None
            assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==receipt
