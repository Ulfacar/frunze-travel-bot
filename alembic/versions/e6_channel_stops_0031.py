"""Add permanent exact-route stops; no backfill or live binding."""
import sqlalchemy as sa
from alembic import op

revision='e6_channel_stops_0031'
down_revision='e6_quote_revisions_0030'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('entry_channel_stops',
        sa.Column('id',sa.Integer(),nullable=False),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('interview_id',sa.Integer(),nullable=False),
        sa.Column('handoff_event_id',sa.Integer(),nullable=False),
        sa.Column('contact_id',sa.Integer(),nullable=False),
        sa.Column('dialog_id',sa.Integer(),nullable=False),
        sa.Column('transport_key',sa.String(64),nullable=False),
        sa.Column('card_hash',sa.String(64),nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('policy',sa.JSON(),nullable=False),
        sa.Column('route',sa.JSON(),nullable=False),
        sa.Column('source_pin',sa.JSON(),nullable=False),
        sa.Column('authority',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transport_key',name='uq_entry_channel_stop_transport'),
        sa.UniqueConstraint('case_id','request_key',name='uq_entry_channel_stop_request'),
        sa.ForeignKeyConstraint(['interview_id','case_id','applicant_id'],['entry_interviews.id','entry_interviews.case_id','entry_interviews.applicant_id'],name='fk_entry_channel_stop_subject'),
        sa.ForeignKeyConstraint(['handoff_event_id','interview_id','case_id','applicant_id'],['entry_interview_events.id','entry_interview_events.interview_id','entry_interview_events.case_id','entry_interview_events.applicant_id'],name='fk_entry_channel_stop_card'),
        sa.ForeignKeyConstraint(['contact_id'],['contacts.id']),
        sa.ForeignKeyConstraint(['dialog_id'],['dialogs.id']),
        sa.CheckConstraint('length(transport_key)=64 AND length(card_hash)=64 AND length(request_hash)=64 AND length(snapshot_hash)=64',name='ck_entry_channel_stop_hashes'))


def downgrade():
    if op.get_context().as_sql:raise RuntimeError('offline downgrade cannot verify empty channel stops')
    connection=op.get_bind()
    if connection.dialect.name=='postgresql':connection.execute(sa.text('LOCK TABLE entry_channel_stops IN ACCESS EXCLUSIVE MODE'))
    elif connection.dialect.name=='sqlite':connection.execute(sa.text('UPDATE entry_channel_stops SET id=id WHERE 1=0'))
    else:raise RuntimeError('unsupported channel stop downgrade dialect')
    if connection.scalar(sa.text('SELECT count(*) FROM entry_channel_stops')):raise RuntimeError('preserve populated channel stops')
    op.drop_table('entry_channel_stops')
