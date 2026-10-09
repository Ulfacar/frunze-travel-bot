"""Internal date-only CRM tasks. No messages, legal decisions or scheduler identity.

The immutable deadline journal is the source; CalendarTaskEvent remains the task
audit. Transactions lock case, application, then task. Hooks share their caller's
transaction and only process tracks explicitly enabled by an operator.
"""
from datetime import date
import json

from sqlalchemy import inspect, select

from app.domain import entry_applications as applications, entry_deadlines as deadlines
from app.domain.calendar_tasks import CalendarTaskService, _log_event
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable, _authorize, _hash, _id, _key
from app.domain.models import CalendarTask, CalendarTaskEvent, EntryDeadlineTask, _now
from app.knowledge.review import canonical

MAX_GENERATIONS = 250
MAX_ACTIONS = 250
ACTIVE = ('planned', 'rescheduled')


def _validate(actor, case_id, application_id, rule):
    _authorize(actor); _id(case_id); _id(application_id); deadlines.sources.unit_id(rule)


async def _bindings(session, application, rule):
    rows = list((await session.scalars(select(EntryDeadlineTask).where(
        EntryDeadlineTask.application_id == application.id, EntryDeadlineTask.rule_unit_id == rule)
        .order_by(EntryDeadlineTask.generation).limit(MAX_GENERATIONS + 1))).all())
    if len(rows) > MAX_GENERATIONS or any(r.case_id != application.case_id or r.generation != i
                                         for i, r in enumerate(rows, 1)):
        raise EntryStorageInvalid('deadline_task_binding_invalid')
    return rows


async def _task(session, case, binding, *, lock=False):
    if binding is None or binding.task_id is None:
        return None
    query = select(CalendarTask).where(CalendarTask.id == binding.task_id)
    task = await session.scalar(query.with_for_update(read=not lock, of=CalendarTask))
    if (task is None or task.service_case_id != case.id or task.contact_id != case.contact_id or
        task.direction != 'visa' or task.kind != 'followup' or task.status not in (*ACTIVE, 'completed', 'cancelled')):
        raise EntryStorageInvalid('deadline_task_scope_invalid')
    event = await session.scalar(select(CalendarTaskEvent).where(CalendarTaskEvent.task_id == task.id,
        CalendarTaskEvent.event == 'deadline_bound').order_by(CalendarTaskEvent.id.desc()).limit(1))
    try:
        evidence = json.loads(event.detail)
        expected = evidence['after']
        if (evidence['binding'] != binding.id or expected['source'] != binding.source_hash or
            expected['target'] != binding.target_hash or expected['deadline'] != binding.deadline_revision_id or
            expected['task']['id'] != task.id or expected['task']['date'] != binding.expected_date.isoformat()):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError):
        raise EntryStorageInvalid('deadline_task_binding_audit_invalid') from None
    return task


def _task_state(task):
    if task is None:
        return None
    return dict(id=task.id, owner=task.manager_id, status=task.status, priority=task.priority,
                date=task.scheduled_date.isoformat(), at=applications._utc(task.scheduled_at) if task.scheduled_at else None,
                claimed=bool(task.claimed_at or task.claimed_by))


def _view(binding, task, desired=None):
    if binding is None:
        return dict(enabled=False, binding_id=None, token=None, task=None, attention='', pending=False)
    state = _task_state(task)
    attention = binding.attention
    if task and state['claimed']:
        attention = 'claimed'
    elif task and task.status in ACTIVE and (task.scheduled_date != binding.expected_date or task.scheduled_at is not None):
        attention = 'schedule_conflict'
    return dict(enabled=True, binding_id=binding.id, generation=binding.generation, revision=binding.revision,
        deadline_revision_id=binding.deadline_revision_id, attention=attention, task=state,
        pending=bool(desired and desired['target_hash'] != binding.target_hash and
            (not task or task.status in ACTIVE or binding.source_hash != desired['source_hash'] or binding.attention == 'missing_owner')),
        token=_hash(dict(binding_id=binding.id, revision=binding.revision, task=state)))


