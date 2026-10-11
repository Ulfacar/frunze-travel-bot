"""Withdrawal must remain possible without enlarging ordinary history limits."""
import asyncio

import pytest
from sqlalchemy import select

from app.domain import entry_deadlines as service
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.models import EntryDeadlineRevision
from app.knowledge.review import canonical
from tests.test_admin_kg_entry import env, Form
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_deadline_tasks import seed, sync, read as task_read
from tests.test_entry_deadlines import read, write, manual
from tests.test_entry_deadline_sources import selection


def at_capacity(env, app, monkeypatch, bound):
    if bound == 'count':
        monkeypatch.setattr(service, 'MAX_REVISIONS', 2)
    else:
        async def size():
            async with env['sm']() as session:
                rows = (await session.scalars(select(EntryDeadlineRevision).where(
                    EntryDeadlineRevision.application_id == app['id']))).all()
                return sum(len(canonical(service._payload(row)).encode()) for row in rows)
        monkeypatch.setattr(service, 'MAX_BYTES', asyncio.run(size()) + 100)


@pytest.mark.parametrize('bound', ['count', 'bytes'])
def test_terminal_clear_preserves_receipts_and_cancels_task(env, monkeypatch, bound):
    app = seed(env)
    sync(env, app, enable=True)
    old = read(env, app)['selected']
    at_capacity(env, app, monkeypatch, bound)
    assert read(env, app)['selected'] == old
    assert sync(env, app, minimum_revision=3)['waiting_for_revision'] == 3
    with pytest.raises(EntryStorageInvalid):
        write(env, app, 'manual', manual(reason='corrected_date'))
    cleared = write(env, app, 'clear', {'reason': 'wrong_document'}, key='capacity-clear')
    assert cleared['summary']['operational_due_on'] is None
    assert read(env, app)['terminal'] is True
    assert read(env, app, revision=old['revision'])['selected'] == old
    assert read(env, app, replay=True)['selected'] == cleared
    assert task_read(env, app)['current']['task']['status'] == 'cancelled'
    current_task = sync(env, app, minimum_revision=3)
    assert 'waiting_for_revision' not in current_task and current_task['task']['status'] == 'cancelled'
    assert sync(env, app, minimum_revision=3) == current_task
    for invalid in (0, True, service.MAX_REVISIONS+2):
        with pytest.raises(EntryStorageInvalid, match='invalid_deadline_revision'):
            sync(env, app, minimum_revision=invalid)
    assert write(env, app, 'clear', {'reason': 'wrong_document'}, revision=2, key='capacity-clear') == cleared
    for action, data in [('manual', manual()), ('recalculate', selection(env)), ('clear', {'reason': 'wrong_document'})]:
        with pytest.raises(EntryStorageInvalid):
            write(env, app, action, data)
    assert read(env, app)['current_revision'] == 3


@pytest.mark.parametrize('bound', ['count', 'bytes'])
def test_native_capacity_clear_and_terminal_history(env, monkeypatch, bound):
    import app.admin.kg_deadlines as ui
    app = seed(env)
    sync(env, app, enable=True)
    at_capacity(env, app, monkeypatch, bound)
    url = ui._url(env['cases']['visa'], app['id']) + '?rule=KG.DL.TEST'
    page = env['client'].get(url)
    assert page.status_code == 200
    values = Form(page.text, 'kg-dl-clear').data
    assert values
    if bound == 'count':
        assert not Form(page.text, 'kg-dl-manual').data
    values['confirmed'] = 'yes'
    response = env['client'].post(url, data=values)
    assert response.status_code == 200
    for action in ('manual', 'recalculate', 'clear'):
        assert not Form(response.text, 'kg-dl-' + action).data
    assert env['client'].get(url + '&revision=3').status_code == 200
    assert env['client'].post(url, data=values).status_code == 200
    assert task_read(env, app)['current']['task']['status'] == 'cancelled'


def test_clear_and_task_cancellation_roll_back_together(env, monkeypatch):
    from app.domain import entry_deadline_tasks as tasks
    app = seed(env)
    sync(env, app, enable=True)
    at_capacity(env, app, monkeypatch, 'count')
    async def failed(*args, **kwargs):
        raise EntryStorageInvalid('synthetic_task_sync_failure')
    with monkeypatch.context() as patch:
        patch.setattr(tasks, 'sync_enabled', failed)
        with pytest.raises(EntryStorageInvalid, match='synthetic_task_sync_failure'):
            write(env, app, 'clear', {'reason': 'wrong_document'}, key='retry-clear')
    assert read(env, app)['current_revision'] == 2
    assert task_read(env, app)['current']['task']['status'] == 'planned'
    write(env, app, 'clear', {'reason': 'wrong_document'}, key='retry-clear')
    assert task_read(env, app)['current']['task']['status'] == 'cancelled'


def test_actual_250_row_history_has_one_readable_terminal_251(env):
    import app.admin.kg_deadlines as ui
    app = seed(env)
    for revision in range(2, 250):
        write(env, app, 'manual', manual(reason='corrected_date'), revision=revision)
    assert read(env, app)['current_revision'] == 250
    sync(env, app, enable=True)
    assert sync(env, app, minimum_revision=251)['waiting_for_revision'] == 251
    url = ui._url(env['cases']['visa'], app['id']) + '?rule=KG.DL.TEST'
    page = env['client'].get(url)
    assert page.status_code == 200
    values = Form(page.text, 'kg-dl-clear').data
    assert values['_dl_revision'] == '250'
    values.update(confirmed='yes')
    assert env['client'].post(url, data=values).status_code == 200
    current = read(env, app, revision=251, replay=True)
    assert current['terminal'] and current['current_revision'] == 251
    assert current['selected']['summary']['operational_due_on'] is None
    assert env['client'].get(url + '&revision=251').status_code == 200
    assert env['client'].post(url, data=values).status_code == 200
    assert task_read(env, app)['current']['task']['status'] == 'cancelled'

    actual = sync(env, app, minimum_revision=251)
    assert 'waiting_for_revision' not in actual and actual['task']['status'] == 'cancelled'
    assert sync(env, app, minimum_revision=251) == actual
    for invalid in (252, True):
        with pytest.raises(EntryStorageInvalid, match='invalid_deadline_revision'):
            sync(env, app, minimum_revision=invalid)


@pytest.mark.parametrize('bound', ['count', 'bytes'])
def test_reader_rejects_any_append_after_terminal_clear(env, monkeypatch, bound):
    app = seed(env)
    at_capacity(env, app, monkeypatch, bound)
    write(env, app, 'clear', {'reason': 'wrong_document'}, key='clear')
    # Simulate an independently inserted, correctly hashed extra receipt.
    with monkeypatch.context() as patch:
        patch.setattr(service, 'MAX_REVISIONS', 250)
        patch.setattr(service, 'MAX_BYTES', 4 * 1024 * 1024)
        write(env, app, 'manual', manual())
    with pytest.raises(EntryStorageInvalid, match='history_limit'):
        read(env, app)
    with pytest.raises(EntryStorageInvalid, match='history_limit'):
        write(env, app, 'clear', {'reason': 'wrong_document'}, revision=2, key='clear')
