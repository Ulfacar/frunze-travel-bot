"""Real synthetic transactions: receipts never imply verified portal decisions."""
import asyncio
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import Session

from app.domain import entry_portal as service
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.models import DomainBase, EntryApplicationEvent, EntryPortalAction, EntryPortalReceipt, DomainError
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import person, application, record, read as read_application, enforce_sqlite_foreign_keys
from tests.test_entry_portal_parser import policy, message


def setup(env, reference='AB12CD34', key='first', case='visa'):
    app = application(env, person(env, key=key+'-person', case=case), key=key+'-app', case=case)
    record(env, app, case=case, reference=reference, occurred_on='2026-10-10')
    return app


def receive_args(env, **changes):
    allowed = changes.pop('policy', policy())
    return dict(actor=ADMIN, case_id=env['cases']['visa'], channel='paste', source_namespace='SYN-PORTAL',
        transport_id='SYN-MESSAGE-1', archive_reference='SYN-ARCHIVE-1', archive_proof='d'*64,
        request_key='receipt-1', expected_policy_hash=allowed.digest if allowed else policy().digest,
        policy=allowed, text=message()) | changes


def receive(env, **changes): return asyncio.run(service.receive(env['engine'], **receive_args(env, **changes)))


def read(env, receipt, **changes):
    return asyncio.run(service.read_receipt(env['engine'], actor=ADMIN, case_id=env['cases']['visa'],
        receipt_id=receipt['id'], policy=policy(), **changes))


def action_args(env, receipt, action, **changes):
    current = read(env, receipt)
    operation = {'action': action, 'confirmed': True}
    if action == 'correlate': operation['binding'] = current['candidate']
    if action == 'dismiss': operation['reason'] = 'unclear'
    if action == 'confirm': operation.update(on='2026-10-10', source='portal', verification_reference='SYN-PORTAL-CHECK',
        verification_proof='e'*64, cycle_verified=True)
    operation.update(changes.pop('operation_changes', {}))
    return dict(actor=ADMIN, case_id=env['cases']['visa'], receipt_id=receipt['id'],
        expected_revision=current['revision'], request_key=action+'-'+str(current['revision']),
        operation=operation, policy=policy(), expected_policy_hash=policy().digest) | changes


def action(env, receipt, name, **changes):
    return asyncio.run(service.record_action(env['engine'], **action_args(env, receipt, name, **changes)))


def counts(env):
    async def run():
        async with env['sm']() as session:
            return {table.name: await session.scalar(select(func.count()).select_from(table)) for table in DomainBase.metadata.sorted_tables}
    return asyncio.run(run())


@pytest.mark.parametrize('kind', ['verification', 'payment', 'correction', 'approval', 'refusal'])
def test_five_receipts_do_not_change_fact_until_separate_verified_confirmation(env, kind):
    app = setup(env); before = counts(env)
    receipt = receive(env, text=message(kind))
    after = counts(env)
    assert {k: v for k, v in after.items() if k != 'entry_portal_receipts'} == {k: v for k, v in before.items() if k != 'entry_portal_receipts'}
    assert after['entry_portal_receipts'] == before['entry_portal_receipts'] + 1
    action(env, receipt, 'correlate')
    args = action_args(env, receipt, 'confirm')
    result = asyncio.run(service.record_action(env['engine'], **args))
    assert asyncio.run(service.record_action(env['engine'], **(args | {'policy': None}))) == result
    assert read(env, receipt)['state'] == result['state']
    expected = service.APPLY.get(kind, 'submitted')
    assert read_application(env, app)['current']['status'] == expected
    assert result['state']['disposition'] == ('applied' if kind in service.APPLY else 'checked')
    assert counts(env)['service_payments'] == before['service_payments']
    assert counts(env)['entry_process_events'] == before['entry_process_events']


