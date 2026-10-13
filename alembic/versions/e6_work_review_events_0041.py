"""Separate conditional work-review receipts; no source approval or backfill."""
import sqlalchemy as sa
from alembic import op

revision='e6_work_review_events_0041'
down_revision='e6_work_process_evidence_0040'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('entry_work_review_events',
        sa.Column('id',sa.Integer(),nullable=False),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('application_id',sa.Integer(),nullable=False),
        sa.Column('procedure',sa.String(32),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('previous_id',sa.Integer(),nullable=True),
        sa.Column('task_id',sa.Integer(),nullable=True),
        sa.Column('action',sa.String(20),nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('id','application_id','case_id','applicant_id',name='uq_work_review_scope'),
        sa.UniqueConstraint('application_id','revision',name='uq_work_review_revision'),
        sa.UniqueConstraint('case_id','request_key',name='uq_work_review_request'),
        sa.ForeignKeyConstraint(['application_id','case_id','applicant_id','procedure'],
            ['entry_applications.id','entry_applications.case_id','entry_applications.applicant_id','entry_applications.procedure'],name='fk_work_review_subject'),
        sa.ForeignKeyConstraint(['previous_id','application_id','case_id','applicant_id'],
            ['entry_work_review_events.id','entry_work_review_events.application_id','entry_work_review_events.case_id','entry_work_review_events.applicant_id'],name='fk_work_review_previous'),
        sa.ForeignKeyConstraint(['task_id'],['calendar_tasks.id']),
        sa.CheckConstraint("procedure='unified_permit'",name='ck_work_review_procedure'),
        sa.CheckConstraint('revision BETWEEN 1 AND 65',name='ck_work_review_revision'),
        sa.CheckConstraint("action IN ('refresh','restore','new_generation','complete','cancel')",name='ck_work_review_action'),
        sa.CheckConstraint('(revision=1 AND previous_id IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<id)',name='ck_work_review_previous'),
        sa.CheckConstraint('length(request_hash)=64 AND length(snapshot_hash)=64',name='ck_work_review_hashes'))
    op.create_index('ix_entry_work_review_events_task_id','entry_work_review_events',['task_id'])


def downgrade():
    if op.get_context().as_sql:raise RuntimeError('offline downgrade cannot verify empty work review history')
    connection=op.get_bind()
    if connection.dialect.name=='postgresql':connection.execute(sa.text('LOCK TABLE entry_work_review_events IN ACCESS EXCLUSIVE MODE'))
    elif connection.dialect.name=='sqlite':connection.execute(sa.text('UPDATE entry_work_review_events SET id=id WHERE 1=0'))
    else:raise RuntimeError('unsupported work review downgrade dialect')
    if connection.scalar(sa.text('SELECT count(*) FROM entry_work_review_events')):
        raise RuntimeError('preserve populated work review history')
    op.drop_index('ix_entry_work_review_events_task_id',table_name='entry_work_review_events')
    op.drop_table('entry_work_review_events')
