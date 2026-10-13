"""Immutable portal observations and confirmations; no backfill or inbox integration."""
import sqlalchemy as sa
from alembic import op
revision = 'e6_portal_observations_0028'
down_revision = 'e6_process_journal_0027'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('entry_portal_receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('source_namespace', sa.String(80), nullable=False),
        sa.Column('channel', sa.String(24), nullable=False),
        sa.Column('transport_id', sa.String(160), nullable=False),
        sa.Column('raw_sha256', sa.String(64), nullable=False),
        sa.Column('raw_bytes', sa.Integer(), nullable=False),
        sa.Column('request_key', sa.String(64), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('snapshot_hash', sa.String(64), nullable=False),
        sa.Column('command', sa.JSON(), nullable=False),
        sa.Column('captures', sa.JSON(), nullable=False),
        sa.Column('policy', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("channel IN ('paste','portal','official_document')", name='ck_entry_portal_receipt_channel'),
        sa.CheckConstraint('length(raw_sha256) = 64 AND length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_entry_portal_receipt_hashes'),
        sa.CheckConstraint('raw_bytes BETWEEN 1 AND 16384', name='ck_entry_portal_receipt_size'),
        sa.ForeignKeyConstraint(['case_id'], ['service_cases.id'], name=None),
        sa.PrimaryKeyConstraint(*['id']),
        sa.UniqueConstraint(*['case_id', 'request_key'], name='uq_entry_portal_receipt_request'),
        sa.UniqueConstraint(*['id', 'case_id'], name='uq_entry_portal_receipt_scope'),
        sa.UniqueConstraint(*['source_namespace', 'channel', 'transport_id'], name='uq_entry_portal_receipt_transport'),
    )
    op.create_index('ix_entry_portal_receipt_case_id', 'entry_portal_receipts', ['case_id', 'id'], unique=False)
    op.create_index('ix_entry_portal_receipt_content', 'entry_portal_receipts', ['source_namespace', 'raw_sha256'], unique=False)
    op.create_table('entry_portal_actions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('receipt_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('previous_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(16), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=True),
        sa.Column('applicant_id', sa.Integer(), nullable=True),
        sa.Column('procedure', sa.String(24), nullable=True),
        sa.Column('head_id', sa.Integer(), nullable=True),
        sa.Column('cycle_id', sa.Integer(), nullable=True),
        sa.Column('applied_event_id', sa.Integer(), nullable=True),
        sa.Column('applied_content_hash', sa.String(64), nullable=True),
        sa.Column('request_key', sa.String(64), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('snapshot_hash', sa.String(64), nullable=False),
        sa.Column('command', sa.JSON(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('policy', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(applied_event_id IS NULL AND applied_content_hash IS NULL) OR (action = 'confirm' AND applied_event_id IS NOT NULL AND applied_content_hash IS NOT NULL AND length(applied_content_hash) = 64)", name='ck_entry_portal_action_applied'),
        sa.CheckConstraint('(application_id IS NULL AND applicant_id IS NULL AND procedure IS NULL AND head_id IS NULL AND cycle_id IS NULL) OR (application_id IS NOT NULL AND applicant_id IS NOT NULL AND procedure IS NOT NULL AND head_id IS NOT NULL AND cycle_id IS NOT NULL)', name='ck_entry_portal_action_binding'),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_entry_portal_action_hashes'),
        sa.CheckConstraint("action IN ('correlate','confirm','dismiss')", name='ck_entry_portal_action_kind'),
        sa.CheckConstraint('(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)', name='ck_entry_portal_action_previous'),
        sa.CheckConstraint('revision BETWEEN 1 AND 64', name='ck_entry_portal_action_revision'),
        sa.ForeignKeyConstraint(['application_id', 'case_id', 'applicant_id', 'procedure'], ['entry_applications.id', 'entry_applications.case_id', 'entry_applications.applicant_id', 'entry_applications.procedure'], name='fk_entry_portal_action_application'),
        sa.ForeignKeyConstraint(['cycle_id', 'application_id'], ['entry_application_events.id', 'entry_application_events.application_id'], name='fk_entry_portal_action_cycle'),
        sa.ForeignKeyConstraint(['applied_event_id', 'application_id'], ['entry_application_events.id', 'entry_application_events.application_id'], name='fk_entry_portal_action_event'),
        sa.ForeignKeyConstraint(['head_id', 'application_id'], ['entry_application_events.id', 'entry_application_events.application_id'], name='fk_entry_portal_action_head'),
        sa.ForeignKeyConstraint(['previous_id', 'receipt_id', 'case_id'], ['entry_portal_actions.id', 'entry_portal_actions.receipt_id', 'entry_portal_actions.case_id'], name='fk_entry_portal_action_previous'),
        sa.ForeignKeyConstraint(['receipt_id', 'case_id'], ['entry_portal_receipts.id', 'entry_portal_receipts.case_id'], name='fk_entry_portal_action_receipt'),
        sa.PrimaryKeyConstraint(*['id']),
        sa.UniqueConstraint(*['receipt_id', 'request_key'], name='uq_entry_portal_action_request'),
        sa.UniqueConstraint(*['receipt_id', 'revision'], name='uq_entry_portal_action_revision'),
        sa.UniqueConstraint(*['id', 'receipt_id', 'case_id'], name='uq_entry_portal_action_scope'),
        sa.UniqueConstraint(*['applied_content_hash'], name='uq_entry_portal_applied_content'),
        sa.UniqueConstraint(*['applied_event_id'], name='uq_entry_portal_applied_event'),
    )

def downgrade():
    if op.get_context().as_sql: raise RuntimeError('offline downgrade cannot verify portal history is empty')
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql': bind.execute(sa.text('LOCK TABLE entry_portal_receipts, entry_portal_actions IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name == 'sqlite':
        if not bind.connection.driver_connection.in_transaction: bind.exec_driver_sql('BEGIN IMMEDIATE')
        else: bind.exec_driver_sql('UPDATE entry_portal_receipts SET id=id WHERE 0')
    for table in ('entry_portal_actions', 'entry_portal_receipts'):
        if bind.scalar(sa.text('SELECT count(*) FROM ' + table)): raise RuntimeError('preserve populated portal observations')
    op.drop_table('entry_portal_actions')
    op.drop_index('ix_entry_portal_receipt_content', table_name='entry_portal_receipts')
    op.drop_index('ix_entry_portal_receipt_case_id', table_name='entry_portal_receipts')
    op.drop_table('entry_portal_receipts')
