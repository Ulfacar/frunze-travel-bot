"""Real additive migration, composite scopes, downgrade and metadata parity."""
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

PREVIOUS='e6_publication_withdraw_0034'
CURRENT='e6_applicant_stay_0035'
TABLE='entry_applicant_stay_history'


def schema(conn):
    return {n:s for n,s in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
        if n not in ('alembic_version',TABLE) and TABLE not in (s or '')}


def test_additive_cycle_and_model_parity(config):
    command.upgrade(config,PREVIOUS)
    engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO contacts(id) VALUES (54321)'));before=schema(conn)
        for fn,target in ((command.upgrade,CURRENT),(command.downgrade,PREVIOUS),(command.upgrade,CURRENT)):
            fn(config,target)
            with engine.connect() as conn:
                assert schema(conn)==before and conn.scalar(text('SELECT id FROM contacts WHERE id=54321'))==54321
        with engine.connect() as conn:
            context=MigrationContext.configure(conn,opts={'compare_type':True,
                'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name==TABLE})
            assert compare_metadata(context,DomainBase.metadata)==[]
    finally:engine.dispose()


def test_migrated_scopes_old_receipts_and_populated_downgrade(config):
    from app.domain import applicant_stay_history as service,applicant_profiles as profiles,entry_applications as apps
    from app.domain.knowledge_import import create_kg_entry_set,import_bundle
    from tests.test_admin_workday import _seed_case
    from tests.test_admin_kg_entry import ADMIN,FIX
    from tests.test_applicant_profiles import request
    from tests.test_applicant_stay_history import document
    command.upgrade(config,PREVIOUS)
    engine=create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:','sqlite+aiosqlite:',1),poolclass=NullPool)
    def enable(dbapi,record):
        cursor=dbapi.cursor();cursor.execute('PRAGMA foreign_keys=ON');cursor.close()
    event.listen(engine.sync_engine,'connect',enable)
    sm=async_sessionmaker(engine,expire_on_commit=False)
    case=_seed_case(sm,owner='admin',reference='synthetic-history',direction='visa')
    other=_seed_case(sm,owner='admin',reference='synthetic-other',direction='visa')
    async def seed():
        set_id=await create_kg_entry_set(engine,actor=ADMIN)
        imported=await import_bundle(engine,actor=ADMIN,set_id=set_id,directory=FIX/'synthetic_bundle',source=FIX/'synthetic_source.txt')
        assert imported.accepted
        args=dict(actor=ADMIN,case_id=case['case_id'])
        first=await apps.add_applicant(engine,**args,role='primary',request_key='person')
        second=await apps.add_applicant(engine,**args,role='child',request_key='child')
        profile=await profiles.save_applicant_profile(engine,**args,applicant_id=first['id'],expected_revision=0,
            request_key='profile',knowledge_version_id=imported.version_id,request=request())
        return first,second,profile
    first,second,profile=asyncio.run(seed())
    command.upgrade(config,CURRENT)
    async def run():
        try:
            args=dict(actor=ADMIN,case_id=case['case_id'],applicant_id=first['id'])
            assert (await profiles.read_applicant_profile(engine,**args,replay=True))['saved']==profile
            op=dict(action='save',confirmed=True,profile_id=profile['qualification_id'],passport_ref=None,document=document(as_of='2026-10-01'))
            row=await service.record_history(engine,**args,expected_revision=0,request_key='save',operation=op)
            assert (await service.read_history(engine,**args))['selected']==row
            sql='INSERT INTO entry_applicant_stay_history(case_id,applicant_id,profile_id,revision,previous_id,action,request_key,request_hash,snapshot_hash,command,provenance,created_by,created_at) SELECT :case,:person,:profile,:rev,:prev,action,:key,request_hash,snapshot_hash,command,provenance,created_by,created_at FROM entry_applicant_stay_history WHERE id=:id'
            for overrides in ({'case':other['case_id']},{'person':second['id']},{'profile':999},{'prev':999},{'rev':1,'prev':None},{'rev':251}):
                params=dict(case=case['case_id'],person=first['id'],profile=profile['qualification_id'],rev=2,prev=row['id'],key='invalid',id=row['id'])|overrides
                async with engine.begin() as conn:
                    with pytest.raises(IntegrityError):await conn.execute(text(sql),params)
        finally:await engine.dispose()
    asyncio.run(run())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
    engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:
            assert TABLE in inspect(conn).get_table_names()
            assert conn.scalar(text('SELECT count(*) FROM entry_applicant_stay_history'))==1
            assert conn.scalar(text('SELECT count(*) FROM entry_applicant_profiles'))==1
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))==CURRENT
    finally:engine.dispose()


def test_postgres_ddl_and_offline_refusal(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused');config.output_buffer=io.StringIO()
    command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1
    assert 'FOREIGN KEY(profile_id, applicant_id, case_id)' in ddl
    assert 'FOREIGN KEY(previous_id, applicant_id, case_id)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