async def _desired(session, case, application, rule):
    rows, _, stale = await deadlines._history(session, case, application, rule)
    if not rows:
        raise EntryStorageInvalid('deadline_task_source_required')
    source = rows[-1]
    due = deadlines._view(source, stale=stale[source.id])['summary']['operational_due_on']
    owner = (case.owner_login or '').strip().lower()
    source_hash = _hash(dict(id=source.id, hash=source.snapshot_hash, due_on=due, stale=stale[source.id]))
    return dict(source=source, source_hash=source_hash, target_hash=_hash(dict(source=source_hash, owner=owner)),
                due_on=date.fromisoformat(due) if due else None, owner=owner)


async def _attention(session, binding, task, value, actor):
    if binding.attention != value:
        previous = binding.attention
        binding.attention = value; binding.revision += 1
        binding.updated_by = actor; binding.updated_at = _now()
        if task:
            await _log_event(session, task, 'deadline_attention', actor=actor,
                             detail=canonical(dict(binding=binding.id, previous=previous, current=value)))
        await session.flush()


async def _reconcile(session, case, application, rule, actor, *, enable=False, restore=False, minimum_revision=None):
    bindings = await _bindings(session, application, rule)
    binding = bindings[-1] if bindings else None
    if not binding and not enable:
        return _view(None, None)
    desired = await _desired(session, case, application, rule)
    task = await _task(session, case, binding, lock=True)
    if minimum_revision and desired['source'].revision < minimum_revision:
        return {**_view(binding, task, desired), 'waiting_for_revision': minimum_revision}
    if task and (task.claimed_at or task.claimed_by):
        await _attention(session, binding, task, 'claimed', actor)
        return _view(binding, task, desired)
    if task and task.status in ACTIVE and (task.scheduled_date != binding.expected_date or task.scheduled_at is not None) and not restore:
        await _attention(session, binding, task, 'schedule_conflict', actor)
        return _view(binding, task, desired)
    if task and task.status not in ACTIVE:
        # A completed/cancelled task does not reopen on owner changes or retries.
        if binding.source_hash == desired['source_hash'] and not (binding.attention == 'missing_owner' and desired['owner'] and desired['due_on']):
            return _view(binding, task, desired)
        if len(bindings) >= MAX_GENERATIONS:
            await _attention(session, binding, task, 'generation_limit', actor)
            return _view(binding, task, desired)
        binding = None; task = None
    if binding is None:
        binding = EntryDeadlineTask(case_id=case.id, application_id=application.id, rule_unit_id=rule,
            generation=len(bindings)+1, revision=1, deadline_revision_id=desired['source'].id,
            source_hash=desired['source_hash'], target_hash=desired['target_hash'], expected_date=None,
            attention='', created_by=actor, updated_by=actor)
        session.add(binding); await session.flush()
    before = dict(source=binding.source_hash, target=binding.target_hash, deadline=binding.deadline_revision_id,
                  task=_task_state(task), attention=binding.attention)
    attention = 'unknown_date' if desired['due_on'] is None else 'missing_owner' if not desired['owner'] else ''
    if task and task.status in ACTIVE and attention:
        await CalendarTaskService.cancel(session, task, actor=actor)
    elif not attention:
        if task is None:
            task = await CalendarTaskService.create(session, manager_id=desired['owner'], direction='visa', kind='followup',
                scheduled_date=desired['due_on'], contact_id=case.contact_id, created_by=actor,
                comment=f"Контроль срока: заявление №{application.id}, {rule}. Проверить подтверждённую дату в карточке.")
            task.service_case_id = case.id; binding.task_id = task.id
        else:
            if task.scheduled_date != desired['due_on'] or task.scheduled_at is not None:
                await CalendarTaskService.reschedule(session, task, new_date=desired['due_on'], actor=actor)
            if task.manager_id != desired['owner']:
                old_owner = task.manager_id; task.manager_id = desired['owner']
                await _log_event(session, task, 'reassigned', actor=actor,
                                 detail=canonical(dict(previous=old_owner, current=desired['owner'], binding=binding.id)))
    binding.source_hash = desired['source_hash']; binding.target_hash = desired['target_hash']
    binding.deadline_revision_id = desired['source'].id
    binding.expected_date = task.scheduled_date if task else None
    binding.attention = attention
    after = dict(source=binding.source_hash, target=binding.target_hash, deadline=binding.deadline_revision_id,
                 task=_task_state(task), attention=attention)
    if before != after:
        binding.revision += 1; binding.updated_by = actor; binding.updated_at = _now()
        if task:
            await _log_event(session, task, 'deadline_bound', actor=actor,
                             detail=canonical(dict(binding=binding.id, before=before, after=after)))
    await session.flush()
    return _view(binding, task, desired)


