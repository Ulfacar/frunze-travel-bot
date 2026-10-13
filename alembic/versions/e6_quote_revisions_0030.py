"""Add immutable internal quote revisions; no existing data or ledger changes."""
import sqlalchemy as sa
from alembic import op

revision='e6_quote_revisions_0030'
down_revision='e6_interview_handoff_0029'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('entry_quote_revisions',
        sa.Column('id',sa.Integer(),nullable=False),
        sa.Column('application_id',sa.Integer(),nullable=False),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('procedure',sa.String(32),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('previous_id',sa.Integer(),nullable=True),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('policy',sa.JSON(),nullable=False),
        sa.Column('source_pin',sa.JSON(),nullable=False),
        sa.Column('result',sa.JSON(),nullable=False),
        sa.Column('authority',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('id','application_id','case_id',name='uq_entry_quote_scope'),
        sa.UniqueConstraint('application_id','revision',name='uq_entry_quote_revision'),
        sa.UniqueConstraint('case_id','request_key',name='uq_entry_quote_request'),
        sa.ForeignKeyConstraint(['application_id','case_id','applicant_id','procedure'],['entry_applications.id','entry_applications.case_id','entry_applications.applicant_id','entry_applications.procedure'],name='fk_entry_quote_subject'),
        sa.ForeignKeyConstraint(['previous_id','application_id','case_id'],['entry_quote_revisions.id','entry_quote_revisions.application_id','entry_quote_revisions.case_id'],name='fk_entry_quote_previous'),
        sa.CheckConstraint('revision BETWEEN 1 AND 128',name='ck_entry_quote_revision'),
        sa.CheckConstraint('(revision=1 AND previous_id IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<id)',name='ck_entry_quote_previous'),
        sa.CheckConstraint('length(request_hash)=64 AND length(snapshot_hash)=64',name='ck_entry_quote_hashes'))


def downgrade():
    context=op.get_context()
    if context.as_sql:raise RuntimeError('offline downgrade cannot verify empty quote history')
    connection=op.get_bind()
    if connection.dialect.name=='postgresql':
        connection.execute(sa.text('LOCK TABLE entry_quote_revisions IN ACCESS EXCLUSIVE MODE'))
    elif connection.dialect.name=='sqlite':
        # A zero-row write reserves SQLite's writer lock without changing evidence.
        connection.execute(sa.text('UPDATE entry_quote_revisions SET id=id WHERE 1=0'))
    else:raise RuntimeError('unsupported quote downgrade dialect')
    if connection.scalar(sa.text('SELECT count(*) FROM entry_quote_revisions')):
        raise RuntimeError('preserve populated quote history')
    op.drop_table('entry_quote_revisions')
