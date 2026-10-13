"""Append publication audit and scoped evidence bindings. No source promotion."""
import sqlalchemy as sa
from alembic import op

revision = 'e6_kb_publication_0024'
down_revision = 'e6_kb_decisions_0023'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('knowledge_publication_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('set_id', sa.Integer(), sa.ForeignKey('knowledge_sets.id'), nullable=False),
        sa.Column('version_id', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('previous_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(16), nullable=False),
        sa.Column('request_key', sa.String(64), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('snapshot_hash', sa.String(64), nullable=False),
        sa.Column('command', sa.JSON(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('id', 'set_id', name='uq_knowledge_publication_set'),
        sa.UniqueConstraint('id', 'version_id', name='uq_knowledge_publication_version'),
        sa.UniqueConstraint('set_id', 'revision', name='uq_knowledge_publication_revision'),
        sa.UniqueConstraint('set_id', 'request_key', name='uq_knowledge_publication_request'),
        sa.ForeignKeyConstraint(['version_id', 'set_id'], ['knowledge_versions.id', 'knowledge_versions.set_id'], name='fk_knowledge_publication_version'),
        sa.ForeignKeyConstraint(['previous_id', 'set_id'], ['knowledge_publication_events.id', 'knowledge_publication_events.set_id'], name='fk_knowledge_publication_previous'),
        sa.CheckConstraint('revision BETWEEN 1 AND 250', name='ck_knowledge_publication_revision'),
        sa.CheckConstraint("action IN ('review','approve','activate','rollback','withdraw')", name='ck_knowledge_publication_action'),
        sa.CheckConstraint('(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)', name='ck_knowledge_publication_previous'),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_knowledge_publication_hashes'))
    op.create_table('knowledge_publication_units',
        sa.Column('event_id', sa.Integer(), primary_key=True),
        sa.Column('unit_id', sa.Text(), primary_key=True),
        sa.Column('version_id', sa.Integer(), nullable=False),
        sa.Column('decision_id', sa.Integer(), nullable=True),
        sa.Column('unit_hash', sa.String(64), nullable=False),
        sa.Column('decision_hash', sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(['event_id', 'version_id'], ['knowledge_publication_events.id', 'knowledge_publication_events.version_id'], name='fk_knowledge_publication_unit_event'),
        sa.ForeignKeyConstraint(['version_id', 'unit_id'], ['knowledge_units.version_id', 'knowledge_units.unit_id'], name='fk_knowledge_publication_unit_source'),
        sa.ForeignKeyConstraint(['decision_id', 'version_id', 'unit_id'], ['knowledge_decisions.id', 'knowledge_decisions.version_id', 'knowledge_decisions.unit_id'], name='fk_knowledge_publication_unit_decision'),
        sa.CheckConstraint('length(unit_hash) = 64 AND (decision_hash IS NULL OR length(decision_hash) = 64)', name='ck_knowledge_publication_unit_hashes'),
        sa.CheckConstraint('(decision_id IS NULL) = (decision_hash IS NULL)', name='ck_knowledge_publication_unit_decision'))


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError('offline downgrade cannot verify publication audit is empty')
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        bind.execute(sa.text('LOCK TABLE knowledge_publication_events, knowledge_publication_units IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name == 'sqlite':
        if not bind.connection.driver_connection.in_transaction:
            bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            bind.exec_driver_sql('UPDATE knowledge_publication_events SET id = id WHERE 0')
    if any(bind.scalar(sa.text('SELECT count(*) FROM ' + table)) for table in ('knowledge_publication_events', 'knowledge_publication_units')):
        raise RuntimeError('preserve populated knowledge publication audit')
    op.drop_table('knowledge_publication_units')
    op.drop_table('knowledge_publication_events')
