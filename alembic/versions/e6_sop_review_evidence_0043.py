"""Scoped manual review evidence and nullable exact task time; no backfill."""
import sqlalchemy as sa
from alembic import op

revision = 'e6_sop_review_evidence_0043'
down_revision = 'e6_actual_anchor_events_0042'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('entry_deadline_tasks', sa.Column('expected_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table('entry_sop_review_evidence',
        sa.Column('deadline_id',sa.Integer(),primary_key=True),
        sa.Column('application_id',sa.Integer(),nullable=False),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('rule_unit_id',sa.String(80),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('process_event_id',sa.Integer(),nullable=False),
        sa.Column('profile_id',sa.Integer(),nullable=False),
        sa.Column('active_application_id',sa.Integer(),nullable=False),
        sa.Column('active_procedure',sa.String(24),nullable=False),
        sa.Column('application_event_id',sa.Integer(),nullable=False),
        sa.Column('receipt_hash',sa.String(64),nullable=False),
        sa.ForeignKeyConstraint(['deadline_id','application_id','case_id','rule_unit_id'],
            ['entry_deadline_revisions.id','entry_deadline_revisions.application_id','entry_deadline_revisions.case_id','entry_deadline_revisions.rule_unit_id'], name='fk_sop_review_receipt'),
        sa.ForeignKeyConstraint(['process_event_id','application_id','case_id','applicant_id'],
            ['entry_process_events.id','entry_process_events.application_id','entry_process_events.case_id','entry_process_events.applicant_id'], name='fk_sop_review_process'),
        sa.ForeignKeyConstraint(['profile_id','applicant_id','case_id'],
            ['entry_applicant_profiles.id','entry_applicant_profiles.applicant_id','entry_applicant_profiles.case_id'], name='fk_sop_review_profile'),
        sa.ForeignKeyConstraint(['active_application_id','case_id','applicant_id','active_procedure'],
            ['entry_applications.id','entry_applications.case_id','entry_applications.applicant_id','entry_applications.procedure'], name='fk_sop_review_active'),
        sa.ForeignKeyConstraint(['application_event_id','active_application_id'],
            ['entry_application_events.id','entry_application_events.application_id'], name='fk_sop_review_event'),
        sa.CheckConstraint('length(receipt_hash)=64',name='ck_sop_review_receipt_hash'))


def downgrade():
    if op.get_context().as_sql: raise RuntimeError('offline downgrade cannot verify empty SOP review history')
    connection=op.get_bind()
    if connection.dialect.name=='postgresql':
        connection.execute(sa.text('LOCK TABLE entry_sop_review_evidence, entry_deadline_tasks IN ACCESS EXCLUSIVE MODE'))
    elif connection.dialect.name=='sqlite':
        connection.execute(sa.text('UPDATE entry_sop_review_evidence SET deadline_id=deadline_id WHERE 1=0'))
    else: raise RuntimeError('unsupported SOP review downgrade dialect')
    if connection.scalar(sa.text('SELECT count(*) FROM entry_sop_review_evidence')):
        raise RuntimeError('preserve populated SOP review evidence')
    if connection.scalar(sa.text('SELECT count(*) FROM entry_deadline_tasks WHERE expected_at IS NOT NULL')):
        raise RuntimeError('preserve exact task times')
    op.drop_table('entry_sop_review_evidence')
    op.drop_column('entry_deadline_tasks','expected_at')
