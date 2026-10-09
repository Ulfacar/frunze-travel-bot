"""Separate people, real FK-enforced SQLite, partial facts and uncertain retries."""
import asyncio
from copy import deepcopy
import json

import pytest
from sqlalchemy import delete, select, text, update

from app.domain import applicant_profiles as service
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _hash
from app.domain.models import DomainError, EntryApplicantProfile, EntryQualification
from app.domain.permissions import Actor
from app.domain.qualification_storage import save_qualification, read_qualification
from app.domain.service_authz import PermissionDenied
from app.knowledge.validation import load_document
from tests.test_admin_kg_entry import ADMIN, FIX, env
from tests.test_entry_applications import person, application, read as read_application, enforce_sqlite_foreign_keys


def request():
    return load_document(FIX / 'synthetic_qualification_review.json')


def save(env, applicant, *, revision=0, key='save', doc=None, case='visa', actor=ADMIN):
    return asyncio.run(service.save_applicant_profile(env['engine'], actor=actor, case_id=env['cases'][case],
        applicant_id=applicant['id'], expected_revision=revision, request_key=key,
        knowledge_version_id=env['version'], request=request() if doc is None else doc))


def read(env, applicant, *, case='visa', **kwargs):
    return asyncio.run(service.read_applicant_profile(env['engine'], actor=ADMIN,
        case_id=env['cases'][case], applicant_id=applicant['id'], **kwargs))


def test_people_never_inherit_payer_or_family_answers_and_applications_keep_identity(env):
    parent = person(env, 'parent')
    child = person(env, 'child', role='child')
    original = request()
    legacy = asyncio.run(save_qualification(env['engine'], actor=ADMIN, contact_id=env['contacts']['visa'],
        expected_revision=0, request_key='payer', knowledge_version_id=env['version'], request=original))
    assert read(env, parent)['saved'] is None and read(env, child)['saved'] is None
    adult = save(env, parent)
    younger = request(); younger['profile'] = {'citizenship': ['CHN'], 'entry_passport_country': 'CHN'}
    minor = save(env, child, doc=younger)
    assert adult['revision'] == minor['revision'] == 1
    assert adult['input'] != minor['input'] and 'contact_id' not in minor['result']
    assert minor['result']['applicant_id'] == child['id']
    assert minor['provenance']['context']['payer_contact_id'] == env['contacts']['visa']
    assert minor['result']['history']['status'] == 'not_attached'
    revised = save(env, parent, revision=1, key='revise', doc=younger)
    assert read(env, child)['saved'] == minor and revised['revision'] == 2
    assert asyncio.run(read_qualification(env['engine'], actor=ADMIN,
        contact_id=env['contacts']['visa'])) == legacy
    child_app = application(env, child)
    assert read_application(env, child_app)['applicant_id'] == child['id']


def test_revision_resume_replace_replay_and_independent_request_keys(env):
    applicant = person(env)
    doc = request(); doc['profile']['purpose'] = 'work_hire'
    original = deepcopy(doc)
    first = save(env, applicant, doc=doc)
    assert doc == original and first['result']['status'] == 'manager_review'
    partial = request(); partial['profile'] = {}; partial['language'] = 'en'
    second = save(env, applicant, doc=partial, revision=1, key='second')
    assert second['result']['status'] == 'needs_input' and second['previous_id'] == first['qualification_id']
    assert 'profile.purpose' in second['result']['missing_facts']
    assert read(env, applicant, qualification_id=first['qualification_id'])['saved'] == first
    assert read(env, applicant, replay=True)['saved'] == second
    assert save(env, applicant, doc=doc) == first
    assert not second['result']['may_quote'] and second['result']['selected_regime'] is None
    second['input']['profile']['purpose'] = 'work_hire'
    assert read(env, applicant)['saved']['input'] == partial
    with pytest.raises(EntryStorageConflict): save(env, applicant, doc=partial)
    with pytest.raises(EntryStorageConflict): save(env, applicant, key='stale')
    with pytest.raises(EntryStorageConflict): save(env, applicant, doc=doc, actor=Actor('other-admin', True))


def test_scope_history_and_no_client_supplied_subject(env):
    applicant = person(env)
    other = person(env, 'other', case='other')
    first = save(env, applicant)
    with pytest.raises(EntryStorageInvalid): read(env, applicant, case='other')
    with pytest.raises(EntryStorageInvalid): save(env, applicant, case='other')
    with pytest.raises(EntryStorageInvalid): read(env, other, case='other', qualification_id=first['qualification_id'])
    for field in ('contact_id', 'applicant_id', 'history_id'):
        doc = request(); doc[field] = 1
        with pytest.raises(EntryStorageInvalid): save(env, other, doc=doc, case='other')
    assert read(env, other, case='other')['saved'] is None


