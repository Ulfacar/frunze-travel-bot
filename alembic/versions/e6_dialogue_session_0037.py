"""Durable typed dialogue evidence; default-empty deployment authority."""
import sqlalchemy as sa
from alembic import op

revision='e6_dialogue_session_0037'
down_revision='e6_dialogue_cause_0036'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('entry_dialogue_sessions',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('transport_key',sa.String(64),nullable=False),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('interview_id',sa.Integer(),nullable=False),
        sa.Column('document',sa.JSON(),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('transport_key',name='uq_dialogue_session_route'),
        sa.UniqueConstraint('interview_id',name='uq_dialogue_session_interview'),
        sa.ForeignKeyConstraint(['interview_id','case_id','applicant_id'],['entry_interviews.id','entry_interviews.case_id','entry_interviews.applicant_id'],name='fk_dialogue_session_subject'),
        sa.CheckConstraint('length(transport_key)=64 AND length(snapshot_hash)=64',name='ck_dialogue_session_hashes'))
    op.create_table('entry_dialogue_events',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('session_id',sa.Integer(),sa.ForeignKey('entry_dialogue_sessions.id'),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('previous_id',sa.Integer(),sa.ForeignKey('entry_dialogue_events.id'),nullable=True),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('kind',sa.String(16),nullable=False),
        sa.Column('document',sa.JSON(),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('session_id','revision',name='uq_dialogue_event_revision'),
        sa.UniqueConstraint('session_id','request_key',name='uq_dialogue_event_request'),
        sa.CheckConstraint('revision BETWEEN 1 AND 1024',name='ck_dialogue_event_revision'),
        sa.CheckConstraint('(revision=1 AND previous_id IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<id)',name='ck_dialogue_event_previous'),
        sa.CheckConstraint("kind IN ('prompt','turn','claim','outcome','stop')",name='ck_dialogue_event_kind'),
        sa.CheckConstraint('length(snapshot_hash)=64',name='ck_dialogue_event_hash'))


def downgrade():
    if op.get_context().as_sql:raise RuntimeError('offline downgrade cannot verify dialogue history')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql':
        bind.execute(sa.text('LOCK TABLE entry_dialogue_sessions,entry_dialogue_events IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction:bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:bind.exec_driver_sql('UPDATE entry_dialogue_sessions SET id=id WHERE 0')
    else:raise RuntimeError('unsupported dialogue migration database')
    if any(bind.scalar(sa.text('SELECT count(*) FROM '+name)) for name in ('entry_dialogue_sessions','entry_dialogue_events')):
        raise RuntimeError('preserve populated typed dialogue history')
    op.drop_table('entry_dialogue_events')
    op.drop_table('entry_dialogue_sessions')
