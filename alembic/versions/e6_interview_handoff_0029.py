"""Immutable applicant interviews and handoff cards; no backfill or route enrollment."""
import sqlalchemy as sa
from alembic import op
revision = 'e6_interview_handoff_0029'
down_revision = 'e6_portal_observations_0028'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('entry_interviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('applicant_id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=True),
        sa.Column('owner_login', sa.String(64), nullable=False),
        sa.Column('request_key', sa.String(64), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('snapshot_hash', sa.String(64), nullable=False),
        sa.Column('command', sa.JSON(), nullable=False),
        sa.Column('policy', sa.JSON(), nullable=False),
        sa.Column('catalog', sa.JSON(), nullable=False),
        sa.Column('source_pin', sa.JSON(), nullable=False),
        sa.Column('authority', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('length(request_hash)=64 AND length(snapshot_hash)=64', name='ck_entry_interview_hashes'),
        sa.ForeignKeyConstraint(['case_id'], ['service_cases.id'], name=None),
        sa.ForeignKeyConstraint(['applicant_id', 'case_id'], ['entry_applicants.id', 'entry_applicants.case_id'], name='fk_entry_interview_applicant'),
        sa.ForeignKeyConstraint(['profile_id', 'applicant_id', 'case_id'], ['entry_applicant_profiles.id', 'entry_applicant_profiles.applicant_id', 'entry_applicant_profiles.case_id'], name='fk_entry_interview_profile'),
        sa.PrimaryKeyConstraint(*['id']),
        sa.UniqueConstraint(*['case_id', 'request_key'], name='uq_entry_interview_request'),
        sa.UniqueConstraint(*['id', 'case_id', 'applicant_id'], name='uq_entry_interview_scope'),
        sa.UniqueConstraint(*['case_id', 'applicant_id'], name='uq_entry_interview_subject'),
    )
    op.create_index('ix_entry_interview_case_id', 'entry_interviews', ['case_id', 'id'], unique=False)
    op.create_table('entry_interview_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('interview_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('applicant_id', sa.Integer(), nullable=False),
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
        sa.CheckConstraint('length(request_hash)=64 AND length(snapshot_hash)=64', name='ck_entry_interview_event_hashes'),
        sa.CheckConstraint("action IN ('start','answer','correct','remove','language','pause','resume','interrupt','handoff','ack','refresh')", name='ck_entry_interview_event_kind'),
        sa.CheckConstraint('(revision=1 AND previous_id IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<id)', name='ck_entry_interview_event_previous'),
        sa.CheckConstraint('revision BETWEEN 1 AND 256', name='ck_entry_interview_event_revision'),
        sa.ForeignKeyConstraint(['previous_id', 'interview_id', 'case_id', 'applicant_id'], ['entry_interview_events.id', 'entry_interview_events.interview_id', 'entry_interview_events.case_id', 'entry_interview_events.applicant_id'], name='fk_entry_interview_event_previous'),
        sa.ForeignKeyConstraint(['interview_id', 'case_id', 'applicant_id'], ['entry_interviews.id', 'entry_interviews.case_id', 'entry_interviews.applicant_id'], name='fk_entry_interview_event_subject'),
        sa.PrimaryKeyConstraint(*['id']),
        sa.UniqueConstraint(*['interview_id', 'request_key'], name='uq_entry_interview_event_request'),
        sa.UniqueConstraint(*['interview_id', 'revision'], name='uq_entry_interview_event_revision'),
        sa.UniqueConstraint(*['id', 'interview_id', 'case_id', 'applicant_id'], name='uq_entry_interview_event_scope'),
    )

def downgrade():
    if op.get_context().as_sql: raise RuntimeError('offline downgrade cannot verify interview history is empty')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql': bind.execute(sa.text('LOCK TABLE entry_interviews, entry_interview_events IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction: bind.exec_driver_sql('BEGIN IMMEDIATE')
        else: bind.exec_driver_sql('UPDATE entry_interviews SET id=id WHERE 0')
    for table in ('entry_interview_events','entry_interviews'):
        if bind.scalar(sa.text('SELECT count(*) FROM '+table)): raise RuntimeError('preserve populated interview history')
    op.drop_table('entry_interview_events')
    op.drop_index('ix_entry_interview_case_id',table_name='entry_interviews')
    op.drop_table('entry_interviews')
