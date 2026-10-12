import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, func

from app.domain import specialist_decisions as service, entry_quotes
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict
from app.domain.models import EntryApplicationEvent
from tests.test_specialist_decisions import (
    env, admins, clock, enforce_sqlite_foreign_keys, setup, record, quote_args, read,
)
from tests.test_specialist_quote_clock import counts


def test_quote_cannot_predate_decision_and_equal_boundary_recovers_same_request(env, tmp_path, monkeypatch):
    setup(env, tmp_path)
    decision = record(env)
    command = quote_args(env, decision)
    stamp = datetime.fromisoformat(decision['receipt']['created_at'])
    async def application_time():
        async with env['sm']() as session:
            return await session.scalar(select(func.max(EntryApplicationEvent.created_at)).where(
                EntryApplicationEvent.application_id == env['application']['id']))
    earlier = asyncio.run(application_time())
    earlier = earlier.replace(tzinfo=earlier.tzinfo or timezone.utc)
    quote_at = earlier + (stamp - earlier) / 2
    assert earlier < quote_at < stamp
    times = iter([stamp + timedelta(minutes=1), stamp + timedelta(minutes=2)])
    failure = None
    with monkeypatch.context() as patch:
        patch.setattr(service, '_now', lambda: next(times))
        patch.setattr(entry_quotes, '_now', lambda: quote_at)
        try:
            asyncio.run(service.record_decision(env['engine'], **command))
        except (EntryStorageInvalid, EntryStorageConflict) as exc:
            failure = exc
    if failure is None:
        assert counts(env) == (2, 1)
        with pytest.raises(EntryStorageInvalid):
            read(env)
        pytest.fail('A quote predating its specialist decision committed and poisoned later journal reads')
    assert counts(env) == (1, 0)
    # Equality is not reversal: both new timestamps may equal the decision time.
    with monkeypatch.context() as patch:
        patch.setattr(service, '_now', lambda: stamp)
        patch.setattr(entry_quotes, '_now', lambda: stamp)
        saved = asyncio.run(service.record_decision(env['engine'], **command))
    assert not saved['duplicate'] and counts(env) == (2, 1)
    assert read(env)['revision'] == 2
    replay = asyncio.run(service.record_decision(env['engine'], **(command | {
        'policy': None, 'interview_policy': None, 'publication_policy': None, 'quote_policy': None,
    })))
    assert replay['duplicate'] and replay['receipt'] == saved['receipt']
