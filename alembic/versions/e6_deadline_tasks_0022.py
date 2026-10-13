"""Bind internal CalendarTasks to application deadline evidence; no backfill."""
import sqlalchemy as sa
from alembic import op

revision = 'e6_deadline_tasks_0022'
down_revision = 'e6_deadlines_0021'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('entry_deadline_tasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('rule_unit_id', sa.String(80), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('deadline_revision_id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('calendar_tasks.id'), nullable=True),
        sa.Column('source_hash', sa.String(64), nullable=False),
        sa.Column('target_hash', sa.String(64), nullable=False),
        sa.Column('expected_date', sa.Date(), nullable=True),
        sa.Column('attention', sa.String(32), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('updated_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('application_id', 'rule_unit_id', 'generation', name='uq_entry_deadline_task_generation'),
        sa.UniqueConstraint('task_id', name='uq_entry_deadline_task_identity'),
        sa.ForeignKeyConstraint(['application_id', 'case_id'], ['entry_applications.id', 'entry_applications.case_id'], name='fk_entry_deadline_task_application'),
        sa.ForeignKeyConstraint(['deadline_revision_id', 'application_id', 'case_id', 'rule_unit_id'],
            ['entry_deadline_revisions.id', 'entry_deadline_revisions.application_id', 'entry_deadline_revisions.case_id', 'entry_deadline_revisions.rule_unit_id'], name='fk_entry_deadline_task_source'),
        sa.CheckConstraint('generation BETWEEN 1 AND 250 AND revision >= 1', name='ck_entry_deadline_task_revision'),
        sa.CheckConstraint('length(source_hash) = 64 AND length(target_hash) = 64', name='ck_entry_deadline_task_hashes'),
        sa.CheckConstraint("attention IN ('','unknown_date','missing_owner','claimed','schedule_conflict','generation_limit')", name='ck_entry_deadline_task_attention'))
    op.create_index('ix_entry_deadline_task_sweep', 'entry_deadline_tasks', ['case_id', 'generation', 'id'])


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError('offline downgrade cannot verify deadline task bindings are empty')
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        bind.execute(sa.text('LOCK TABLE entry_deadline_tasks IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name == 'sqlite':
        if not bind.connection.driver_connection.in_transaction:
            bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            bind.exec_driver_sql('UPDATE entry_deadline_tasks SET id = id WHERE 0')
    if bind.scalar(sa.text('SELECT count(*) FROM entry_deadline_tasks')):
        raise RuntimeError('preserve populated deadline task bindings and audit')
    op.drop_table('entry_deadline_tasks')
