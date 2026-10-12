"""Add connected interruption provenance; no channel is activated."""
import sqlalchemy as sa
from alembic import op

revision='e6_dialogue_cause_0036'
down_revision='e6_applicant_stay_0035'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('entry_dialogue_stop_causes',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('transport_key',sa.String(64),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('previous_id',sa.Integer(),sa.ForeignKey('entry_dialogue_stop_causes.id'),nullable=True),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('interview_id',sa.Integer(),nullable=False),
        sa.Column('stop_id',sa.Integer(),sa.ForeignKey('entry_channel_stops.id'),nullable=False),
        sa.Column('event_id',sa.Integer(),sa.ForeignKey('entry_interview_events.id'),nullable=False),
        sa.Column('message_key',sa.String(64),nullable=False),
        sa.Column('input_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('document',sa.JSON(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('transport_key','revision',name='uq_dialogue_cause_revision'),
        sa.UniqueConstraint('transport_key','message_key',name='uq_dialogue_cause_message'),
        sa.ForeignKeyConstraint(['interview_id','case_id','applicant_id'],['entry_interviews.id','entry_interviews.case_id','entry_interviews.applicant_id'],name='fk_dialogue_cause_subject'),
        sa.CheckConstraint('revision BETWEEN 1 AND 2',name='ck_dialogue_cause_revision'),
        sa.CheckConstraint('(revision=1 AND previous_id IS NULL) OR (revision=2 AND previous_id IS NOT NULL AND previous_id<id)',name='ck_dialogue_cause_previous'),
        sa.CheckConstraint('length(transport_key)=64 AND length(message_key)=64 AND length(input_hash)=64 AND length(snapshot_hash)=64',name='ck_dialogue_cause_hashes'))


def downgrade():
    if op.get_context().as_sql:raise RuntimeError('offline downgrade cannot verify connected stop history')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql':
        bind.execute(sa.text('LOCK TABLE entry_dialogue_stop_causes IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction:bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:bind.exec_driver_sql('UPDATE entry_dialogue_stop_causes SET id=id WHERE 0')
    else:raise RuntimeError('unsupported dialogue migration database')
    if bind.scalar(sa.text('SELECT count(*) FROM entry_dialogue_stop_causes')):
        raise RuntimeError('preserve populated connected stop history')
    op.drop_table('entry_dialogue_stop_causes')
