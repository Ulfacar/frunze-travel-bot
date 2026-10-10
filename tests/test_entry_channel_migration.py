import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine,text

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_quote_revisions_0030'
CURRENT='e6_channel_stops_0031'
TABLE='entry_channel_stops'


def schema(conn):
    return {n:s for n,s in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
        if n!='alembic_version' and n!=TABLE and TABLE not in s}


def test_additive_sqlite_empty_cycle_and_model_parity(config):
    command.upgrade(config,PREVIOUS);engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:before=schema(conn)
        for fn,target in ((command.upgrade,CURRENT),(command.downgrade,PREVIOUS),(command.upgrade,CURRENT)):
            fn(config,target)
            with engine.connect() as conn:assert schema(conn)==before
        with engine.connect() as conn:
            context=MigrationContext.configure(conn,opts={'compare_type':True,'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name==TABLE})
            assert compare_metadata(context,DomainBase.metadata)==[]
    finally:engine.dispose()


def test_postgres_additive_ddl_and_offline_downgrade_refusal(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused');config.output_buffer=io.StringIO()
    command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True);ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1 and 'UNIQUE (transport_key)' in ddl
    assert 'FOREIGN KEY(handoff_event_id, interview_id, case_id, applicant_id)' in ddl
    assert all(column+' JSON' in ddl for column in ('command','policy','route','source_pin','authority'))
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
