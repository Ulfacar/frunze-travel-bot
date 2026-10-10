import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import shutil

import pytest
import yaml

from app.domain import knowledge_publication as publication
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.knowledge_publication_rules import PublicationPolicy, configured_policy
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, FIX, env
from tests.test_knowledge_decisions import data, sql, write as review

POLICY = PublicationPolicy('SYNTHETIC-DEC-07', 'a'*64, ('admin',))
IDS = ['KG.DL.TEST', 'KG.VF.TEST']


def load_source(env, tmp_path, *, changes=None, tag='release'):
    from app.domain.knowledge_import import create_kg_entry_set, import_bundle
    folder = tmp_path / tag
    shutil.copytree(FIX/'synthetic_bundle', folder)
    units = yaml.safe_load((folder/'units.yaml').read_text('utf-8'))
    for unit in units:
        if unit['unit_id'] in IDS:
            unit.update(effective_from='2026-01-01', verified_at='2026-09-01T00:00:00Z',
                verified_by='synthetic-reviewer', review_due_at='2026-12-01T00:00:00Z', owner='synthetic-owner',
                source_ref='Synthetic official-source test evidence '+tag)
            if changes and unit['unit_id'] in changes:
                unit.update(changes[unit['unit_id']])
    (folder/'units.yaml').write_text(yaml.safe_dump(units, allow_unicode=True), 'utf-8')
    async def load():
        set_id = await create_kg_entry_set(env['engine'], actor=ADMIN)
        return await import_bundle(env['engine'], actor=ADMIN, set_id=set_id, directory=folder, source=FIX/'synthetic_source.txt')
    imported = asyncio.run(load()); assert imported.accepted, imported.report
    for identifier in IDS:
        review(env, unit=identifier, version=imported.version_id, key='official-'+identifier)
    return imported.version_id


@pytest.fixture
def release(env, tmp_path):
    env['release'] = load_source(env, tmp_path)
    return env


def preview(env, *, version=None, ids=IDS):
    return asyncio.run(publication.publication_preview(env['engine'], actor=ADMIN,
        version_id=version or env['release'], unit_ids=ids))


def publish(env, action, *, version=None, ids=IDS, revision=None, key=None, manifest=None, policy=POLICY):
    version = version or env['release']
    current = preview(env, version=version, ids=ids)
    if revision is None: revision = current['current_revision']
    return asyncio.run(publication.publish_knowledge(env['engine'], actor=ADMIN, policy=policy,
        version_id=version, action=action, expected_revision=revision, request_key=key or f'{action}-{revision}',
        unit_ids=ids, manifest_hash=manifest or current['manifest_hash']))


def runtime(env, ids=IDS, *, policy=POLICY):
    return asyncio.run(publication.runtime_knowledge(env['engine'], actor=ADMIN, policy=policy, unit_ids=ids))


def activate(env, *, version=None):
    for action in ('review', 'approve', 'activate'):
        publish(env, action, version=version)


def test_explicit_review_approval_active_subset_and_withdrawal(release):
    before = sql(release, 'SELECT bundle_hash,source_hash FROM knowledge_versions ORDER BY id')
    assert runtime(release)['unavailable'][0]['reasons'] == ['no_active_publication']
    with pytest.raises(EntryStorageConflict): publish(release, 'activate')
    assert preview(release)['current_revision'] == 0
    activate(release)
    result = runtime(release, IDS+['KG.REG.DEFAULT'])
    assert {r['unit_id'] for r in result['available']} == set(IDS)
    assert result['unavailable'] == [dict(unit_id='KG.REG.DEFAULT', reasons=['unit_not_published'])]
    assert result['available'][0]['value']['value'] == 3
    assert preview(release)['version']['status'] == 'active'
    assert before == sql(release, 'SELECT bundle_hash,source_hash FROM knowledge_versions ORDER BY id')
    with pytest.raises(EntryStorageConflict): publish(release, 'review')
    publish(release, 'withdraw')
    assert runtime(release)['version_id'] is None
    assert len(preview(release)['history']) == 4


def test_atomic_version_switch_rollback_and_old_source_preserved(release, tmp_path):
    first = release['release']; activate(release)
    second = load_source(release, tmp_path, tag='second')
    activate(release, version=second)
    assert runtime(release)['version_id'] == second
    assert preview(release, version=first)['version']['status'] == 'retired'
    publish(release, 'rollback', version=first)
    assert runtime(release)['version_id'] == first
    assert sql(release, "SELECT count(*) FROM knowledge_versions WHERE status='active'")[0][0] == 1
    assert preview(release, version=second)['version']['status'] == 'retired'