def test_manual_fallback_requires_its_own_channel_authority_and_same_confirmation(env):
    setup(env); allowed = policy(allow_paste=False, manual_sources=('portal',))
    with pytest.raises(PermissionDenied): receive(env, policy=allowed)
    args = receive_args(env, policy=allowed, channel='portal', text=None,
                        manual={'reference':'AB12CD34', 'kind':'approval', 'occurred_on':'2026-10-10'})
    with pytest.raises(PermissionDenied): asyncio.run(service.receive(env['engine'], **(args | {'policy':None})))
    receipt = asyncio.run(service.receive(env['engine'], **args))
    action(env, receipt, 'correlate', policy=allowed, expected_policy_hash=allowed.digest)
    assert action(env, receipt, 'confirm', policy=allowed, expected_policy_hash=allowed.digest)['state']['disposition'] == 'applied'


def test_transport_dedup_conflict_and_exact_retry_after_policy_loss(env):
    args = receive_args(env); first = asyncio.run(service.receive(env['engine'], **args))
    assert asyncio.run(service.receive(env['engine'], **(args | {'policy':None}))) == first
    assert receive(env, request_key='different-form-key')['id'] == first['id']
    with pytest.raises(EntryStorageConflict): receive(env, text=message('refusal'))
    with pytest.raises(EntryStorageConflict): receive(env, case_id=env['cases']['other'], request_key='other-case')
    assert counts(env)['entry_portal_receipts'] == 1


def test_unclaimed_reference_can_later_bind_but_never_selects_a_foreign_case(env):
    receipt = receive(env)
    assert read(env, receipt)['candidate'] is None
    app = setup(env)
    candidate = read(env, receipt)['candidate']
    assert candidate['application_id'] == app['id']
    other = setup(env, key='other', case='other', reference='XY98ZT76')
    foreign = receive(env, text=message(reference='XY98ZT76'), transport_id='foreign', request_key='foreign')
    assert read(env, foreign)['candidate'] is None
    with pytest.raises((EntryStorageConflict, EntryStorageInvalid)):
        action(env, foreign, 'correlate', operation_changes={'binding': candidate | {'application_id':other['id']}})


@pytest.mark.parametrize('change', [
    {'confirmed':False}, {'cycle_verified':False}, {'source':'email'}, {'verification_proof':'broken'},
    {'on':'2026-10-09'}, {'on':'2099-01-01'}, {'on':'2026-10-11'},
])
def test_confirmation_is_explicit_and_chronological(env, change):
    app = setup(env); receipt = receive(env); action(env, receipt, 'correlate'); before = counts(env)
    with pytest.raises((EntryStorageInvalid, PermissionDenied)):
        action(env, receipt, 'confirm', operation_changes=change)
    assert counts(env) == before and read_application(env, app)['current']['status'] == 'submitted'


def test_receipt_hash_is_not_independent_verification_proof(env):
    setup(env); receipt = receive(env); action(env, receipt, 'correlate')
    with pytest.raises(EntryStorageInvalid, match='independent'):
        action(env, receipt, 'confirm', operation_changes={'verification_proof':receipt['raw_sha256']})


def test_old_cycle_late_correction_and_same_day_resubmit_need_new_verified_binding(env):
    app = setup(env); receipt = receive(env, text=message('correction')); action(env, receipt, 'correlate')
    args = action_args(env, receipt, 'confirm')
    record(env, app, key='manual-return', status='revision_requested', occurred_on='2026-10-10')
    record(env, app, key='manual-resubmit', status='submitted', occurred_on='2026-10-10')
    assert not read(env, receipt)['can_confirm']
    with pytest.raises(EntryStorageConflict, match='application_changed'):
        asyncio.run(service.record_action(env['engine'], **args))
    action(env, receipt, 'correlate', request_key='explicit-new-cycle')
    with pytest.raises(EntryStorageInvalid): action(env, receipt, 'confirm', operation_changes={'cycle_verified':False})
    action(env, receipt, 'confirm')
    assert read_application(env, app)['current']['status'] == 'revision_requested'


def test_exact_content_new_transport_cannot_apply_twice_after_a_new_cycle(env):
    app = setup(env); first = receive(env, text=message('correction')); action(env, first, 'correlate')
    applied = action(env, first, 'confirm')
    record(env, app, key='resubmit', status='submitted', occurred_on='2026-10-10')
    assert read(env, first)['state'] == applied['state']
    duplicate = receive(env, text=message('correction'), transport_id='new-message-id', request_key='new-receipt')
    action(env, duplicate, 'correlate')
    with pytest.raises(EntryStorageConflict, match='already_applied'): action(env, duplicate, 'confirm')
    assert read_application(env, app)['current']['status'] == 'submitted'
    assert action(env, duplicate, 'dismiss', operation_changes={'reason':'duplicate'})['state']['disposition'] == 'dismissed'


