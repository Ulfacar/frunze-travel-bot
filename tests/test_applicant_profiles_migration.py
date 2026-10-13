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

PREVIOUS = 'e6_issued_0019'
CURRENT = 'e6_profiles_0020'
TABLE = 'entry_applicant_profiles'


def schema(conn):
    return {n:s for n,s in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
            if n not in ('alembic_version',TABLE) and TABLE not in (s or '')}


def test_additive_cycle_and_model_parity(config):
    command.upgrade(config, PREVIOUS)
    engine = create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn: before = schema(conn)
        for fn,target in ((command.upgrade,CURRENT),(command.downgrade,PREVIOUS),(command.upgrade,CURRENT)):
            fn(config,target)
            with engine.connect() as conn: assert schema(conn) == before
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={'compare_type':True,
                'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name==TABLE})
            assert compare_metadata(ctx, DomainBase.metadata) == []
    finally: engine.dispose()


def test_migrated_operations_scope_previous_and_populated_downgrade(config):
    from app.domain import applicant_profiles as profiles, entry_applications as apps
    from app.domain.knowledge_import import create_kg_entry_set, import_bundle
    from tests.test_admin_workday import _seed_case
    from tests.test_admin_kg_entry import ADMIN, FIX
    from tests.test_applicant_profiles import request
    command.upgrade(config,CURRENT)
    engine = create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:', 'sqlite+aiosqlite:', 1), poolclass=NullPool)
    def enable(dbapi, record):
        cursor=dbapi.cursor();cursor.execute('PRAGMA foreign_keys=ON');cursor.close()
    event.listen(engine.sync_engine, 'connect', enable)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    case = _seed_case(sm, owner='admin', reference='synthetic-profile', direction='visa')
    other_case = _seed_case(sm, owner='admin', reference='synthetic-other', direction='visa')
    async def run():
        try:
            set_id = await create_kg_entry_set(engine, actor=ADMIN)
            imported = await import_bundle(engine, actor=ADMIN, set_id=set_id,
                directory=FIX/'synthetic_bundle', source=FIX/'synthetic_source.txt')
            assert imported.accepted
            args = dict(actor=ADMIN, case_id=case['case_id'])
            first = await apps.add_applicant(engine, **args, role='primary', request_key='person')
            second = await apps.add_applicant(engine, **args, role='child', request_key='child')
            row = await profiles.save_applicant_profile(engine, **args, applicant_id=first['id'], expected_revision=0,
                request_key='save', knowledge_version_id=imported.version_id, request=request())
            assert (await profiles.read_applicant_profile(engine, **args, applicant_id=first['id'], replay=True))['saved'] == row
            sql = "INSERT INTO entry_applicant_profiles(case_id,applicant_id,revision,previous_id,knowledge_version_id,request_key,request_hash,snapshot_hash,input_snapshot,result_snapshot,provenance,created_by,created_at) SELECT :case,:person,:rev,:prev,knowledge_version_id,:key,request_hash,snapshot_hash,input_snapshot,result_snapshot,provenance,created_by,created_at FROM entry_applicant_profiles WHERE id=:id"
            for overrides in ({'case':other_case['case_id']}, {'person':second['id']}, {'prev':999}, {'rev':1, 'prev':None}, {'rev':251}):
                params = dict(case=case['case_id'], person=first['id'], rev=2, prev=row['qualification_id'], key='invalid', id=row['qualification_id'])
                params.update(overrides)
                async with engine.begin() as conn:
                    with pytest.raises(IntegrityError): await conn.execute(text(sql), params)
        finally: await engine.dispose()
    asyncio.run(run())
    with pytest.raises(RuntimeError, match='preserve populated'): command.downgrade(config,PREVIOUS)
    engine = create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:
            assert TABLE in inspect(conn).get_table_names()
            assert conn.scalar(text('SELECT count(*) FROM entry_applicant_profiles')) == 1
            assert conn.scalar(text('SELECT version_num FROM alembic_version')) == CURRENT
    finally: engine.dispose()


def test_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url', 'postgresql+asyncpg://localhost/unused')
    config.output_buffer = io.StringIO()
    command.upgrade(config, f'{PREVIOUS}:{CURRENT}', sql=True)
    ddl = config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ') == 1
    assert 'FOREIGN KEY(applicant_id, case_id) REFERENCES entry_applicants (id, case_id)' in ddl
    assert 'FOREIGN KEY(previous_id, applicant_id, case_id)' in ddl
    assert 'UNIQUE (applicant_id, request_key)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError, match='offline downgrade'): command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
