import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine,text

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_dialogue_cause_0036'
CURRENT='e6_dialogue_session_0037'
TABLES={'entry_dialogue_sessions','entry_dialogue_events'}


def test_additive_empty_roundtrip_and_model_parity(config):
    command.upgrade(config,PREVIOUS)
    engine=create_engine(config.get_main_option('sqlalchemy.url'))
    def old_schema():
        with engine.connect() as conn:
            return {n:s for n,s in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
                if n!='alembic_version' and n not in TABLES and not any(t in s for t in TABLES)}
    try:
        before=old_schema()
        for operation,target in ((command.upgrade,CURRENT),(command.downgrade,PREVIOUS),(command.upgrade,CURRENT)):
            operation(config,target);assert old_schema()==before
        with engine.connect() as conn:
            context=MigrationContext.configure(conn,opts={'compare_type':True,
                'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name in TABLES})
            assert compare_metadata(context,DomainBase.metadata)==[]
    finally:engine.dispose()


def test_postgres_ddl_and_offline_downgrade_refusal(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,PREVIOUS+':'+CURRENT,sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==2 and 'UNIQUE (transport_key)' in ddl
    assert 'UNIQUE (session_id, request_key)' in ddl and 'fk_dialogue_session_subject' in ddl
    assert all(v not in ddl for v in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,CURRENT+':'+PREVIOUS,sql=True)