async def sync_enabled(session, case, application, actor):
    """Atomic source hook; caller already holds case/application write locks."""
    # Older journal migrations remain usable before this additive capability is
    # installed. With no binding table, no track can have been enabled. Explicit
    # task APIs still require the new migration and never hide a storage error.
    if not await session.run_sync(lambda s: inspect(s.connection()).has_table('entry_deadline_tasks')):
        return
    rules = list((await session.scalars(select(EntryDeadlineTask.rule_unit_id).where(
        EntryDeadlineTask.application_id == application.id).distinct().order_by(EntryDeadlineTask.rule_unit_id)
        .limit(deadlines.MAX_TRACKS + 1))).all())
    if len(rules) > deadlines.MAX_TRACKS:
        raise EntryStorageInvalid('deadline_task_track_limit')
    for rule in rules:
        await _reconcile(session, case, application, rule, actor)


async def reconcile_deadline_task(engine, *, actor, case_id, application_id, rule_unit_id,
                                  enable=False, restore=False, expected_token=None, minimum_revision=None):
    _validate(actor, case_id, application_id, rule_unit_id)
    if type(enable) is not bool or type(restore) is not bool:
        raise EntryStorageInvalid('invalid_deadline_task_command')
    if minimum_revision is not None and (type(minimum_revision) is not int or not 1 <= minimum_revision <= deadlines.MAX_REVISIONS):
        raise EntryStorageInvalid('invalid_deadline_revision')
    async def write(session):
        case = await applications._case(session, case_id, lock=True)
        application = await applications._application(session, case_id, application_id, lock=True)
        if restore:
            bindings = await _bindings(session, application, rule_unit_id)
            binding = bindings[-1] if bindings else None
            task = await _task(session, case, binding, lock=True)
            if not expected_token or expected_token != _view(binding, task)['token']:
                raise EntryStorageConflict('deadline_task_changed')
        return await _reconcile(session, case, application, rule_unit_id, actor.manager_id,
                                enable=enable, restore=restore, minimum_revision=minimum_revision)
    return await applications._run(engine, write)


async def read_deadline_task(engine, *, actor, case_id, application_id, rule_unit_id):
    _validate(actor, case_id, application_id, rule_unit_id)
    async def read(session):
        case = await applications._case(session, case_id)
        application = await applications._application(session, case_id, application_id)
        desired = await _desired(session, case, application, rule_unit_id)
        bindings = await _bindings(session, application, rule_unit_id)
        result = []
        for binding in reversed(bindings):
            task = await _task(session, case, binding)
            result.append(_view(binding, task, desired if binding == bindings[-1] else None))
        events = []
        if result and result[0]['task']:
            audit = list((await session.scalars(select(CalendarTaskEvent).where(
                CalendarTaskEvent.task_id == result[0]['task']['id']).order_by(CalendarTaskEvent.id.desc()).limit(50))).all())
            for event in audit:
                item = dict(event=event.event, actor=event.actor, created_at=applications._utc(event.created_at))
                if event.event == 'deadline_action':
                    item.update(action=json.loads(event.detail)['command']['action'], reason=json.loads(event.detail)['command']['reason'])
                events.append(item)
        return dict(current=result[0] if result else _view(None, None), history=result,
                    owner=desired['owner'], due_on=desired['due_on'].isoformat() if desired['due_on'] else None, events=events)
    return await applications._run(engine, read)