@pytest.mark.parametrize('actor', [None, {}, Actor('manager'), Actor('bot', True)])
def test_authorization_before_any_data_or_engine(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(service.read_applicant_profile(None, actor=actor, case_id=1, applicant_id=1))
    with pytest.raises(PermissionDenied):
        asyncio.run(service.save_applicant_profile(None, actor=actor, case_id=1, applicant_id=1,
            expected_revision=0, request_key='x', knowledge_version_id=1, request={}))


def test_invalid_input_and_size_fail_without_new_revision(env):
    applicant = person(env)
    for bad in (True, -1, 250, '1'):
        with pytest.raises(EntryStorageInvalid): save(env, applicant, revision=bad)
    for profile in ({'passport_pages_ok': 1}, {'unknown_key': 'PRIVATE'}, {'purpose_details': 'x'*50000}):
        doc = request(); doc['profile'] = profile
        with pytest.raises(EntryStorageInvalid) as error: save(env, applicant, doc=doc)
        assert 'PRIVATE' not in str(error.value)
    assert read(env, applicant)['current_revision'] == 0


@pytest.mark.parametrize('field,value', [('result_snapshot', '{}'), ('input_snapshot', '{}'), ('snapshot_hash', '0'*64)])
def test_tampered_history_refuses_read_write_and_retry(env, field, value):
    applicant = person(env)
    first = save(env, applicant)
    async def corrupt():
        async with env['engine'].begin() as conn:
            await conn.execute(text(f'UPDATE entry_applicant_profiles SET {field}=:value WHERE id=:id'),
                dict(value=value, id=first['qualification_id']))
    asyncio.run(corrupt())
    for fn in (lambda: read(env, applicant), lambda: save(env, applicant),
               lambda: save(env, applicant, revision=1, key='next')):
        with pytest.raises(EntryStorageInvalid): fn()


def test_orm_immutability_and_deleted_predecessor_are_detected(env):
    applicant = person(env)
    first = save(env, applicant)
    save(env, applicant, revision=1, key='next')
    async def scenario():
        async with env['sm']() as session:
            row = await session.get(EntryApplicantProfile, first['qualification_id'])
            with pytest.raises((TypeError, DomainError)): row.input_snapshot['profile']['purpose'] = 'work_hire'
            with pytest.raises(DomainError):
                await session.execute(update(EntryApplicantProfile).values(snapshot_hash='0'*64))
            with pytest.raises(DomainError): await session.execute(delete(EntryApplicantProfile))
        async with env['engine'].connect() as conn:
            await conn.execute(text('PRAGMA foreign_keys=OFF'))
            await conn.execute(text('DELETE FROM entry_applicant_profiles WHERE id=:id'), {'id': first['qualification_id']})
            await conn.commit()
    asyncio.run(scenario())
    with pytest.raises(EntryStorageInvalid): read(env, applicant)


def test_bounded_history_and_runtime_upgrade_preserve_read_but_refuse_replay(env, monkeypatch):
    applicant = person(env)
    first = save(env, applicant)
    runtime = service._runtime()
    monkeypatch.setattr(service, '_runtime', lambda: {**runtime, 'profile_code_hash': 'new'})
    assert read(env, applicant)['saved'] == first
    with pytest.raises(EntryStorageInvalid, match='runtime_changed'): read(env, applicant, replay=True)
    monkeypatch.setattr(service, 'MAX_BYTES', 1)
    with pytest.raises(EntryStorageInvalid, match='history_limit'): read(env, applicant)
    with pytest.raises(EntryStorageInvalid, match='history_limit'): save(env, applicant)


def test_concurrent_writers_create_only_one_successor(env):
    applicant = person(env)
    async def race():
        kwargs = dict(actor=ADMIN, case_id=env['cases']['visa'], applicant_id=applicant['id'],
            expected_revision=0, knowledge_version_id=env['version'], request=request())
        return await asyncio.gather(*(service.save_applicant_profile(env['engine'], request_key=k, **kwargs)
                                     for k in ('left', 'right')), return_exceptions=True)
    results = asyncio.run(race())
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, EntryStorageConflict) for r in results) == 1
    assert read(env, applicant)['current_revision'] == 1
