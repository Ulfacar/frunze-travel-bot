import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_applicant_stay_0035'
CURRENT='e6_dialogue_cause_0036'
TABLE='entry_dialogue_stop_causes'


def test_additive_cycle_and_schema_parity(config):
    command.upgrade(config,PREVIOUS)
    engine=create_engine(config.get_main_option('sqlalchemy.url'))
    def existing(conn):
        return {n:s for n,s in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
            if n not in ('alembic_version',TABLE) and TABLE not in (s or '')}
    try:
        with engine.begin() as c:
            c.execute(text('INSERT INTO contacts(id) VALUES (54321)'));before=existing(c)
        for fn,target in ((command.upgrade,CURRENT),(command.downgrade,PREVIOUS),(command.upgrade,CURRENT)):
            fn(config,target)
            with engine.connect() as c:
                assert existing(c)==before and c.scalar(text('SELECT id FROM contacts WHERE id=54321'))==54321
        with engine.connect() as c:
            context=MigrationContext.configure(c,opts={'compare_type':True,
                'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name==TABLE})
            assert compare_metadata(context,DomainBase.metadata)==[]
            # Deliberate raw synthetic row checks the downgrade guard before any
            # table drop. FK behavior is covered by normal migrated PG receipts.
            c.execute(text("INSERT INTO entry_dialogue_stop_causes(id,transport_key,revision,previous_id,case_id,applicant_id,interview_id,stop_id,event_id,message_key,input_hash,snapshot_hash,document,created_at) VALUES(1,:h,1,NULL,1,1,1,1,1,:h,:h,:h,'{}','2026-10-12')"),{'h':'a'*64});c.commit()
        with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
        with engine.connect() as c:
            assert TABLE in inspect(c).get_table_names()
            assert c.scalar(text('SELECT count(*) FROM entry_dialogue_stop_causes'))==1
    finally:engine.dispose()


def test_postgres_ddl_and_offline_refusal(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused');config.output_buffer=io.StringIO()
    command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1
    assert 'FOREIGN KEY(interview_id, case_id, applicant_id)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):
        command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
