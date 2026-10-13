"""Add case-scoped applicants, attempts and immutable processing facts. No backfill."""
import sqlalchemy as sa
from alembic import op

revision = 'e6_applications_0017'
down_revision = 'e5_qualification_0016'
branch_labels = None
depends_on = None


def _stamp():
    return [sa.Column('request_key', sa.String(64), nullable=False),
            sa.Column('request_hash', sa.String(64), nullable=False),
            sa.Column('snapshot_hash', sa.String(64), nullable=False),
            sa.Column('created_by', sa.String(64), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.create_table('entry_applicants',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(16), nullable=False), *_stamp(),
        sa.ForeignKeyConstraint(['case_id'], ['service_cases.id']),
        sa.UniqueConstraint('id', 'case_id', name='uq_entry_applicant_case'),
        sa.UniqueConstraint('case_id', 'ordinal', name='uq_entry_applicant_ordinal'),
        sa.UniqueConstraint('case_id', 'request_key', name='uq_entry_applicant_request'),
        sa.CheckConstraint('ordinal BETWEEN 1 AND 1000', name='ck_entry_applicant_ordinal'),
        sa.CheckConstraint("role IN ('unknown','primary','spouse','child','parent','employee','other')", name='ck_entry_applicant_role'),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_entry_applicant_hashes'))
    op.create_table('entry_applications',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('applicant_id', sa.Integer(), nullable=False),
        sa.Column('procedure', sa.String(32), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('previous_id', sa.Integer(), nullable=True), *_stamp(),
        sa.ForeignKeyConstraint(['case_id'], ['service_cases.id']),
        sa.ForeignKeyConstraint(['applicant_id', 'case_id'], ['entry_applicants.id', 'entry_applicants.case_id'], name='fk_entry_application_applicant'),
        sa.ForeignKeyConstraint(['previous_id', 'case_id', 'applicant_id', 'procedure'],
            ['entry_applications.id', 'entry_applications.case_id', 'entry_applications.applicant_id', 'entry_applications.procedure'], name='fk_entry_application_previous'),
        sa.UniqueConstraint('id', 'case_id', name='uq_entry_application_case'),
        sa.UniqueConstraint('id', 'case_id', 'applicant_id', 'procedure', name='uq_entry_application_subject'),
        sa.UniqueConstraint('case_id', 'request_key', name='uq_entry_application_request'),
        sa.UniqueConstraint('previous_id', name='uq_entry_application_successor'),
        sa.CheckConstraint("procedure IN ('visa','unified_permit','resident_card','registration','violation_protocol','exit_visa')", name='ck_entry_application_procedure'),
        sa.CheckConstraint('attempt BETWEEN 1 AND 100', name='ck_entry_application_attempt'),
        sa.CheckConstraint('(attempt = 1 AND previous_id IS NULL) OR (attempt > 1 AND previous_id IS NOT NULL AND previous_id < id)', name='ck_entry_application_previous'),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_entry_application_hashes'))
    op.create_table('entry_application_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('previous_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('occurred_on', sa.Date(), nullable=False),
        sa.Column('source', sa.String(24), nullable=False),
        sa.Column('reference', sa.String(8), nullable=True), *_stamp(),
        sa.UniqueConstraint('id', 'application_id', name='uq_entry_application_event_parent'),
        sa.UniqueConstraint('application_id', 'revision', name='uq_entry_application_event_revision'),
        sa.UniqueConstraint('application_id', 'request_key', name='uq_entry_application_event_request'),
        sa.ForeignKeyConstraint(['application_id', 'case_id'], ['entry_applications.id', 'entry_applications.case_id'], name='fk_entry_application_event_case'),
        sa.ForeignKeyConstraint(['previous_id', 'application_id'], ['entry_application_events.id', 'entry_application_events.application_id'], name='fk_entry_application_event_previous'),
        sa.CheckConstraint('revision BETWEEN 1 AND 500', name='ck_entry_application_event_revision'),
        sa.CheckConstraint("(revision = 1 AND previous_id IS NULL AND status = 'draft') OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id AND status <> 'draft')", name='ck_entry_application_event_previous'),
        sa.CheckConstraint("status IN ('draft','submitted','revision_requested','approved','refused','closed')", name='ck_entry_application_event_status'),
        sa.CheckConstraint("source IN ('crm','portal','official_document','client_request')", name='ck_entry_application_event_source'),
        sa.CheckConstraint('reference IS NULL OR length(reference) = 8', name='ck_entry_application_event_reference'),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_entry_application_event_hashes'))
    op.create_table('entry_application_references',
        sa.Column('application_id', sa.Integer(), primary_key=True),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('reference', sa.String(8), nullable=False, unique=True),
        sa.ForeignKeyConstraint(['application_id', 'case_id'], ['entry_applications.id', 'entry_applications.case_id'], name='fk_entry_application_reference_case'),
        sa.CheckConstraint('length(reference) = 8', name='ck_entry_application_reference_length'))


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError('offline downgrade cannot verify application register is empty')
    tables = ('entry_application_references', 'entry_application_events', 'entry_applications', 'entry_applicants')
    bind = op.get_bind()
    # Hold writers out across the empty check and all drops, not just each SELECT.
    if bind.dialect.name == 'postgresql':
        bind.execute(sa.text('LOCK TABLE ' + ', '.join(tables) + ' IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name == 'sqlite':
        if not bind.connection.driver_connection.in_transaction:
            bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            bind.exec_driver_sql('UPDATE entry_applicants SET id = id WHERE 0')
    if any(bind.scalar(sa.text(f'SELECT count(*) FROM {name}')) for name in tables):
        raise RuntimeError('preserve populated entry application register')
    for name in tables:
        op.drop_table(name)
