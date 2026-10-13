"""Append knowledge review evidence without editing source or active pointers."""
import sqlalchemy as sa
from alembic import op

revision='e6_kb_decisions_0023'
down_revision='e6_deadline_tasks_0022'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('knowledge_decisions',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('version_id',sa.Integer(),nullable=False),
        sa.Column('unit_id',sa.Text(),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('previous_id',sa.Integer(),nullable=True),
        sa.Column('unit_hash',sa.String(64),nullable=False),
        sa.Column('bundle_hash',sa.String(64),nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','version_id','unit_id',name='uq_knowledge_decision_scope'),
        sa.UniqueConstraint('version_id','unit_id','revision',name='uq_knowledge_decision_revision'),
        sa.UniqueConstraint('version_id','unit_id','request_key',name='uq_knowledge_decision_request'),
        sa.ForeignKeyConstraint(['version_id','unit_id'],['knowledge_units.version_id','knowledge_units.unit_id'],name='fk_knowledge_decision_unit'),
        sa.ForeignKeyConstraint(['previous_id','version_id','unit_id'],['knowledge_decisions.id','knowledge_decisions.version_id','knowledge_decisions.unit_id'],name='fk_knowledge_decision_previous'),
        sa.CheckConstraint('revision BETWEEN 1 AND 250',name='ck_knowledge_decision_revision'),
        sa.CheckConstraint('(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)',name='ck_knowledge_decision_previous'),
        sa.CheckConstraint('length(unit_hash) = 64 AND length(bundle_hash) = 64 AND length(request_hash) = 64 AND length(snapshot_hash) = 64',name='ck_knowledge_decision_hashes'))


def downgrade():
    if op.get_context().as_sql:raise RuntimeError('offline downgrade cannot verify knowledge decisions are empty')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql':bind.execute(sa.text('LOCK TABLE knowledge_decisions IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction:bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:bind.exec_driver_sql('UPDATE knowledge_decisions SET id = id WHERE 0')
    if bind.scalar(sa.text('SELECT count(*) FROM knowledge_decisions')):raise RuntimeError('preserve populated knowledge decisions')
    op.drop_table('knowledge_decisions')
