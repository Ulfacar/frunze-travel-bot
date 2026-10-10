"""Connected synthetic source scenarios, with absent product links left visible.

PDF v1.1 physical79-80 (§19.1) and89-90 (B.8). These are operator-driven
service calls, not a claim that the installed bot orchestrates the whole SOP.
No real policy, legal result, portal, payment or delivery is approved here.
"""
import asyncio
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain.entry_storage import EntryStorageInvalid
from app.domain.models import ServiceCase, ServiceEvent
from app.knowledge.qualification import QualificationReview
from app.knowledge.validation import load_document
from scripts.build_kg_entry_conditions import build_catalog
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import enforce_sqlite_foreign_keys, person, application, record
from tests.test_entry_interviews import admins
from tests.test_entry_channel_stops import activation
from tests import test_applicant_profiles as profiles
from tests import test_entry_interviews as interviews
from tests import test_entry_channel_stops as stops
from tests import test_entry_quotes as quotes
from tests import test_entry_document_packages as packages
from tests import test_entry_processes as processes
from tests import test_entry_portal as portal
from tests import test_entry_issued as issued
from tests import test_entry_applications as applications

SOURCE_SHA256 = '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'


def handoff(env, subject, *, purpose='tourism', language='ru'):
    """Persist typed facts, bind an actual Dialog, then acknowledge exact card."""
    iv = interviews.start(env, subject, language=language)
    interviews.correct(env, iv, {'purpose': purpose})
    did = stops.dialog(env)
    saved = stops.bind(env, iv, did)
    card = deepcopy(interviews.read(env, iv)['state']['handoff'])
    assert saved['card_hash'] == card['hash']
    assert stops.send(env)[1] == []
    interviews.action(env, iv, 'ack')
    assert interviews.read(env, iv)['state']['handoff'] == card
    assert stops.send(env)[1] == []
    return iv, saved


def profile_and_process(env, subject, *, procedure='visa'):
    saved = profiles.save(env, subject)
    app = processes.setup(env, applicant=subject, procedure=procedure)
    role = {'visa': 'visa', 'registration': 'registration',
            'unified_permit': 'permit', 'violation_protocol': 'protocol'}[procedure]
    processes.attest(env, app, 'profile_review_complete', role=role,
                     profile_id=saved['qualification_id'])
    assert app['applicant_id'] == subject['id']
    return app, saved


def portal_decision(env, app, *, kind='approval', key='decision'):
    current = applications.read(env, app)['current']
    reference = current['reference']
    receipt = portal.receive(env, text=portal.message(kind, reference),
                             transport_id='SYN-'+key, request_key=key)
    assert applications.read(env, app)['current'] == current
    assert portal.read(env, receipt)['candidate']['application_id'] == app['id']
    portal.action(env, receipt, 'correlate')
    assert applications.read(env, app)['current'] == current
    args = portal.action_args(env, receipt, 'confirm')
    result = asyncio.run(portal.service.record_action(env['engine'], **args))
    assert asyncio.run(portal.service.record_action(env['engine'], **(args | {'policy': None}))) == result
    return result


