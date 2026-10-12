"""Regression of independently reproduced clock and terminal-capacity failures."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.domain import knowledge_decisions as decisions, knowledge_publication as service
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _hash, _plain
from app.domain.models import KnowledgePublicationEvent, KnowledgePublicationUnit
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_knowledge_publication import POLICY, IDS, activate, publish, preview, release, runtime
from tests.test_knowledge_decisions import data, read, sql, write


@pytest.mark.parametrize('delta', [-1, 0])
def test_new_review_must_be_strictly_after_last_publication(release, monkeypatch, delta):
    activate(release)
    before = preview(release)
    latest = datetime.fromisoformat(before['history'][0]['created_at'])
    monkeypatch.setattr(decisions, '_now', lambda: latest + timedelta(seconds=delta))
    with pytest.raises(EntryStorageInvalid, match='clock_before_history'):
        write(release, decision={**data(), 'verdict':'rejected', 'reason':'withdrawn', 'review_due_on':None},
              version=release['release'], key='late-clock')
    assert preview(release)['history'] == before['history']
    assert len(runtime(release)['available']) == 2
    publish(release, 'withdraw')
    assert runtime(release)['version_id'] is None


def test_review_retry_survives_clock_rollback_and_new_clock_is_checked(release, monkeypatch):
    original = read(release, version=release['release'])['selected']
    activate(release)
    monkeypatch.setattr(decisions, '_now', lambda: datetime(2026, 8, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(decisions.transactions, '_today', lambda: datetime(2026, 8, 1).date())
    assert write(release, version=release['release'], revision=0, key='official-'+IDS[0]) == original
    with pytest.raises(EntryStorageInvalid, match='clock_before_history'):
        write(release, version=release['release'], key='bad-clock')


def test_review_clock_before_previous_decision_without_publication(release, monkeypatch):
    previous = read(release, version=release['release'])['selected']
    monkeypatch.setattr(decisions, '_now', lambda: datetime.fromisoformat(previous['created_at'])-timedelta(seconds=1))
    with pytest.raises(EntryStorageInvalid, match='clock_before_history'):
        write(release, version=release['release'], key='earlier-review')


def test_publication_review_must_not_pin_a_future_decision(release, monkeypatch):
    previous = read(release, version=release['release'])['selected']
    monkeypatch.setattr(service, '_now', lambda: datetime.fromisoformat(previous['created_at'])-timedelta(seconds=1))
    with pytest.raises(EntryStorageInvalid, match='clock_before_review'):
        publish(release, 'review', key='future-manifest')
    assert preview(release)['current_revision'] == 0


def test_existing_full_history_has_one_terminal_withdrawal(release, monkeypatch):
    activate(release)
    monkeypatch.setattr(service, 'MAX_REVISIONS', 3)
    result = publish(release, 'withdraw', key='terminal')
    assert result['revision'] == 4 and runtime(release)['version_id'] is None
    assert publish(release, 'withdraw', revision=3, key='terminal') == result
    with pytest.raises(EntryStorageInvalid): publish(release, 'review', key='after-terminal')
    assert len(preview(release)['history']) == 4


def test_normal_commands_preserve_recovery_slot(release, monkeypatch):
    monkeypatch.setattr(service, 'MAX_REVISIONS', 4)
    activate(release)
    with pytest.raises(EntryStorageInvalid, match='history_limit'):
        publish(release, 'review', key='use-reserve')
    assert preview(release)['normal_capacity_available'] is False
    assert preview(release)['withdrawal_capacity_available'] is True
    assert publish(release, 'withdraw')['revision'] == 4


def journal_size(env):
    async def run():
        async with env['sm']() as session:
            rows = list((await session.scalars(select(KnowledgePublicationEvent).order_by(KnowledgePublicationEvent.revision))).all())
            return sum(len(service.canonical(service._payload(r)).encode()) for r in rows)
    return asyncio.run(run())


def test_legacy_byte_full_history_can_withdraw_once(release, monkeypatch):
    activate(release)
    monkeypatch.setattr(service, 'MAX_BYTES', journal_size(release))
    monkeypatch.setattr(service, 'MAX_EVENT_BYTES', 8192)
    before = preview(release)
    assert not before['normal_capacity_available']
    receipt = publish(release, 'withdraw', key='bytes-terminal')
    assert runtime(release)['version_id'] is None
    assert publish(release, 'withdraw', revision=3, key='bytes-terminal') == receipt
    with pytest.raises(EntryStorageInvalid, match='history_limit'):
        publish(release, 'review', key='after-byte-terminal')


def test_oversized_event_and_normal_bytes_leave_no_writes(release, monkeypatch):
    monkeypatch.setattr(service, 'MAX_EVENT_BYTES', 100)
    with pytest.raises(EntryStorageInvalid, match='history_limit'): publish(release, 'review')
    assert preview(release)['current_revision'] == 0
    monkeypatch.setattr(service, 'MAX_EVENT_BYTES', 4096)
    monkeypatch.setattr(service, 'MAX_BYTES', 4200)
    with pytest.raises(EntryStorageInvalid, match='history_limit'): publish(release, 'review')
    assert preview(release)['current_revision'] == 0


def full_legacy_history(env):
    """250 authentic-shaped source-bound events, with active publication at 250.

    Seed through real service; append immutable historical events in one synthetic
    setup transaction, each with its exact command, receipt and source FK rows.
    The production reader independently replays the entire 250-event history.
    """
    for key, action in enumerate(('review', 'review', 'approve', 'activate')):
        publish(env, action, key=f'initial-{key}')
    async def seed():
        async with env['sm']() as session, session.begin():
            last = await session.scalar(select(KnowledgePublicationEvent).order_by(KnowledgePublicationEvent.revision.desc()).limit(1))
            command = _plain(last.command)
            manifest = _plain(last.snapshot)
            original_stamp = service._utc(last.created_at)
            for revision in range(5, 251):
                action = 'withdraw' if revision % 2 else 'rollback'
                current = {**command, 'action':action, 'expected_revision':revision-1}
                row = KnowledgePublicationEvent(set_id=last.set_id, version_id=last.version_id,
                    revision=revision, previous_id=last.id, action=action, request_key=f'legacy-{revision}',
                    request_hash=_hash(current), command=current, snapshot=manifest,
                    created_by=last.created_by, created_at=original_stamp)
                row.snapshot_hash = _hash(service._payload(row))
                session.add(row); await session.flush()
                session.add_all(KnowledgePublicationUnit(event_id=row.id, version_id=row.version_id, **u) for u in manifest['units'])
                last = row
    asyncio.run(seed())


def test_real_250_event_history_withdraws_at_251(release):
    full_legacy_history(release)
    assert preview(release)['current_revision'] == 250
    assert len(runtime(release)['available']) == 2
    result = publish(release, 'withdraw', key='real-terminal')
    assert result['revision'] == 251
    assert runtime(release)['version_id'] is None
    assert publish(release, 'withdraw', revision=250, key='real-terminal') == result
    assert sql(release, 'SELECT count(*) FROM knowledge_publication_events')[0][0] == 251


def test_server_manifest_resolution_keeps_command_and_scope_pins(release):
    activate(release)
    before = preview(release)
    args = dict(actor=ADMIN, policy=POLICY, version_id=release['release'], action='withdraw',
        expected_revision=3, request_key='server-resolved', unit_ids=None, manifest_hash=before['manifest_hash'])
    receipt = asyncio.run(service.publish_knowledge(release['engine'], **args))
    for change in ({'manifest_hash':'f'*64}, {'expected_revision':2}, {'version_id':release['version']}):
        with pytest.raises(EntryStorageConflict):
            asyncio.run(service.publish_knowledge(release['engine'], **(args|change)))
    assert asyncio.run(service.publish_knowledge(release['engine'], **args)) == receipt
    with pytest.raises(EntryStorageInvalid):
        asyncio.run(service.publish_knowledge(None, **(args|{'action':'activate'})))
