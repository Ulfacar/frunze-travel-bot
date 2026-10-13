"""Nullable own-person stay pin, retaining every original process receipt."""
import sqlalchemy as sa
from alembic import op

revision = 'e6_work_process_evidence_0040'
down_revision = 'e6_specialist_decisions_0039'
branch_labels = None
depends_on = None

KINDS = ['application','application_event','package','issued','profile','attestation','payment','contract']
COLUMNS = ['application_event_id','package_event_id','issued_id','profile_id','attestation_id','payment_id','contract_event_id']


def checks(batch, added):
    kinds = KINDS + (['stay'] if added else [])
    columns = COLUMNS + (['stay_history_id'] if added else [])
    batch.create_check_constraint('ck_entry_process_pin_kind', 'kind IN (' + ','.join(repr(k) for k in kinds) + ')')
    batch.create_check_constraint('ck_entry_process_pin_one_source', '(' + ' + '.join(
        'CASE WHEN '+c+' IS NULL THEN 0 ELSE 1 END' for c in columns) + ") = CASE WHEN kind = 'application' THEN 0 ELSE 1 END")
    pairs = list(zip(KINDS[1:], COLUMNS)) + ([('stay','stay_history_id')] if added else [])
    batch.create_check_constraint('ck_entry_process_pin_source_kind', "kind = 'application' OR " + ' OR '.join(
        "(kind = '"+kind+"' AND "+column+' IS NOT NULL'+(' AND attestation_id < event_id' if kind=='attestation' else '')+')'
        for kind,column in pairs))


def replace_checks(batch, added):
    for name in ('kind','one_source','source_kind'):
        batch.drop_constraint('ck_entry_process_pin_'+name,type_='check')
    checks(batch,added)


def upgrade():
    with op.batch_alter_table('entry_process_pins') as batch:
        batch.add_column(sa.Column('stay_history_id',sa.Integer(),nullable=True))
        batch.create_foreign_key('fk_entry_process_pin_stay','entry_applicant_stay_history',
            ['stay_history_id','applicant_id','case_id'],['id','applicant_id','case_id'])
        replace_checks(batch,True)


def downgrade():
    if op.get_context().as_sql: raise RuntimeError('offline downgrade cannot verify work evidence is unused')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql': bind.execute(sa.text('LOCK TABLE entry_process_events, entry_process_pins IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction: bind.exec_driver_sql('BEGIN IMMEDIATE')
        else: bind.exec_driver_sql('UPDATE entry_process_events SET id=id WHERE 0')
    if bind.scalar(sa.text('SELECT count(*) FROM entry_process_pins WHERE stay_history_id IS NOT NULL')):
        raise RuntimeError('preserve populated work evidence')
    events=sa.table('entry_process_events',sa.column('snapshot',sa.JSON()))
    if bind.scalar(sa.select(sa.func.count()).select_from(events).where(events.c.snapshot['catalog_digest'].as_string()==
            '31a9bd02864b62621f2968139a6b90bc128889febfebe657001c959d96d09ee2')):
        raise RuntimeError('preserve populated work evidence')
    with op.batch_alter_table('entry_process_pins') as batch:
        batch.drop_constraint('fk_entry_process_pin_stay',type_='foreignkey')
        replace_checks(batch,False)
        batch.drop_column('stay_history_id')
