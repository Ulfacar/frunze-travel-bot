"""Real 4 MiB boundary populated through the archived valid R9 writer."""
import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from app.config import settings, ManagerConfig
from app.domain import specialist_decisions as current
from app.domain.entry_storage import EntryStorageInvalid, _hash
from app.knowledge.review import canonical
from tests import archived_specialist_r9 as old
from tests.test_specialist_reserves import prepare, withdrawal
from tests.test_specialist_decisions import env, admins, clock
from tests.test_entry_applications import enforce_sqlite_foreign_keys


def test_real_byte_reserve_archived_rows_upgrade_and_exact_retry(env, monkeypatch):
    assert current.MAX_BYTES == old.MAX_BYTES == 4194304
    assert current.WITHDRAWAL_BYTES == old.WITHDRAWAL_BYTES == 8192
    monkeypatch.setattr(old, '_now', current._now)
    originals = list(settings.managers)

    def registry(count, last_length=64):
        additions = [ManagerConfig(login='m'+str(i).zfill(5)+'x'*(64-6),
            name='Synthetic admin', password='synthetic', admin=True) for i in range(count)]
        if count and last_length != 64:
            additions[-1].login = 'm'+str(count-1).zfill(5)+'x'*(last_length-6)
        monkeypatch.setattr(settings, 'managers', originals+additions)

    registry(1400)
    args, operation = prepare(env)
    budget = current.MAX_BYTES-current.WITHDRAWAL_BYTES
    history = []
    commands = []

    def next_command(revision, key):
        return dict(**args, expected_revision=revision, request_key=key, operation=operation)

    def estimated(last, revision, key):
        payload = {k:deepcopy(v) for k,v in last.items() if k not in ('id','snapshot_hash')}
        payload['revision'] = revision+1
        payload['previous_id'] = last['id']
        payload['command']['expected_revision'] = revision
        payload['request_key'] = key
        payload['request_hash'] = _hash(payload['command'])
        payload['provenance']['previous'] = dict(id=last['id'],hash=last['snapshot_hash'])
        payload['provenance']['authority']['full_admins'] = sorted(old.existing_full_admins())
        return len(canonical(payload).encode())

    async def run():
        total = 0
        while True:
            revision = len(history)
            key = 'SYN-BYTE-'+str(revision)
            if history:
                size = estimated(history[-1], revision, key)
                if budget-total < size*2:
                    break
            request = next_command(revision, key)
            answer = await old.record_decision(env['engine'], **request)
            receipt = answer['receipt']
            actual_size = len(canonical({k:v for k,v in receipt.items() if k not in ('id','snapshot_hash')}).encode())
            if history:
                assert actual_size == size
            total += actual_size
            history.append(receipt)
            commands.append(request)
            assert len(history)<63

        # Set the final archived membership list to fill the exact ordinary byte
        # allowance. The configuration is real, bounded, canonical fixture data.
        revision = len(history)
        key = 'SYN-BYTE-FINAL'
        target = budget-total
        registry(0)
        base_size = estimated(history[-1], revision, key)
        spare = target-base_size
        assert spare > 1000
        count = spare//67
        remainder = spare%67
        if remainder and remainder < 9:
            count -= 1
            remainder += 67
        if remainder:
            count += 1
        registry(count)
        # A second shortened name handles the tiny unrepresentable remainder.
        overshoot = estimated(history[-1], revision, key)-target
        if overshoot:
            additions = list(settings.managers[len(originals):])
            for index in (-1,-2):
                shorten = min(58, overshoot)
                additions[index].login = additions[index].login[:-shorten] if shorten else additions[index].login
                overshoot -= shorten
                if not overshoot:break
            monkeypatch.setattr(settings, 'managers', originals+additions)
        assert estimated(history[-1], revision, key) == target
        request = next_command(revision,key)
        final = await old.record_decision(env['engine'], **request)
        last = final['receipt']
        total += len(canonical({k:v for k,v in last.items() if k not in ('id','snapshot_hash')}).encode())
        assert total == budget and last['revision']<63
        history.append(last)
        commands.append(request)
        # Upgrade to current code; old membership receipts remain exact, while
        # any new ordinary append is refused and the real reserved terminal fits.
        registry(0)
        view = await current.read_decisions(env['engine'], **args)
        assert view['history'] == list(reversed(history))
        assert not view['can_record'] and view['can_withdraw']
        with pytest.raises(EntryStorageInvalid,match='specialist_history_limit'):
            await current.record_decision(env['engine'], **next_command(len(history),'SYN-BYTE-OVER'))
        terminal_command = withdrawal(args,last,len(history))
        terminal = await current.record_decision(env['engine'], **terminal_command)
        terminal_size = len(canonical({k:v for k,v in terminal['receipt'].items() if k not in ('id','snapshot_hash')}).encode())
        assert terminal_size <= current.WITHDRAWAL_BYTES
        assert total+terminal_size <= current.MAX_BYTES
        again = await current.record_decision(env['engine'], **terminal_command)
        assert again['duplicate'] and again['receipt']==terminal['receipt']
        retry = {k:v for k,v in commands[-1].items() if k not in ('policy','interview_policy','publication_policy')}
        old_again = await current.record_decision(env['engine'], **retry)
        assert old_again['duplicate'] and old_again['receipt']==last
        print(dict(ordinary_records=len(history), ordinary_bytes=total,
            withdrawal_bytes=terminal_size, total_bytes=total+terminal_size))
    asyncio.run(run())