def test_distinct_manual_source_evidence_can_confirm_new_same_day_cycle(env):
    app = setup(env)
    values = dict(channel='portal', text=None, manual={'reference':'AB12CD34','kind':'correction','occurred_on':'2026-10-10'})
    first = receive(env, **values); action(env, first, 'correlate'); action(env, first, 'confirm')
    record(env, app, key='same-day-resubmit', status='submitted', occurred_on='2026-10-10')
    repeated = receive(env, **values, request_key='old-proof', transport_id='other-transport')
    action(env, repeated, 'correlate')
    with pytest.raises(EntryStorageConflict, match='already_applied'): action(env, repeated, 'confirm')
    renamed = receive(env, **values, request_key='renamed-proof', transport_id='renamed-transport', archive_reference='SYN-RENAMED')
    action(env, renamed, 'correlate')
    with pytest.raises(EntryStorageConflict, match='already_applied'): action(env, renamed, 'confirm')
    fresh = receive(env, **values, request_key='new-proof', transport_id='new-manual-check',
                    archive_reference='SYN-NEW-CYCLE', archive_proof='f'*64)
    assert fresh['raw_sha256'] != first['raw_sha256']
    action(env, fresh, 'correlate')
    result = action(env, fresh, 'confirm', operation_changes={'verification_reference':'SYN-NEW-CHECK','verification_proof':'1'*64})
    assert result['state']['binding']['cycle_id'] != read(env, first)['state']['binding']['cycle_id']
    assert read_application(env, app)['current']['revision'] == 5


@pytest.mark.parametrize('at', ['application', 'action'])
def test_fault_after_either_half_flush_rolls_back_entire_confirmation(env, at):
    setup(env); receipt = receive(env); action(env, receipt, 'correlate'); before = counts(env)
    model = EntryApplicationEvent if at == 'application' else EntryPortalAction
    def fail(session, context):
        if any(isinstance(v, model) for v in session.new): raise RuntimeError('synthetic flush fault')
    event.listen(Session, 'after_flush', fail)
    try:
        with pytest.raises(EntryStorageUnavailable): action(env, receipt, 'confirm')
    finally: event.remove(Session, 'after_flush', fail)
    assert counts(env) == before
    assert action(env, receipt, 'confirm')['state']['disposition'] == 'applied'


def test_corrupt_pinned_event_fails_even_when_receipt_hash_is_unchanged(env):
    setup(env); receipt = receive(env); action(env, receipt, 'correlate'); saved = action(env, receipt, 'confirm')
    async def corrupt():
        async with env['engine'].begin() as conn:
            await conn.execute(text("UPDATE entry_application_events SET snapshot_hash=:bad WHERE id=:id"),
                {'bad':'0'*64,'id':saved['state']['applied_event']['id']})
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid): read(env, receipt)


def test_receipt_and_action_orm_bulk_mutation_guards(env):
    receipt = receive(env); action(env, receipt, 'dismiss')
    async def run():
        for model in (EntryPortalReceipt, EntryPortalAction):
            async with env['sm']() as session:
                row = await session.scalar(select(model))
                row.created_by = 'changed'
                with pytest.raises(DomainError): await session.flush()
            async with env['sm']() as session:
                with pytest.raises(DomainError): await session.execute(update(model).values(created_by='changed'))
    asyncio.run(run())


def test_reserved_final_disposition_survives_limit_and_policy_expiry(env):
    setup(env); receipt = receive(env)
    for i in range(63): action(env, receipt, 'correlate', request_key=f'correlate-{i}')
    with pytest.raises(EntryStorageInvalid, match='limit'): action(env, receipt, 'correlate')
    result = action(env, receipt, 'dismiss', policy=None, expected_policy_hash=None)
    assert result['revision'] == 64 and read(env, receipt)['state']['disposition'] == 'dismissed'