async def act_on_deadline_task(engine, *, actor, case_id, application_id, rule_unit_id,
                               binding_id, expected_token, request_key, action, reason=None):
    _validate(actor, case_id, application_id, rule_unit_id); _id(binding_id); _key(request_key)
    if action not in ('complete', 'cancel', 'escalate') or (reason not in ('overdue', 'needs_review', 'urgent') if action == 'escalate' else reason is not None):
        raise EntryStorageInvalid('invalid_deadline_task_action')
    if not isinstance(expected_token, str) or len(expected_token) != 64:
        raise EntryStorageInvalid('invalid_deadline_task_token')
    command = dict(binding=binding_id, token=expected_token, request_key=request_key, action=action, reason=reason, actor=actor.manager_id)
    async def write(session):
        case = await applications._case(session, case_id, lock=True)
        application = await applications._application(session, case_id, application_id, lock=True)
        desired = await _desired(session, case, application, rule_unit_id)
        bindings = await _bindings(session, application, rule_unit_id)
        binding = next((b for b in bindings if b.id == binding_id), None)
        if binding is None:
            raise EntryStorageInvalid('deadline_task_unavailable')
        task = await _task(session, case, binding, lock=True)
        if task is None:
            raise EntryStorageInvalid('deadline_task_unavailable')
        receipts = list((await session.scalars(select(CalendarTaskEvent).where(CalendarTaskEvent.task_id == task.id,
            CalendarTaskEvent.event == 'deadline_action').order_by(CalendarTaskEvent.id).limit(MAX_ACTIONS+1))).all())
        for event in receipts:
            try: receipt = json.loads(event.detail)
            except (ValueError, TypeError): raise EntryStorageInvalid('deadline_task_receipt_invalid') from None
            if receipt['command']['actor'] != event.actor or receipt['command']['binding'] != binding.id:
                raise EntryStorageInvalid('deadline_task_receipt_invalid')
            if receipt['command']['request_key'] == request_key:
                if receipt['command'] != command:
                    raise EntryStorageConflict('deadline_task_request_reused')
                return _view(binding, task, desired)
        if len(receipts) >= MAX_ACTIONS:
            raise EntryStorageInvalid('deadline_task_action_limit')
        if binding != bindings[-1] or expected_token != _view(binding, task)['token'] or binding.target_hash != desired['target_hash']:
            raise EntryStorageConflict('deadline_task_changed')
        if task.claimed_at or task.claimed_by:
            raise EntryStorageConflict('deadline_task_claimed')
        if task.status not in ACTIVE:
            raise EntryStorageConflict('deadline_task_terminal')
        if task.scheduled_date != binding.expected_date or task.scheduled_at is not None:
            raise EntryStorageConflict('deadline_task_schedule_conflict')
        before = _task_state(task)
        if action == 'complete': await CalendarTaskService.complete(session, task, actor=actor.manager_id)
        elif action == 'cancel': await CalendarTaskService.cancel(session, task, actor=actor.manager_id)
        else: task.priority = 'high'
        binding.revision += 1; binding.updated_by = actor.manager_id; binding.updated_at = _now()
        await _log_event(session, task, 'deadline_action', actor=actor.manager_id,
                         detail=canonical(dict(command=command, before=before, after=_task_state(task))))
        return _view(binding, task, desired)
    return await applications._run(engine, write)


async def reconcile_case_deadline_tasks(engine, *, actor, case_id, after_binding_id=0, limit=20):
    """Bounded resumable worker: each track commits independently, latest state wins.

    Scans enabled bindings only. Start a new sweep at zero to include anchor/owner
    changes without a new source row. No message sender or background identity.
    """
    _authorize(actor); _id(case_id)
    if type(after_binding_id) is not int or after_binding_id < 0 or type(limit) is not int or not 1 <= limit <= 50:
        raise EntryStorageInvalid('invalid_deadline_task_batch')
    async def read(session):
        await applications._case(session, case_id)
        # First binding per track is a stable cursor even when generations grow.
        return list((await session.scalars(select(EntryDeadlineTask).where(EntryDeadlineTask.case_id == case_id,
            EntryDeadlineTask.generation == 1, EntryDeadlineTask.id > after_binding_id)
            .order_by(EntryDeadlineTask.id).limit(limit + 1))).all())
    rows = await applications._run(engine, read)
    results = []
    for row in rows[:limit]:
        try:
            state = await reconcile_deadline_task(engine, actor=actor, case_id=case_id,
                application_id=row.application_id, rule_unit_id=row.rule_unit_id)
            results.append(dict(cursor=row.id, status='ok', state=state))
        except (EntryStorageInvalid, EntryStorageConflict, EntryStorageUnavailable) as exc:
            results.append(dict(cursor=row.id, status='failed', code=str(exc)))
    return dict(results=results, next_cursor=rows[limit-1].id if len(rows) > limit else None,
                retry_cursors=[r['cursor'] for r in results if r['status'] != 'ok'])