def test_source_19_visa_same_subject_through_handoff_quote_rework_portal_and_aftercare(env):
    # The current product requires an existing service case. Its real contract
    # service was called by env; qualification-before-contract is NOT simulated.
    async def contract():
        async with env['sm']() as session:
            case = await session.get(ServiceCase, env['cases']['visa'])
            events = list(await session.scalars(select(ServiceEvent).where(
                ServiceEvent.case_id == case.id, ServiceEvent.event_type == 'contract_signed')))
            return case.contract_reference, events
    reference, contract_events = asyncio.run(contract())
    assert reference and len(contract_events) == 1
    subject = person(env, 'SOP-VISA')
    iv, stop = handoff(env, subject)
    app, profile = profile_and_process(env, subject)

    # A partial estimate is retained; it cannot silently become a complete quote
    # or overwrite the independently agreed contract price.
    quote = quotes.save(env, app)
    assert quote['receipt']['applicant_id'] == subject['id']
    assert not quote['receipt']['result']['complete']
    assert quote['receipt']['result']['totals_by_currency'] is None
    assert quote['receipt']['result']['payment'] == 'not_created'
    packages.setup(env, app=app, product='TS')
    package_policy = packages.complete(env, app)
    packages.approve(env, app, package_policy)
    for fact, value in [('conversation_started', True), ('manager_review_required', False),
                        ('eligibility', 'eligible'), ('visa_required', True), ('quote_sent', True),
                        ('offer_accepted', True), ('invoice_issued', True), ('checklist_sent', True),
                        ('portal_draft_created', True), ('email_verified', True),
                        ('portal_payment_confirmed', True)]:
        # These are explicitly synthetic operator attestations, not decisions
        # inferred from the draft profile/quote or actual external transmissions.
        processes.attest(env, app, fact, value,
                         profile_id=profile['qualification_id'] if fact in ('eligibility', 'visa_required') else None)
    for stage in ('V02', 'V04', 'V06', 'V07', 'V08'):
        processes.transition(env, app, stage, package_policy=package_policy)
    processes.money(env, amount='40000', currency='KGS', idempotency_key='SOP-PAY-1')
    with pytest.raises(EntryStorageInvalid, match='prerequisites'):
        processes.transition(env, app, 'V09', package_policy=package_policy)
    processes.money(env, amount='60000', currency='KGS', idempotency_key='SOP-PAY-2')
    for stage in ('V09', 'V10', 'V12', 'V14', 'V15'):
        processes.transition(env, app, stage, package_policy=package_policy)
    record(env, app, 'submit', reference='SV000001', occurred_on='2026-09-01')
    for stage in ('V16', 'V17'):
        processes.transition(env, app, stage, package_policy=package_policy)

    portal_decision(env, app, kind='correction', key='correction')
    assert applications.read(env, app)['current']['status'] == 'revision_requested'
    processes.transition(env, app, 'V18', package_policy=package_policy)
    with pytest.raises(EntryStorageInvalid, match='prerequisites'):
        processes.transition(env, app, 'V19', package_policy=package_policy)
    record(env, app, 'resubmit', reference='SV000001', occurred_on='2026-10-10')
    packages.approve(env, app, package_policy, key='SOP-RECHECK')
    for stage in ('V19', 'V17'):
        processes.transition(env, app, stage, package_policy=package_policy)
    portal_decision(env, app, key='approval')
    processes.transition(env, app, 'V20', package_policy=package_policy)
    on = processes.today()
    issued.write(env, app, 'file', dict(fingerprint='a'*64, passport_fingerprint='b'*64, on=on))
    processes.transition(env, app, 'V21', package_policy=package_policy)
    with pytest.raises(EntryStorageInvalid, match='review_required'):
        issued.write(env, app, 'delivery', dict(version=1, fingerprint='a'*64, on=on,
                     channel='email', proof='c'*64, pamphlet='d'*64))
    issued.review(env, app, on=on)
    for channel in ('messenger', 'email', 'crm'):
        issued.write(env, app, 'delivery', dict(version=1, fingerprint='a'*64, on=on,
                     channel=channel, proof='c'*64, pamphlet='d'*64))
    processes.transition(env, app, 'V22', package_policy=package_policy)
    issued.write(env, app, 'receipt', dict(version=1, fingerprint='a'*64, on=on,
                 proof='e'*64, identity_checked=True))
    processes.transition(env, app, 'V23', package_policy=package_policy)
    issued.write(env, app, 'travel', dict(direction='entry', on=on, proof='f'*64,
                 source='stamp', passport_fingerprint='b'*64))
    processes.transition(env, app, 'V24', package_policy=package_policy)
    with pytest.raises(EntryStorageInvalid, match='prerequisites'):
        processes.transition(env, app, 'V25', package_policy=package_policy)
    issued.write(env, app, 'travel', dict(direction='exit', on=on, proof='1'*64,
                 source='official_record', passport_fingerprint='b'*64))
    processes.attest(env, app, 'followup_completed')
    end = processes.transition(env, app, 'V25', package_policy=package_policy)
    assert end['snapshot']['stage'] == 'V25'
    assert end['snapshot']['root_id'] == app['id']
    assert profiles.read(env, subject)['saved'] == profile
    assert interviews.read(env, iv)['state']['phase'] == 'acked'
    assert stops.send(env)[1] == []
    assert quotes.read(env, app)['history'][0]['receipt'] == quote['receipt']


def test_source_registration_same_subject_certificate_requires_separate_decision(env):
    subject = person(env, 'SOP-REG')
    handoff(env, subject)
    app, _ = profile_and_process(env, subject, procedure='registration')
    packages.setup(env, app=app, product='REG')
    allowed = packages.complete(env, app)
    packages.approve(env, app, allowed)
    for fact in ('stay_basis_checked', 'payment_code_received',
                 'registration_payment_confirmed', 'registration_certificate_received',
                 'completion_reviewed', 'followup_completed'):
        processes.attest(env, app, fact, role='registration')
    for stage in ('R02', 'R03'):
        processes.transition(env, app, stage, package_policy=allowed)
    record(env, app, 'submit', reference='SR000001', occurred_on='2026-09-01')
    for stage in ('R04', 'R05'):
        processes.transition(env, app, stage, package_policy=allowed)
    with pytest.raises(EntryStorageInvalid, match='prerequisites'):
        processes.transition(env, app, 'R06', package_policy=allowed)
    portal_decision(env, app, key='registration')
    for stage in ('R06', 'R07', 'R08'):
        processes.transition(env, app, stage, package_policy=allowed)
    assert processes.read(env, app)['application']['procedure'] == 'registration'


