import asyncio
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_profiles_0020'
CURRENT='e6_deadlines_0021'
TABLE='entry_deadline_revisions'


def schema(conn):
    return {n:s for n,s in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
            if n not in ('alembic_version',TABLE) and TABLE not in (s or '')}


def test_additive_empty_cycle_and_model_parity(config):
    command.upgrade(config,PREVIOUS);engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:before=schema(conn)
        for fn,target in ((command.upgrade,CURRENT),(command.downgrade,PREVIOUS),(command.upgrade,CURRENT)):
            fn(config,target)
            with engine.connect() as conn:assert schema(conn)==before
        with engine.connect() as conn:
            context=MigrationContext.configure(conn,opts={'compare_type':True,
                'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name==TABLE})
            assert compare_metadata(context,DomainBase.metadata)==[]
    finally:engine.dispose()


def test_migrated_deadlines_actual_event_foreign_scope_and_preserved_downgrade(config):
    from app.domain import entry_deadlines as deadlines, entry_applications as apps
    from app.domain.knowledge_import import create_kg_entry_set, import_bundle
    from tests.test_admin_workday import _seed_case
    from tests.test_admin_kg_entry import ADMIN, FIX
    command.upgrade(config,CURRENT)
    engine=create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:','sqlite+aiosqlite:',1),poolclass=NullPool)
    def enable(dbapi,record):
        cursor=dbapi.cursor();cursor.execute('PRAGMA foreign_keys=ON');cursor.close()
    event.listen(engine.sync_engine,'connect',enable)
    sm=async_sessionmaker(engine,expire_on_commit=False)
    first=_seed_case(sm,owner='admin',reference='synthetic-deadline',direction='visa')
    second=_seed_case(sm,owner='admin',reference='synthetic-other',direction='visa')
    async def run():
        try:
            set_id=await create_kg_entry_set(engine,actor=ADMIN)
            imported=await import_bundle(engine,actor=ADMIN,set_id=set_id,directory=FIX/'synthetic_bundle',source=FIX/'synthetic_source.txt')
            assert imported.accepted
            apps_by_case=[]
            for case in (first,second):
                args=dict(actor=ADMIN,case_id=case['case_id'])
                person=await apps.add_applicant(engine,**args,role='primary',request_key='person')
                app=await apps.open_application(engine,**args,applicant_id=person['id'],procedure='visa',request_key='app')
                ev=await apps.record_application_event(engine,**args,application_id=app['id'],expected_revision=1,
                    request_key='submitted',status='submitted',occurred_on='2026-09-01',source='portal',
                    reference=f'DL{app["id"]:06}',confirmed=True)
                apps_by_case.append((app,ev))
            app,ev=apps_by_case[0]
            data=dict(knowledge_version_id=imported.version_id,calendar_ids=[],anchor=dict(kind='application_event',id=ev['id']),policy=None)
            args=dict(actor=ADMIN,case_id=first['case_id'],application_id=app['id'],rule_unit_id='KG.DL.TEST')
            row=await deadlines.record_deadline_operation(engine,**args,expected_revision=0,request_key='calc',
                operation=dict(action='recalculate',data=data,confirmed=True))
            assert (await deadlines.read_deadline_history(engine,**args,replay=True))['selected']==row
            sql="INSERT INTO entry_deadline_revisions(case_id,application_id,rule_unit_id,knowledge_version_id,anchor_event_id,anchor_issued_id,revision,previous_id,request_key,request_hash,snapshot_hash,command,snapshot,created_by,created_at) SELECT :case,:app,:rule,knowledge_version_id,:event,anchor_issued_id,:rev,:prev,:key,request_hash,snapshot_hash,command,snapshot,created_by,created_at FROM entry_deadline_revisions WHERE id=:id"
            defaults=dict(case=first['case_id'],app=app['id'],rule='KG.DL.TEST',event=ev['id'],rev=2,prev=row['id'],key='invalid',id=row['id'])
            for override in ({'case':second['case_id']},{'event':apps_by_case[1][1]['id']},{'rule':'KG.DL.OTHER'},
                             {'prev':999},{'rev':1,'prev':None},{'rev':251}):
                async with engine.begin() as conn:
                    with pytest.raises(IntegrityError):await conn.execute(text(sql),{**defaults,**override})
        finally:await engine.dispose()
    asyncio.run(run())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
    engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:
            assert TABLE in inspect(conn).get_table_names()
            assert conn.scalar(text('SELECT count(*) FROM entry_deadline_revisions'))==1
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))==CURRENT
    finally:engine.dispose()


def test_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1
    assert 'FOREIGN KEY(application_id, case_id)' in ddl
    assert 'FOREIGN KEY(anchor_event_id, application_id)' in ddl
    assert 'FOREIGN KEY(anchor_issued_id, application_id, case_id)' in ddl
    assert 'FOREIGN KEY(previous_id, application_id, case_id, rule_unit_id)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
