import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, func

from app.domain import specialist_decisions as service, entry_quotes
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict
from app.domain.models import SpecialistDecisionEvent, EntryQuoteRevision
from tests.test_specialist_decisions import (
    env, admins, clock, enforce_sqlite_foreign_keys, setup, record, quote_args, read,
)


def counts(env):
    async def run():
        async with env['sm']() as session:
            return tuple([await session.scalar(select(func.count()).select_from(model))
                          for model in (SpecialistDecisionEvent, EntryQuoteRevision)])
    return asyncio.run(run())


def test_quote_to_link_clock_reversal_rolls_back_both_and_original_request_recovers(env, tmp_path, monkeypatch):
    setup(env, tmp_path)
    decision = record(env)
    command = quote_args(env, decision)
    assert counts(env) == (1, 0)
    base = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
    samples = iter([base + timedelta(minutes=1), base + timedelta(minutes=2)])
    failure = None
    with monkeypatch.context() as patch:
        patch.setattr(service, '_now', lambda: next(samples))
        patch.setattr(entry_quotes, '_now', lambda: base + timedelta(minutes=3))
        try:
            asyncio.run(service.record_decision(env['engine'], **command))
        except (EntryStorageInvalid, EntryStorageConflict) as exc:
            failure = exc
    if failure is None:
        # The admitted write has already committed a link predating its quote.
        assert counts(env) == (2, 1)
        with pytest.raises(EntryStorageInvalid):
            read(env)
        pytest.fail('Quote/link clock reversal committed both rows and made the specialist journal unreadable')
    assert counts(env) == (1, 0)
    saved = asyncio.run(service.record_decision(env['engine'], **command))
    assert not saved['duplicate'] and counts(env) == (2, 1)
    assert read(env)['revision'] == 2
    retry = asyncio.run(service.record_decision(env['engine'], **(command | {
        'policy': None, 'interview_policy': None, 'publication_policy': None, 'quote_policy': None,
    })))
    assert retry['duplicate'] and retry['receipt'] == saved['receipt'] and counts(env) == (2, 1)