B8 = {
    'us_tourism_45': dict(language='en', purpose='tourism', country='USA',
        location='abroad', entry='2027-05-01', exit='2027-06-14', pages=[89]),
    'india_business_10': dict(language='ru', purpose='business_meeting', country='IND',
        location='abroad', entry='2026-12-01', exit='2026-12-10', pages=[90]),
    'uzbekistan_garment_work': dict(language='ru', purpose='work_hire', country='UZB',
        location='in_kg', entry='2026-09-20', exit='2026-11-01', pages=[90]),
}


@pytest.fixture(scope='module')
def source_review():
    root = Path(__file__).resolve().parents[1]
    bundle = {name: load_document(root/'knowledge/kg_entry/draft-v1.1'/f'{name}.yaml')
              for name in ('meta', 'countries', 'units')}
    assert bundle['meta']['source_hash'] == SOURCE_SHA256
    return QualificationReview(**bundle, source_hash=SOURCE_SHA256, catalog=build_catalog())


@pytest.mark.parametrize('name', B8)
def test_exact_b8_facts_survive_handoff_and_unapproved_source_never_becomes_advice(env, source_review, name):
    example = B8[name]
    subject = person(env, 'B8-'+name)
    iv = interviews.start(env, subject, language=example['language'])
    # Exact PDF situations, with deterministic dates added solely for rehearsal.
    interviews.correct(env, iv, {'citizenships': [example['country']]})
    # The separate passport-country question applies to multiple citizenships;
    # these exact examples declare one citizenship and must not force that slot.
    interviews.correct(env, iv, {'location': example['location'], 'purpose': example['purpose']})
    if interviews.read(env, iv)['state']['phase'] == 'pending':
        interviews.action(env, iv, 'ack')
    owner = interviews.OWNER if interviews.read(env, iv)['state']['phase'] == 'acked' else ADMIN
    dates = {'entry_on': example['entry'], 'exit_on': example['exit']}
    if example['location'] == 'in_kg':
        dates = {'actual_entry.on': example['entry'], 'employment.garment': True}
    interviews.correct(env, iv, dates, actor=owner)
    did = stops.dialog(env)
    stops.bind(env, iv, did)
    if interviews.read(env, iv)['state']['phase'] == 'pending':
        interviews.action(env, iv, 'ack')
    current = interviews.read(env, iv)
    assert current['state']['answers']['citizenships']['value'] == [example['country']]
    assert current['state']['answers']['purpose']['value'] == example['purpose']
    assert current['current_analysis']['legal_qualification'] == 'unknown'
    assert stops.send(env)[1] == []
    request = profiles.request()
    request['language'] = example['language']
    request['profile'].update(citizenship=[example['country']], entry_passport_country=example['country'],
        purpose=example['purpose'], current_location=example['location'],
        entry_date=example['entry'], exit_date=example['exit'])
    if example['location'] == 'in_kg':
        request['profile'].update(in_kg_since=example['entry'], current_basis_in_kg='visa_free')
        assert (date(2026, 10, 11)-date.fromisoformat(example['entry'])).days == 21
    result = source_review.evaluate(request)
    assert result['source']['source_hash'] == SOURCE_SHA256
    assert result['candidate_rules']
    assert not result['may_quote'] and not result['publication_approved']
    assert result['selected_regime'] is None and result['visa_required'] is None
    assert result['exact_deadline'] is None and result['exact_remaining_days'] is None
    assert 'publication_not_approved' in result['blockers']
    if name == 'uzbekistan_garment_work':
        assert result['status'] == 'manager_review' and 'work_purpose_review' in result['stop_reasons']
    else:
        expected = 45 if name == 'us_tourism_45' else 10
        assert (date.fromisoformat(example['exit'])-date.fromisoformat(example['entry'])).days+1 == expected
    # No invented technical bridge: this read-only review is explicitly invoked
    # by the operator; the interview does not persist its result automatically.
    assert profiles.read(env, subject)['saved'] is None
