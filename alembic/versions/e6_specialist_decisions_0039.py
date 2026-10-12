"""Add immutable specialist planning; no existing data or monetary updates."""
import sqlalchemy as sa
from alembic import op

revision='e6_specialist_decisions_0039'
down_revision='e6_precontract_case_0038'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('specialist_decision_events',
        sa.Column('id',sa.Integer(),nullable=False),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('application_id',sa.Integer(),nullable=True),
        sa.Column('procedure',sa.String(32),nullable=True),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('previous_id',sa.Integer(),nullable=True),
        sa.Column('decision_id',sa.Integer(),nullable=True),
        sa.Column('quote_id',sa.Integer(),nullable=True),
        sa.Column('action',sa.String(16),nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('provenance',sa.JSON(),nullable=False),
        sa.Column('result',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('id','case_id','applicant_id',name='uq_specialist_scope'),
        sa.UniqueConstraint('applicant_id','revision',name='uq_specialist_revision'),
        sa.UniqueConstraint('case_id','request_key',name='uq_specialist_request'),
        sa.UniqueConstraint('quote_id',name='uq_specialist_quote'),
        sa.ForeignKeyConstraint(['applicant_id','case_id'],['entry_applicants.id','entry_applicants.case_id'],name='fk_specialist_person'),
        sa.ForeignKeyConstraint(['application_id','case_id','applicant_id','procedure'],['entry_applications.id','entry_applications.case_id','entry_applications.applicant_id','entry_applications.procedure'],name='fk_specialist_application'),
        sa.ForeignKeyConstraint(['previous_id','case_id','applicant_id'],['specialist_decision_events.id','specialist_decision_events.case_id','specialist_decision_events.applicant_id'],name='fk_specialist_previous'),
        sa.ForeignKeyConstraint(['decision_id','case_id','applicant_id'],['specialist_decision_events.id','specialist_decision_events.case_id','specialist_decision_events.applicant_id'],name='fk_specialist_decision'),
        sa.ForeignKeyConstraint(['quote_id','application_id','case_id'],['entry_quote_revisions.id','entry_quote_revisions.application_id','entry_quote_revisions.case_id'],name='fk_specialist_quote'),
        sa.CheckConstraint('revision BETWEEN 1 AND 64',name='ck_specialist_revision'),
        sa.CheckConstraint("(application_id IS NULL AND procedure IS NULL) OR (application_id IS NOT NULL AND procedure IS NOT NULL AND procedure='visa')",name='ck_specialist_procedure'),
        sa.CheckConstraint("action IN ('record','quote','withdraw')",name='ck_specialist_action'),
        sa.CheckConstraint('(revision=1 AND previous_id IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<id)',name='ck_specialist_previous'),
        sa.CheckConstraint("(action='record' AND decision_id IS NULL) OR (action IN ('quote','withdraw') AND decision_id IS NOT NULL AND decision_id<id)",name='ck_specialist_decision'),
        sa.CheckConstraint("(action='quote' AND quote_id IS NOT NULL AND application_id IS NOT NULL) OR (action!='quote' AND quote_id IS NULL)",name='ck_specialist_quote'),
        sa.CheckConstraint('length(request_hash)=64 AND length(snapshot_hash)=64',name='ck_specialist_hashes'))


def downgrade():
    if op.get_context().as_sql:raise RuntimeError('offline downgrade cannot verify empty specialist history')
    connection=op.get_bind()
    if connection.dialect.name=='postgresql':
        connection.execute(sa.text('LOCK TABLE specialist_decision_events IN ACCESS EXCLUSIVE MODE'))
    elif connection.dialect.name=='sqlite':
        connection.execute(sa.text('UPDATE specialist_decision_events SET id=id WHERE 1=0'))
    else:raise RuntimeError('unsupported specialist downgrade dialect')
    if connection.scalar(sa.text('SELECT count(*) FROM specialist_decision_events')):
        raise RuntimeError('preserve populated specialist history')
    op.drop_table('specialist_decision_events')
