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

PREVIOUS='e6_deadlines_0021'
CURRENT='e6_deadline_tasks_0022'
TABLE='entry_deadline_tasks'


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


def test_migrated_worker_foreign_scope_and_populated_downgrade(config):
    from app.domain import entry_deadlines as deadlines, entry_deadline_tasks as tasks, entry_applications as apps
    from app.domain.knowledge_import import create_kg_entry_set, import_bundle
    from tests.test_admin_workday import _seed_case
    from tests.test_admin_kg_entry import ADMIN, FIX
    from tests.test_entry_deadlines import manual
    command.upgrade(config,CURRENT)
    engine=create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:','sqlite+aiosqlite:',1),poolclass=NullPool)
    def enable(dbapi,record):
        cursor=dbapi.cursor();cursor.execute('PRAGMA foreign_keys=ON');cursor.close()
    event.listen(engine.sync_engine,'connect',enable)
    sm=async_sessionmaker(engine,expire_on_commit=False)
    first=_seed_case(sm,owner='admin',reference='synthetic-task',direction='visa')
    second=_seed_case(sm,owner='admin',reference='synthetic-other',direction='visa')
    async def run():
        try:
            set_id=await create_kg_entry_set(engine,actor=ADMIN)
            imported=await import_bundle(engine,actor=ADMIN,set_id=set_id,directory=FIX/'synthetic_bundle',source=FIX/'synthetic_source.txt')
            assert imported.accepted
            app_ids=[]
            for case in (first,second):
                args=dict(actor=ADMIN,case_id=case['case_id'])
                person=await apps.add_applicant(engine,**args,role='primary',request_key='person')
                app=await apps.open_application(engine,**args,applicant_id=person['id'],procedure='visa',request_key='app')
                app_ids.append(app['id'])
            args=dict(actor=ADMIN,case_id=first['case_id'],application_id=app_ids[0],rule_unit_id='KG.DL.TEST')
            data=dict(knowledge_version_id=imported.version_id,calendar_ids=[],anchor=None,policy=None)
            await deadlines.record_deadline_operation(engine,**args,expected_revision=0,request_key='calc',operation=dict(action='recalculate',data=data,confirmed=True))
            await deadlines.record_deadline_operation(engine,**args,expected_revision=1,request_key='manual',operation=dict(action='manual',data=manual(),confirmed=True))
            result=await tasks.reconcile_deadline_task(engine,**args,enable=True)
            assert result['task']['date']=='2026-10-20'
            sql="INSERT INTO entry_deadline_tasks(case_id,application_id,rule_unit_id,generation,revision,deadline_revision_id,task_id,source_hash,target_hash,expected_date,attention,created_by,updated_by,created_at,updated_at) SELECT :case,:app,:rule,:gen,revision,deadline_revision_id,:task,source_hash,target_hash,expected_date,attention,created_by,updated_by,created_at,updated_at FROM entry_deadline_tasks WHERE id=:id"
            defaults=dict(case=first['case_id'],app=app_ids[0],rule='KG.DL.TEST',gen=2,task=None,id=result['binding_id'])
            for override in ({'case':second['case_id']},{'app':app_ids[1]},{'rule':'KG.DL.OTHER'},
                             {'task':999},{'task':result['task']['id']},{'gen':1},{'gen':251}):
                async with engine.begin() as conn:
                    with pytest.raises(IntegrityError):await conn.execute(text(sql),{**defaults,**override})
        finally:await engine.dispose()
    asyncio.run(run())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
    engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:
            assert TABLE in inspect(conn).get_table_names()
            assert conn.scalar(text('SELECT count(*) FROM entry_deadline_tasks'))==1
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))==CURRENT
    finally:engine.dispose()


def test_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1
    assert 'FOREIGN KEY(application_id, case_id)' in ddl and 'FOREIGN KEY(task_id)' in ddl
    assert 'FOREIGN KEY(deadline_revision_id, application_id, case_id, rule_unit_id)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
