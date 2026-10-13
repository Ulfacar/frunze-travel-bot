import asyncio
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine,event,inspect,text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.pool import NullPool

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_documents_0018'
CURRENT='e6_issued_0019'
TABLE='entry_issued_revisions'


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
            ctx=MigrationContext.configure(conn,opts={'compare_type':True,'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name==TABLE})
            assert compare_metadata(ctx,DomainBase.metadata)==[]
    finally:engine.dispose()


def test_migrated_operations_foreign_keys_and_populated_downgrade(config):
    from app.domain import entry_issued as issued,entry_applications as apps
    from app.domain.permissions import Actor
    from tests.test_admin_workday import _seed_case
    command.upgrade(config,CURRENT)
    engine=create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:','sqlite+aiosqlite:',1),poolclass=NullPool)
    def enable(dbapi,record):
        cursor=dbapi.cursor();cursor.execute('PRAGMA foreign_keys=ON');cursor.close()
    event.listen(engine.sync_engine,'connect',enable)
    sm=async_sessionmaker(engine,expire_on_commit=False)
    case=_seed_case(sm,owner='admin',reference='synthetic-issued',direction='visa')
    other=_seed_case(sm,owner='admin',reference='synthetic-other',direction='visa')
    async def run():
        try:
            args=dict(actor=Actor('admin',True),case_id=case['case_id'])
            person=await apps.add_applicant(engine,**args,role='primary',request_key='p')
            app=await apps.open_application(engine,**args,applicant_id=person['id'],procedure='visa',request_key='a')
            await apps.record_application_event(engine,**args,application_id=app['id'],expected_revision=1,request_key='submitted',status='submitted',occurred_on='2026-09-01',source='portal',reference='AB12CD34',confirmed=True)
            await apps.record_application_event(engine,**args,application_id=app['id'],expected_revision=2,request_key='approved',status='approved',occurred_on='2026-09-02',source='portal',reference='AB12CD34',confirmed=True)
            row=await issued.record_issued_operation(engine,**args,application_id=app['id'],expected_revision=0,request_key='file',
                operation=dict(action='file',data=dict(fingerprint='a'*64,passport_fingerprint='b'*64,on='2026-09-03'),confirmed=True))
            assert (await issued.read_issued_history(engine,**args,application_id=app['id']))['current_revision']==1
            other_args=dict(actor=Actor('admin',True),case_id=other['case_id'])
            other_person=await apps.add_applicant(engine,**other_args,role='primary',request_key='other-person')
            other_app=await apps.open_application(engine,**other_args,applicant_id=other_person['id'],procedure='visa',request_key='other-app')
            async with engine.connect() as conn:
                other_event=await conn.scalar(text('SELECT id FROM entry_application_events WHERE application_id=:app'),{'app':other_app['id']})
            sql="INSERT INTO entry_issued_revisions(case_id,application_id,approval_event_id,revision,previous_id,request_key,request_hash,snapshot_hash,command,snapshot,created_by,created_at) SELECT :case,application_id,:approval,:rev,:prev,:key,request_hash,snapshot_hash,command,snapshot,created_by,created_at FROM entry_issued_revisions WHERE id=:id"
            for changes in ({'case':other['case_id'],'rev':2,'prev':row['id'],'key':'foreign'},
                            {'case':case['case_id'],'rev':1,'prev':None,'key':'duplicate'},
                            {'case':case['case_id'],'rev':2,'prev':row['id']+99,'key':'missing'},
                            {'case':case['case_id'],'rev':2,'prev':row['id'],'key':'wrong-approval','approval':other_event}):
                async with engine.begin() as conn:
                    with pytest.raises(IntegrityError):await conn.execute(text(sql),dict(id=row['id'],**{'approval':row['approval_event_id'],**changes}))
        finally:await engine.dispose()
    asyncio.run(run())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
    sync=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with sync.connect() as conn:
            assert TABLE in inspect(conn).get_table_names()
            assert conn.scalar(text('SELECT count(*) FROM entry_issued_revisions'))==1
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))==CURRENT
    finally:sync.dispose()


def test_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1
    assert 'FOREIGN KEY(application_id, case_id) REFERENCES entry_applications (id, case_id)' in ddl
    assert 'FOREIGN KEY(previous_id, application_id, case_id)' in ddl
    assert 'UNIQUE (application_id, request_key)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
