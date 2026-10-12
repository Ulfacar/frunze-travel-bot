"""Typed actual evidence, no migration of or reinterpretation of old dates."""
import sqlalchemy as sa
from alembic import op

revision = 'e6_actual_anchor_events_0042'
down_revision = 'e6_work_review_events_0041'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('entry_anchor_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('applicant_id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('procedure', sa.String(32), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('anchor_key', sa.String(64), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('previous_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('request_key', sa.String(64), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('snapshot_hash', sa.String(64), nullable=False),
        sa.Column('command', sa.JSON(), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('id', 'application_id', 'case_id', 'applicant_id', name='uq_actual_anchor_scope'),
        sa.UniqueConstraint('application_id', 'revision', name='uq_actual_anchor_revision'),
        sa.UniqueConstraint('case_id', 'request_key', name='uq_actual_anchor_request'),
        sa.ForeignKeyConstraint(['application_id', 'case_id', 'applicant_id', 'procedure'],
            ['entry_applications.id', 'entry_applications.case_id', 'entry_applications.applicant_id', 'entry_applications.procedure'], name='fk_actual_anchor_subject'),
        sa.ForeignKeyConstraint(['previous_id', 'application_id', 'case_id', 'applicant_id'],
            ['entry_anchor_events.id', 'entry_anchor_events.application_id', 'entry_anchor_events.case_id', 'entry_anchor_events.applicant_id'], name='fk_actual_anchor_previous'),
        sa.CheckConstraint('revision BETWEEN 1 AND 80', name='ck_actual_anchor_revision'),
        sa.CheckConstraint("action IN ('record','withdraw')", name='ck_actual_anchor_action'),
        sa.CheckConstraint("(kind IN ('visa_period','visa_renewal_context') AND procedure='visa') OR (kind IN ('permit_period','employment_ended','permit_terminated') AND procedure='unified_permit') OR (kind='resident_period' AND procedure='resident_card') OR (kind IN ('registration_period','registration_payment_code','address_change','passport_change','purpose_change') AND procedure='registration')", name='ck_actual_anchor_kind'),
        sa.CheckConstraint('(revision=1 AND previous_id IS NULL) OR (revision>1 AND previous_id IS NOT NULL AND previous_id<id)', name='ck_actual_anchor_previous'),
        sa.CheckConstraint('length(request_hash)=64 AND length(snapshot_hash)=64', name='ck_actual_anchor_hashes'),
        sa.CheckConstraint('length(anchor_key) BETWEEN 1 AND 64', name='ck_actual_anchor_key'))
    op.create_table('entry_anchor_pins',
        sa.Column('anchor_id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('applicant_id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('application_event_id', sa.Integer(), nullable=False),
        sa.Column('issued_id', sa.Integer(), nullable=True),
        sa.Column('receipt_hash', sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint('anchor_id'),
        sa.ForeignKeyConstraint(['anchor_id', 'application_id', 'case_id', 'applicant_id'],
            ['entry_anchor_events.id', 'entry_anchor_events.application_id', 'entry_anchor_events.case_id', 'entry_anchor_events.applicant_id'], name='fk_actual_anchor_pin_receipt'),
        sa.ForeignKeyConstraint(['profile_id', 'applicant_id', 'case_id'],
            ['entry_applicant_profiles.id', 'entry_applicant_profiles.applicant_id', 'entry_applicant_profiles.case_id'], name='fk_actual_anchor_pin_profile'),
        sa.ForeignKeyConstraint(['application_event_id', 'application_id'],
            ['entry_application_events.id', 'entry_application_events.application_id'], name='fk_actual_anchor_pin_application'),
        sa.ForeignKeyConstraint(['issued_id', 'application_id', 'case_id'],
            ['entry_issued_revisions.id', 'entry_issued_revisions.application_id', 'entry_issued_revisions.case_id'], name='fk_actual_anchor_pin_issued'),
        sa.CheckConstraint('length(receipt_hash)=64', name='ck_actual_anchor_pin_hash'))
    op.create_index('ix_actual_anchor_pin_application', 'entry_anchor_pins', ['application_id'])
    op.create_table('entry_conditional_evidence',
        sa.Column('deadline_id', sa.Integer(), primary_key=True),
        sa.Column('application_id', sa.Integer(), nullable=False),
        sa.Column('case_id', sa.Integer(), nullable=False),
        sa.Column('rule_unit_id', sa.String(80), nullable=False),
        sa.Column('applicant_id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), nullable=False),
        sa.Column('application_event_id', sa.Integer(), nullable=False),
        sa.Column('anchor_id', sa.Integer(), nullable=True),
        sa.Column('history_id', sa.Integer(), nullable=True),
        sa.Column('receipt_hash', sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(['deadline_id', 'application_id', 'case_id', 'rule_unit_id'],
            ['entry_deadline_revisions.id', 'entry_deadline_revisions.application_id', 'entry_deadline_revisions.case_id', 'entry_deadline_revisions.rule_unit_id'], name='fk_conditional_receipt'),
        sa.ForeignKeyConstraint(['profile_id', 'applicant_id', 'case_id'],
            ['entry_applicant_profiles.id', 'entry_applicant_profiles.applicant_id', 'entry_applicant_profiles.case_id'], name='fk_conditional_profile'),
        sa.ForeignKeyConstraint(['application_event_id', 'application_id'],
            ['entry_application_events.id', 'entry_application_events.application_id'], name='fk_conditional_application'),
        sa.ForeignKeyConstraint(['anchor_id', 'application_id', 'case_id', 'applicant_id'],
            ['entry_anchor_events.id', 'entry_anchor_events.application_id', 'entry_anchor_events.case_id', 'entry_anchor_events.applicant_id'], name='fk_conditional_anchor'),
        sa.ForeignKeyConstraint(['history_id', 'applicant_id', 'case_id'],
            ['entry_applicant_stay_history.id', 'entry_applicant_stay_history.applicant_id', 'entry_applicant_stay_history.case_id'], name='fk_conditional_stay'),
        sa.CheckConstraint('length(receipt_hash)=64', name='ck_conditional_receipt_hash'))


def downgrade():
    if op.get_context().as_sql: raise RuntimeError('offline downgrade cannot verify empty actual anchor history')
    connection = op.get_bind()
    if connection.dialect.name == 'postgresql': connection.execute(sa.text('LOCK TABLE entry_anchor_events, entry_anchor_pins, entry_conditional_evidence IN ACCESS EXCLUSIVE MODE'))
    elif connection.dialect.name == 'sqlite': connection.execute(sa.text('UPDATE entry_anchor_events SET id=id WHERE 1=0'))
    else: raise RuntimeError('unsupported actual anchor downgrade dialect')
    if connection.scalar(sa.text('SELECT count(*) FROM entry_anchor_events')): raise RuntimeError('preserve populated actual anchor history')
    if connection.scalar(sa.text('SELECT count(*) FROM entry_conditional_evidence')): raise RuntimeError('preserve populated conditional deadline history')
    op.drop_table('entry_conditional_evidence')
    op.drop_index('ix_actual_anchor_pin_application', table_name='entry_anchor_pins')
    op.drop_table('entry_anchor_pins')
    op.drop_table('entry_anchor_events')