def test_concurrent_identical_confirmation_keeps_one_fact(env):
    app = setup(env); receipt = receive(env); action(env, receipt, 'correlate'); args = action_args(env, receipt, 'confirm')
    def worker(): return asyncio.run(service.record_action(env['engine'], **args))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [f.result(timeout=30) for f in futures]
    assert results[0] == results[1]
    assert read_application(env, app)['current']['revision'] == 3


@pytest.mark.parametrize('at',['before_commit','after_commit'])
def test_commit_fault_exact_retry_recovers_one_fact(env,at):
    app=setup(env);receipt=receive(env);action(env,receipt,'correlate');args=action_args(env,receipt,'confirm')
    def fault(session):raise RuntimeError('synthetic commit fault')
    event.listen(Session,at,fault)
    try:
        with pytest.raises(EntryStorageUnavailable):asyncio.run(service.record_action(env['engine'],**args))
    finally:event.remove(Session,at,fault)
    assert read_application(env,app)['current']['status']==('approved' if at=='after_commit' else 'submitted')
    first=asyncio.run(service.record_action(env['engine'],**args))
    assert asyncio.run(service.record_action(env['engine'],**(args|{'policy':None})))==first
    assert read_application(env,app)['current']['revision']==3


def test_enabled_deadline_task_hook_and_action_are_one_transaction(env,monkeypatch):
    from app.domain import entry_deadline_tasks as tasks
    from tests import test_entry_deadlines as deadlines
    from tests.test_entry_deadline_sources import selection
    app=setup(env);deadlines.write(env,app,'recalculate',selection(env))
    deadlines.write(env,app,'manual',deadlines.manual()|{'evidence_on':'2026-10-10'})
    from tests.test_entry_deadline_tasks import sync,read as task_read
    enabled=sync(env,app,enable=True)
    assert enabled['task'] is not None
    receipt=receive(env,text=message('correction'));action(env,receipt,'correlate');before=counts(env)
    original=tasks.sync_enabled;observed=[]
    async def after_hook(session,case,application,actor):
        await original(session,case,application,actor)
        observed.append(application.id)
        raise RuntimeError('synthetic failure after enabled task hook')
    with monkeypatch.context() as scoped:
        scoped.setattr(tasks,'sync_enabled',after_hook)
        with pytest.raises(EntryStorageUnavailable):action(env,receipt,'confirm')
    assert observed==[app['id']] and counts(env)==before
    assert task_read(env,app)['current']==enabled
    action(env,receipt,'confirm')
    assert read_application(env,app)['current']['status']=='revision_requested'
    assert task_read(env,app)['current']['enabled']


def test_growth_keyset_pagination_and_old_receipt_retry_stay_available(env):
    first=receive(env);args=receive_args(env)
    for i in range(42):receive(env,transport_id=f'list-{i}',request_key=f'list-{i}',text=message(reference=f'{i:08d}'))
    page=asyncio.run(service.list_receipts(env['engine'],actor=ADMIN,case_id=env['cases']['visa']))
    assert len(page['receipts'])==20 and page['next_before']
    receive(env,transport_id='between-pages',request_key='between-pages',text=message(reference='ZZZZ0001'))
    later=asyncio.run(service.list_receipts(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],before=page['next_before']))
    assert not {v['id'] for v in page['receipts']} & {v['id'] for v in later['receipts']}
    assert asyncio.run(service.receive(env['engine'],**(args|{'policy':None})))==first
    assert read(env,first)['receipt']['id']==first['id']


def test_competing_decisions_and_late_return_cannot_regress_approved_application(env):
    app=setup(env);first=receive(env);late=receive(env,text=message('correction'),transport_id='late',request_key='late')
    action(env,first,'correlate');action(env,late,'correlate');action(env,first,'confirm')
    with pytest.raises(EntryStorageConflict):action(env,late,'confirm')
    action(env,late,'correlate')
    assert not read(env,late)['can_confirm']
    with pytest.raises(EntryStorageInvalid,match='not_submitted'):action(env,late,'confirm')
    assert read_application(env,app)['current']['status']=='approved'
