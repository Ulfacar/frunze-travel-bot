import asyncio
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine,event,text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_interview_handoff_0029'
CURRENT='e6_quote_revisions_0030'
TABLE='entry_quote_revisions'


def schema(conn):
    return {n:s for n,s in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
        if n!='alembic_version' and n!=TABLE and TABLE not in s}


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


def test_populated_downgrade_refusal_and_scoped_foreign_keys(config,monkeypatch):
    from app.config import settings
    from tests.test_admin_workday import _seed_case
    from tests.test_entry_quotes import subject,save,read
    monkeypatch.setattr(settings,'admin_user','admin');command.upgrade(config,CURRENT)
    engine=create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:','sqlite+aiosqlite:',1),poolclass=NullPool)
    def enable(dbapi,record):
        cursor=dbapi.cursor();cursor.execute('PRAGMA foreign_keys=ON');cursor.close()
    event.listen(engine.sync_engine,'connect',enable);sm=async_sessionmaker(engine,expire_on_commit=False)
    case=_seed_case(sm,owner='admin',reference='SYN-QUOTE',direction='visa')
    other=_seed_case(sm,owner='admin',reference='SYN-OTHER',direction='visa')
    env={'engine':engine,'sm':sm,'cases':{'visa':case['case_id'],'other':other['case_id']}}
    try:
        app=subject(env);save(env,app);save(env,app);assert read(env,app)['revision']==2
        async def invalid():
            for column,value in [('case_id',other['case_id']),('applicant_id',99999),('procedure','registration'),
                ('revision',129),('previous_id',99999),('application_id',99999)]:
                async with engine.begin() as conn:
                    with pytest.raises(IntegrityError):await conn.execute(text(f'UPDATE {TABLE} SET {column}=:value'),{'value':value})
        asyncio.run(invalid())
    finally:asyncio.run(engine.dispose())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
    sync=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with sync.connect() as conn:
            assert conn.scalar(text('SELECT count(*) FROM '+TABLE))==2
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))==CURRENT
    finally:sync.dispose()


def test_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused');config.output_buffer=io.StringIO()
    command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True);ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1
    assert all(column+' JSON' in ddl for column in ('command','result','policy','source_pin','authority'))
    assert 'UNIQUE (application_id, revision)' in ddl and 'FOREIGN KEY(application_id, case_id, applicant_id, procedure)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
