import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading

import pytest
from sqlalchemy import select, func

from tests.test_entry_process_postgres import template, env
from tests.test_conditional_deadlines import clock
from tests.test_entry_anchor_migration import metadata_options
from tests import test_conditional_deadlines as core
from tests.test_specialist_postgres import waiting
from app.domain import conditional_deadlines as service, conditional_deadline_sources as sources
from app.domain.conditional_deadline_policy import from_document
from app.domain.models import KnowledgeSet, EntryDeadlineRevision
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict


def test_first_record_resamples_clock_after_actual_publication_lock(env,tmp_path,monkeypatch):
    prepared=core.setup(env,tmp_path)
    rule='KG.DL.REGISTRATION_EXTENSION'
    doc=core.authority(env,rule).document
    doc['policy']['review_due_on']='2026-10-13'
    authority=from_document(doc)
    options=core.arguments(env,prepared,rule,authority)
    first=core.preview(env,options)
    assert first['report']['review_due_on']=='2026-11-01'
    request=options|dict(expected_revision=0,request_key='AUDIT-WAIT-CLOCK',
        operation=dict(action='conditional_review',confirmed=True,evidence_hash=first['report']['evidence_hash']))
    current=[datetime(2026,10,13,17,59,59,tzinfo=timezone.utc)]
    monkeypatch.setattr(service,'_now',lambda:current[0])
    monkeypatch.setattr(sources,'_now',lambda:current[0])
    locked=threading.Event(); release=threading.Event()
    async def hold_source():
        async with env['sm']() as session:
            async with session.begin():
                await session.scalar(select(KnowledgeSet).where(KnowledgeSet.code=='kg_entry').with_for_update())
                locked.set()
                assert await asyncio.to_thread(release.wait,30)
    def write():return asyncio.run(service.record(env['engine'],**request))
    with ThreadPoolExecutor(max_workers=2) as pool:
        holder=pool.submit(lambda:asyncio.run(hold_source()))
        try:
            assert locked.wait(15)
            writer=pool.submit(write)
            waiting(env,writer)
            current[0]+=timedelta(seconds=2)
        finally:release.set()
        holder.result(timeout=30)
        with pytest.raises((EntryStorageInvalid,EntryStorageConflict)):
            writer.result(timeout=60)
    async def count():
        async with env['sm']() as session:return await session.scalar(select(func.count()).select_from(EntryDeadlineRevision))
    assert asyncio.run(count())==0


@pytest.mark.parametrize('mode',['count','bytes'])
def test_actual_pg_anchor_reserves(env,mode):
    from tests import test_entry_anchor_reserves as capacity
    if mode=='count':capacity.test_actual_64_records_still_allow_terminal_withdrawal_and_old_retry(env)
    else:capacity.test_real_byte_boundary_reserves_all_16_active_keys(env)


def test_actual_pg_migration_scope_and_populated_inverse_guard(env):
    from types import SimpleNamespace
    from alembic import command
    from alembic.config import Config
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from app.domain.models import DomainBase,EntryAnchorPin
    from tests import test_entry_anchors as actual
    cfg=Config('alembic.ini')
    cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_work_review_events_0041');command.upgrade(cfg,'head')
    async def metadata():
        async with env['engine'].connect() as conn:
            return await conn.run_sync(lambda c:compare_metadata(MigrationContext.configure(c,opts=metadata_options()),DomainBase.metadata))
    assert asyncio.run(metadata())==[]
    own=actual.setup(env);other=actual.setup(env,key='OTHER')
    request=actual.args(env,own);saved=actual.write(env,request)
    async def substitute():
        async with env['sm']() as session:
            async with session.begin():
                await session.execute(text('UPDATE entry_anchor_pins SET profile_id=:profile WHERE anchor_id=:anchor'),
                    dict(profile=other[2]['qualification_id'],anchor=saved['id']))
    with pytest.raises(IntegrityError):asyncio.run(substitute())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(cfg,'e6_work_review_events_0041')
    assert actual.write(env,request|dict(policy=None))==saved
    assert actual.read(env,own)['observations'][0]['usable']
