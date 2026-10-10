"""Immutable procedural stages and scoped evidence pins; no backfill."""
import sqlalchemy as sa
from alembic import op
revision = 'e6_process_journal_0027'
down_revision = 'e6_document_quarantine_0026'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('entry_process_events',
        sa.Column('id',sa.Integer(),nullable=False),
        sa.Column('application_id',sa.Integer(),nullable=False),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('root_procedure',sa.String(24),nullable=False),
        sa.Column('active_application_id',sa.Integer(),nullable=False),
        sa.Column('active_procedure',sa.String(24),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('action',sa.String(16),nullable=False),
        sa.Column('previous_id',sa.Integer(),nullable=True),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),
        sa.Column('policy',sa.JSON(),nullable=True),
        sa.Column('evidence',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("action IN ('initialize','link','attest','withdraw','transition','stop')",name='ck_entry_process_action'),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64',name='ck_entry_process_hashes'),
        sa.CheckConstraint("(revision = 1 AND previous_id IS NULL AND action = 'initialize') OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id AND action != 'initialize')",name='ck_entry_process_initial'),
        sa.CheckConstraint('revision BETWEEN 1 AND 250',name='ck_entry_process_revision'),
        sa.ForeignKeyConstraint(['active_application_id', 'case_id', 'applicant_id', 'active_procedure'],['entry_applications.id', 'entry_applications.case_id', 'entry_applications.applicant_id', 'entry_applications.procedure'],name='fk_entry_process_active'),
        sa.ForeignKeyConstraint(['previous_id', 'application_id', 'case_id', 'applicant_id'],['entry_process_events.id', 'entry_process_events.application_id', 'entry_process_events.case_id', 'entry_process_events.applicant_id'],name='fk_entry_process_previous'),
        sa.ForeignKeyConstraint(['application_id', 'case_id', 'applicant_id', 'root_procedure'],['entry_applications.id', 'entry_applications.case_id', 'entry_applications.applicant_id', 'entry_applications.procedure'],name='fk_entry_process_root'),
        sa.PrimaryKeyConstraint(*['id']),
        sa.UniqueConstraint(*['application_id', 'request_key'],name='uq_entry_process_request'),
        sa.UniqueConstraint(*['application_id', 'revision'],name='uq_entry_process_revision'),
        sa.UniqueConstraint(*['id', 'application_id', 'case_id', 'applicant_id'],name='uq_entry_process_scope'),
    )
    op.create_table('entry_process_pins',
        sa.Column('event_id',sa.Integer(),nullable=False),
        sa.Column('ordinal',sa.Integer(),nullable=False),
        sa.Column('root_id',sa.Integer(),nullable=False),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('application_id',sa.Integer(),nullable=False),
        sa.Column('procedure',sa.String(24),nullable=False),
        sa.Column('fact',sa.String(100),nullable=False),
        sa.Column('kind',sa.String(24),nullable=False),
        sa.Column('source_hash',sa.String(64),nullable=False),
        sa.Column('application_event_id',sa.Integer(),nullable=True),
        sa.Column('package_event_id',sa.Integer(),nullable=True),
        sa.Column('issued_id',sa.Integer(),nullable=True),
        sa.Column('profile_id',sa.Integer(),nullable=True),
        sa.Column('attestation_id',sa.Integer(),nullable=True),
        sa.Column('payment_id',sa.Integer(),nullable=True),
        sa.Column('contract_event_id',sa.Integer(),nullable=True),
        sa.CheckConstraint('length(source_hash) = 64',name='ck_entry_process_pin_hash'),
        sa.CheckConstraint("kind IN ('application','application_event','package','issued','profile','attestation','payment','contract')",name='ck_entry_process_pin_kind'),
        sa.CheckConstraint("(CASE WHEN application_event_id IS NULL THEN 0 ELSE 1 END + CASE WHEN package_event_id IS NULL THEN 0 ELSE 1 END + CASE WHEN issued_id IS NULL THEN 0 ELSE 1 END + CASE WHEN profile_id IS NULL THEN 0 ELSE 1 END + CASE WHEN attestation_id IS NULL THEN 0 ELSE 1 END + CASE WHEN payment_id IS NULL THEN 0 ELSE 1 END + CASE WHEN contract_event_id IS NULL THEN 0 ELSE 1 END) = CASE WHEN kind = 'application' THEN 0 ELSE 1 END",name='ck_entry_process_pin_one_source'),
        sa.CheckConstraint('ordinal BETWEEN 1 AND 160',name='ck_entry_process_pin_ordinal'),
        sa.CheckConstraint("kind = 'application' OR (kind = 'application_event' AND application_event_id IS NOT NULL) OR (kind = 'package' AND package_event_id IS NOT NULL) OR (kind = 'issued' AND issued_id IS NOT NULL) OR (kind = 'profile' AND profile_id IS NOT NULL) OR (kind = 'attestation' AND attestation_id IS NOT NULL AND attestation_id < event_id) OR (kind = 'payment' AND payment_id IS NOT NULL) OR (kind = 'contract' AND contract_event_id IS NOT NULL)",name='ck_entry_process_pin_source_kind'),
        sa.ForeignKeyConstraint(['payment_id'],['service_payments.id'],name=None),
        sa.ForeignKeyConstraint(['contract_event_id'],['service_events.id'],name=None),
        sa.ForeignKeyConstraint(['application_event_id', 'application_id'],['entry_application_events.id', 'entry_application_events.application_id'],name='fk_entry_process_pin_app_event'),
        sa.ForeignKeyConstraint(['application_id', 'case_id', 'applicant_id', 'procedure'],['entry_applications.id', 'entry_applications.case_id', 'entry_applications.applicant_id', 'entry_applications.procedure'],name='fk_entry_process_pin_application'),
        sa.ForeignKeyConstraint(['attestation_id', 'root_id', 'case_id', 'applicant_id'],['entry_process_events.id', 'entry_process_events.application_id', 'entry_process_events.case_id', 'entry_process_events.applicant_id'],name='fk_entry_process_pin_attestation'),
        sa.ForeignKeyConstraint(['issued_id', 'application_id', 'case_id'],['entry_issued_revisions.id', 'entry_issued_revisions.application_id', 'entry_issued_revisions.case_id'],name='fk_entry_process_pin_issued'),
        sa.ForeignKeyConstraint(['package_event_id', 'application_id', 'case_id'],['entry_document_package_events.id', 'entry_document_package_events.application_id', 'entry_document_package_events.case_id'],name='fk_entry_process_pin_package'),
        sa.ForeignKeyConstraint(['event_id', 'root_id', 'case_id', 'applicant_id'],['entry_process_events.id', 'entry_process_events.application_id', 'entry_process_events.case_id', 'entry_process_events.applicant_id'],name='fk_entry_process_pin_parent'),
        sa.ForeignKeyConstraint(['profile_id', 'applicant_id', 'case_id'],['entry_applicant_profiles.id', 'entry_applicant_profiles.applicant_id', 'entry_applicant_profiles.case_id'],name='fk_entry_process_pin_profile'),
        sa.PrimaryKeyConstraint(*['event_id', 'ordinal']),
    )

def downgrade():
    if op.get_context().as_sql: raise RuntimeError('offline downgrade cannot verify process history is empty')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql': bind.execute(sa.text('LOCK TABLE entry_process_events, entry_process_pins IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction: bind.exec_driver_sql('BEGIN IMMEDIATE')
        else: bind.exec_driver_sql('UPDATE entry_process_events SET id=id WHERE 0')
    for table in ('entry_process_pins','entry_process_events'):
        if bind.scalar(sa.text('SELECT count(*) FROM '+table)): raise RuntimeError('preserve populated procedural evidence')
    op.drop_table('entry_process_pins')
    op.drop_table('entry_process_events')