@pytest.mark.parametrize('actor,policy', [(ADMIN,None), (Actor('other',True),POLICY), (Actor('admin'),POLICY),
    (None,POLICY), (Actor('system',True),POLICY)])
def test_publication_authority_before_storage(actor, policy):
    with pytest.raises(PermissionDenied):
        asyncio.run(publication.publish_knowledge(None, actor=actor, policy=policy, version_id=1, action='activate',
            expected_revision=0, request_key='request', unit_ids=IDS, manifest_hash='a'*64))


def test_policy_defaults_and_revocation(release):
    from app.config import Settings
    assert configured_policy(Settings(_env_file=None)) is None
    activate(release)
    assert not runtime(release, policy=None)['available']
    assert not runtime(release, policy=replace(POLICY, fingerprint='b'*64))['available']
    assert runtime(release)['available']


def test_changed_review_blocks_only_one_unit_and_expiry_is_per_rule(release, monkeypatch):
    activate(release)
    pinned = preview(release)['manifest_hash']
    review(release, {**data(), 'verdict':'rejected', 'reason':'source_conflict', 'review_due_on':None},
           unit=IDS[0], version=release['release'], key='reject')
    result = runtime(release)
    assert [r['unit_id'] for r in result['available']] == [IDS[1]]
    assert 'review_changed_since_approval' in result['unavailable'][0]['reasons']
    # Withdrawal still works when review evidence has since changed.
    publish(release, 'withdraw', manifest=pinned)
    assert runtime(release)['version_id'] is None


@pytest.mark.parametrize('changes,reason', [
    ({'effective_from':'2027-01-01'}, 'not_yet_effective'),
    ({'effective_from':None}, 'effective_date_unknown'),
    ({'review_due_at':'2026-09-01T00:00:00Z'}, 'source_review_expired'),
    ({'owner':'UNASSIGNED'}, 'source_owner_unknown'),
    ({'label':'practice'}, 'source_label_requires_specialist')])
def test_unavailable_rules_can_be_reviewed_but_never_approved(env, tmp_path, changes, reason):
    env['release'] = load_source(env, tmp_path, changes={IDS[0]:changes})
    assert reason in preview(env)['availability'][0]['reasons']
    publish(env, 'review')
    with pytest.raises(EntryStorageInvalid, match='rules_unavailable'): publish(env, 'approve')
    assert preview(env)['version']['status'] == 'review'


def test_missing_metadata_and_technical_review_do_not_promote_source(env):
    env['release'] = env['version']
    review(env, {**data(), 'evidence_kind':'technical_check'}, unit=IDS[0])
    result = preview(env, ids=[IDS[0]])
    assert 'official_source_review_required' in result['availability'][0]['reasons']
    assert 'effective_date_unknown' in result['availability'][0]['reasons']
    publish(env, 'review', ids=[IDS[0]])
    with pytest.raises(EntryStorageInvalid): publish(env, 'approve', ids=[IDS[0]])


def test_retry_cas_manifest_and_policy_changes(release):
    before = preview(release); first = publish(release, 'review', key='same')
    publish(release, 'approve')
    assert publish(release, 'review', revision=0, key='same', manifest=before['manifest_hash']) == first
    with pytest.raises(EntryStorageConflict): publish(release, 'activate', revision=0, key='same')
    with pytest.raises(EntryStorageConflict): publish(release, 'activate', revision=0)
    with pytest.raises(EntryStorageConflict): publish(release, 'activate', policy=replace(POLICY, fingerprint='b'*64))
    review(release, {**data(), 'proof':'b'*64}, unit=IDS[0], version=release['release'], key='new-evidence')
    with pytest.raises(EntryStorageConflict): publish(release, 'activate', manifest=before['manifest_hash'])
    with pytest.raises(EntryStorageConflict): publish(release, 'activate')
    assert preview(release)['version']['status'] == 'approved'


def test_expiry_boundary_does_not_rewrite_history(release, monkeypatch):
    activate(release)
    monkeypatch.setattr(publication, '_now', lambda:datetime(2026,12,1,tzinfo=timezone.utc))
    result = runtime(release)
    assert not result['available']
    assert all('source_review_expired' in r['reasons'] for r in result['unavailable'])
    assert len(preview(release)['history']) == 3
    publish(release, 'withdraw')


