"""Only synthetic local migration rehearsal; no production DSN or real data."""
import asyncio
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS = 'e5_qualification_0016'
CURRENT = 'e6_applications_0017'
TABLES = {'entry_applicants', 'entry_applications', 'entry_application_events', 'entry_application_references'}


def schema(conn):
    return {name: sql for name, sql in conn.execute(text("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL")).all()
            if 'entry_applicant' not in name and 'entry_application' not in name}


def seed(conn):
    conn.execute(text('INSERT INTO contacts(id) VALUES (1)'))
    conn.execute(text("INSERT INTO products(id,code,name,direction,active,created_at,updated_at) VALUES (1,'test','Synthetic','visa',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
    conn.execute(text("INSERT INTO workflow_versions(id,product_id,version,stages,transitions,created_at) VALUES (1,1,1,'[]','{}',CURRENT_TIMESTAMP)"))
    conn.execute(text("INSERT INTO service_cases(id,contact_id,product_id,workflow_version_id,owner_login,stage,revision,created_at,updated_at) VALUES (1,1,1,1,'admin','test',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))


def test_additive_empty_cycle_and_model_parity(config):
    command.upgrade(config, PREVIOUS)
    engine = create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.begin() as conn:
            seed(conn); before = schema(conn)
        for operation, target in ((command.upgrade, CURRENT), (command.downgrade, PREVIOUS), (command.upgrade, CURRENT)):
            operation(config, target)
            with engine.connect() as conn:
                assert schema(conn) == before
                assert conn.scalar(text('SELECT contact_id FROM service_cases WHERE id=1')) == 1
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={'compare_type': True, 'compare_server_default': True,
                'include_object': lambda obj, name, kind, reflected, other: kind != 'table' or name in TABLES})
            assert compare_metadata(ctx, DomainBase.metadata) == []
            assert all(conn.scalar(text(f'SELECT count(*) FROM {table}')) == 0 for table in TABLES)
    finally: engine.dispose()


def test_populated_downgrade_refuses_before_drop(config):
    command.upgrade(config, CURRENT)
    engine = create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.begin() as conn:
            seed(conn)
            conn.execute(text("INSERT INTO entry_applicants(id,case_id,ordinal,role,request_key,request_hash,snapshot_hash,created_by,created_at) VALUES (1,1,1,'unknown','synthetic',:hash,:hash,'admin',CURRENT_TIMESTAMP)"), {'hash': 'a' * 64})
        with pytest.raises(RuntimeError, match='preserve populated'): command.downgrade(config, PREVIOUS)
        with engine.connect() as conn:
            assert TABLES <= set(inspect(conn).get_table_names())
            assert conn.scalar(text('SELECT count(*) FROM entry_applicants')) == 1
            assert conn.scalar(text('SELECT version_num FROM alembic_version')) == CURRENT
    finally: engine.dispose()


def test_postgresql_ddl_contains_scoped_foreign_keys_without_backfill(config):
    config.set_main_option('sqlalchemy.url', 'postgresql+asyncpg://localhost/unused')
    config.output_buffer = io.StringIO()
    command.upgrade(config, f'{PREVIOUS}:{CURRENT}', sql=True)
    ddl = config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ') == 4
    assert 'FOREIGN KEY(applicant_id, case_id) REFERENCES entry_applicants (id, case_id)' in ddl
    assert 'FOREIGN KEY(previous_id, case_id, applicant_id, procedure)' in ddl
    assert 'UNIQUE (application_id, revision)' in ddl and 'UNIQUE (reference)' in ddl
    assert all(word not in ddl for word in ('ALTER TABLE', 'DROP TABLE', 'DELETE FROM', 'INSERT INTO'))
    with pytest.raises(RuntimeError, match='offline downgrade'): command.downgrade(config, f'{CURRENT}:{PREVIOUS}', sql=True)


def test_operations_on_migrated_database(config):
    from app.domain import entry_applications as service
    from app.domain.permissions import Actor
    from tests.test_admin_workday import _seed_case
    command.upgrade(config, CURRENT)
    engine = create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:', 'sqlite+aiosqlite:', 1), poolclass=NullPool)
    def enable(dbapi, record):
        cursor = dbapi.cursor(); cursor.execute('PRAGMA foreign_keys=ON'); cursor.close()
    event.listen(engine.sync_engine, 'connect', enable)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    case = _seed_case(sm, owner='admin', reference='migration-synthetic', direction='visa')
    async def run():
        try:
            args = dict(actor=Actor('admin', True), case_id=case['case_id'])
            person = await service.add_applicant(engine, **args, role='primary', request_key='person')
            app = await service.open_application(engine, **args, applicant_id=person['id'], procedure='visa', request_key='app')
            await service.record_application_event(engine, **args, application_id=app['id'], expected_revision=1,
                request_key='submit', status='submitted', occurred_on='2026-09-01', source='portal', reference='AB12CD34', confirmed=True)
            assert (await service.read_application(engine, **args, application_id=app['id']))['current']['reference'] == 'AB12CD34'
        finally: await engine.dispose()
    asyncio.run(run())


def test_database_rejects_cross_case_subject_retry_and_duplicate_reference(config):
    command.upgrade(config, CURRENT)
    engine = create_engine(config.get_main_option('sqlalchemy.url'))
    stamp = "'k','" + 'a' * 64 + "','" + 'b' * 64 + "','admin',CURRENT_TIMESTAMP"
    try:
        with engine.begin() as conn:
            conn.execute(text('PRAGMA foreign_keys=ON'))
            assert conn.scalar(text('PRAGMA foreign_keys')) == 1
            seed(conn)
            conn.execute(text("INSERT INTO service_cases(id,contact_id,product_id,workflow_version_id,owner_login,stage,revision,created_at,updated_at) VALUES (2,1,1,1,'admin','test',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            for i in (1, 2):
                conn.execute(text(f"INSERT INTO entry_applicants(id,case_id,ordinal,role,request_key,request_hash,snapshot_hash,created_by,created_at) VALUES ({i},{i},1,'unknown',{stamp})"))
            columns = 'id,case_id,applicant_id,procedure,attempt,previous_id,request_key,request_hash,snapshot_hash,created_by,created_at'
            with pytest.raises(IntegrityError):
                conn.execute(text(f"INSERT INTO entry_applications({columns}) VALUES (1,1,2,'visa',1,NULL,{stamp})"))
            conn.execute(text(f"INSERT INTO entry_applications({columns}) VALUES (1,1,1,'visa',1,NULL,{stamp})"))
            with pytest.raises(IntegrityError):
                conn.execute(text(f"INSERT INTO entry_applications({columns}) VALUES (2,2,2,'visa',2,1,{stamp})"))
            conn.execute(text(f"INSERT INTO entry_applications({columns}) VALUES (2,2,2,'visa',1,NULL,{stamp})"))
            conn.execute(text("INSERT INTO entry_application_references VALUES (1,1,'AB12CD34')"))
            with pytest.raises(IntegrityError):
                conn.execute(text("INSERT INTO entry_application_references VALUES (2,2,'AB12CD34')"))
            with pytest.raises(IntegrityError):
                conn.execute(text("INSERT INTO entry_application_references VALUES (2,1,'XY98PQ76')"))
    finally: engine.dispose()
