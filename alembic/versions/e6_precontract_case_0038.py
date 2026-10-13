"""Retained preliminary opening identity, without changing existing contracts."""
import sqlalchemy as sa
from alembic import op

revision='e6_precontract_case_0038'
down_revision='e6_dialogue_session_0037'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('service_case_openings',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('case_id',sa.Integer(),sa.ForeignKey('service_cases.id'),nullable=False),
        sa.Column('request_key',sa.String(128),nullable=False),
        sa.Column('document',sa.JSON(),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('request_key',name='uq_case_opening_request'),
        sa.UniqueConstraint('case_id',name='uq_case_opening_case'),
        sa.CheckConstraint('length(request_key) BETWEEN 1 AND 128',name='ck_case_opening_key'),
        sa.CheckConstraint('length(snapshot_hash)=64',name='ck_case_opening_hash'))


def downgrade():
    if op.get_context().as_sql:raise RuntimeError('offline downgrade cannot verify opening receipts')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql':
        bind.execute(sa.text('LOCK TABLE service_case_openings IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction:bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:bind.exec_driver_sql('UPDATE service_case_openings SET id=id WHERE 0')
    else:raise RuntimeError('unsupported opening migration database')
    if bind.scalar(sa.text('SELECT count(*) FROM service_case_openings')):
        raise RuntimeError('preserve populated preliminary opening receipts')
    op.drop_table('service_case_openings')