def test_corrupt_projection_or_link_refuses_runtime(release):
    activate(release)
    sql(release, "UPDATE knowledge_publication_units SET unit_hash=:hash WHERE unit_id=:unit", hash='0'*64, unit=IDS[0])
    with pytest.raises(EntryStorageInvalid, match='integrity_failed'): runtime(release)


def test_unaudited_active_pointer_is_not_trusted(release):
    sql(release, "UPDATE knowledge_versions SET status='active' WHERE id=:id", id=release['release'])
    sql(release, 'UPDATE knowledge_sets SET active_version_id=:id', id=release['release'])
    with pytest.raises(EntryStorageInvalid, match='projection_integrity'): runtime(release)


def test_lost_acknowledgement_is_exact_retry(release, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSessionTransaction
    before = preview(release)
    args = dict(actor=ADMIN, policy=POLICY, version_id=release['release'], action='review', expected_revision=0,
                request_key='lost', unit_ids=IDS, manifest_hash=before['manifest_hash'])
    original = AsyncSessionTransaction.__aexit__; once = True
    async def lost(self, *args):
        nonlocal once
        result = await original(self, *args)
        if once: once=False; raise RuntimeError('synthetic lost acknowledgement')
        return result
    monkeypatch.setattr(AsyncSessionTransaction, '__aexit__', lost)
    with pytest.raises(EntryStorageUnavailable): asyncio.run(publication.publish_knowledge(release['engine'], **args))
    assert asyncio.run(publication.publish_knowledge(release['engine'], **args))['revision'] == 1
    assert preview(release)['current_revision'] == 1


def test_concurrent_identical_requests_have_one_receipt(release):
    current = preview(release)
    args = dict(actor=ADMIN, policy=POLICY, version_id=release['release'], action='review', expected_revision=0,
                request_key='race', unit_ids=IDS, manifest_hash=current['manifest_hash'])
    async def race():
        return await asyncio.gather(*(publication.publish_knowledge(release['engine'], **args) for _ in range(2)), return_exceptions=True)
    result = asyncio.run(race())
    assert any(isinstance(r, dict) for r in result)
    assert all(isinstance(r, (dict, EntryStorageConflict)) for r in result), result
    assert preview(release)['current_revision'] == 1


def test_failure_before_commit_rolls_back_pointer_status_and_audit(release, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession
    publish(release, 'review'); publish(release, 'approve')
    current = preview(release); original = AsyncSession.execute
    async def broken(self, statement, *args, **kwargs):
        if getattr(getattr(statement, 'table', None), 'name', None) == 'knowledge_sets' and statement.is_update:
            raise RuntimeError('synthetic failure before pointer update')
        return await original(self, statement, *args, **kwargs)
    monkeypatch.setattr(AsyncSession, 'execute', broken)
    with pytest.raises(EntryStorageUnavailable): publish(release, 'activate', key='atomic')
    monkeypatch.setattr(AsyncSession, 'execute', original)
    after = preview(release)
    assert after['version']['status'] == 'approved' and after['active_version_id'] is None
    assert after['current_revision'] == current['current_revision']
    publish(release, 'activate', key='atomic')
    assert runtime(release)['version_id'] == release['release']


def test_ordinary_orm_cannot_edit_source_or_publication_audit(release):
    from sqlalchemy import update
    from app.domain.models import DomainError, KnowledgeVersion, KnowledgePublicationEvent
    row = publish(release, 'review')
    async def change():
        async with release['sm']() as session:
            source = await session.get(KnowledgeVersion, release['release']); source.status = 'active'
            with pytest.raises(DomainError): await session.flush()
            await session.rollback()
            audit = await session.get(KnowledgePublicationEvent, row['id']); audit.action = 'activate'
            with pytest.raises(DomainError): await session.flush()
            await session.rollback()
            with pytest.raises(DomainError): await session.execute(update(KnowledgePublicationEvent).values(action='activate'))
    asyncio.run(change())
    assert preview(release)['version']['status'] == 'review'


def test_one_expired_rule_leaves_the_other_available(env, tmp_path, monkeypatch):
    env['release'] = load_source(env, tmp_path, changes={IDS[0]:{'review_due_at':'2026-11-01T00:00:00Z'}})
    activate(env)
    monkeypatch.setattr(publication, '_now', lambda:datetime(2026,11,1,tzinfo=timezone.utc))
    result = runtime(env)
    assert [r['unit_id'] for r in result['available']] == [IDS[1]]
    assert result['unavailable'][0]['reasons'] == ['source_review_expired']


def test_rollback_requires_current_evidence(release, tmp_path):
    first = release['release']; activate(release)
    second = load_source(release, tmp_path, tag='second'); activate(release, version=second)
    review(release, {**data(), 'verdict':'rejected', 'reason':'withdrawn', 'review_due_on':None},
           unit=IDS[0], version=first, key='withdraw-evidence')
    with pytest.raises(EntryStorageInvalid): publish(release, 'rollback', version=first)
    assert runtime(release)['version_id'] == second


def test_bounded_history_and_malformed_ids_fail_closed(release, monkeypatch):
    publish(release, 'review')
    monkeypatch.setattr(publication, 'MAX_BYTES', 1)
    with pytest.raises(EntryStorageInvalid, match='history_limit'): runtime(release)
    for value in ([], [IDS[0],IDS[0]], [{}], ['bad'], IDS*51):
        with pytest.raises(EntryStorageInvalid): runtime(release, value)


def test_new_version_preview_includes_old_cases_and_preserves_calculation_replay(release, tmp_path):
    from app.domain.entry_calculations import save_calculation, replay_calculation
    from app.domain.entry_storage import import_work_calendars
    from app.knowledge.validation import load_document
    from tests.test_entry_storage import calendars
    first = release['release']
    async def calculate():
        calendar = await import_work_calendars(release['engine'], actor=ADMIN, document=calendars())
        return await save_calculation(release['engine'], actor=ADMIN, contact_id=release['contacts']['visa'],
            kind='deadline', knowledge_version_id=first, request_key='pinned-before-publication',
            request=load_document(FIX/'synthetic_deadline_review.json'), calendar_ids=[c['calendar_id'] for c in calendar])
    saved = asyncio.run(calculate())
    cases_before = sql(release, 'SELECT id,agreed_amount,currency,revision FROM service_cases ORDER BY id')
    activate(release)
    second = load_source(release, tmp_path, tag='second')
    candidate = preview(release, version=second)
    assert release['cases']['visa'] in candidate['affected_case_ids']
    assert candidate['diff']['summary']['changed'] == 2
    activate(release, version=second)
    replay = asyncio.run(replay_calculation(release['engine'], actor=ADMIN, contact_id=release['contacts']['visa'],
                                          calculation_id=saved['calculation_id']))
    assert replay['replay_verified'] and replay['result'] == saved['result']
    assert cases_before == sql(release, 'SELECT id,agreed_amount,currency,revision FROM service_cases ORDER BY id')


def test_publication_uses_one_instant_when_source_expires_during_transaction(env, tmp_path, monkeypatch):
    env['release'] = load_source(env, tmp_path, changes={IDS[0]:{'review_due_at':'2026-11-01T00:00:00Z'}})
    publish(env, 'review'); publish(env, 'approve'); current = preview(env)
    stamps = [datetime(2026,10,31,23,59,59,999999,tzinfo=timezone.utc), datetime(2026,11,1,tzinfo=timezone.utc)]
    def advancing():
        return stamps.pop(0) if len(stamps)>1 else stamps[0]
    monkeypatch.setattr(publication, '_now', advancing)
    row = asyncio.run(publication.publish_knowledge(env['engine'], actor=ADMIN, policy=POLICY, version_id=env['release'],
        action='activate', expected_revision=2, request_key='boundary', unit_ids=IDS, manifest_hash=current['manifest_hash']))
    assert row['created_at'].startswith('2026-10-31T23:59:59.999999')
    # Journal remains valid at its recorded instant; current read expires only the affected rule.
    result = runtime(env)
    assert len(result['available']) == 1 and result['unavailable'][0]['reasons'] == ['source_review_expired']


def test_clock_rollback_does_not_commit_invalid_journal(release, monkeypatch):
    publish(release, 'review')
    monkeypatch.setattr(publication, '_now', lambda:datetime(2026,9,1,tzinfo=timezone.utc))
    with pytest.raises(EntryStorageInvalid, match='clock_before_history'): publish(release, 'review', key='clock-rollback')
    assert preview(release)['current_revision'] == 1
