"""Add individual stay evidence, without converting contact histories."""
import sqlalchemy as sa
from alembic import op

revision='e6_applicant_stay_0035'
down_revision='e6_publication_withdraw_0034'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('entry_applicant_stay_history',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('applicant_id',sa.Integer(),nullable=False),
        sa.Column('profile_id',sa.Integer(),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('previous_id',sa.Integer(),nullable=True),
        sa.Column('action',sa.String(16),nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('provenance',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','applicant_id','case_id',name='uq_applicant_stay_scope'),
        sa.UniqueConstraint('applicant_id','revision',name='uq_applicant_stay_revision'),
        sa.UniqueConstraint('applicant_id','request_key',name='uq_applicant_stay_request'),
        sa.ForeignKeyConstraint(['applicant_id','case_id'],['entry_applicants.id','entry_applicants.case_id'],name='fk_applicant_stay_person'),
        sa.ForeignKeyConstraint(['profile_id','applicant_id','case_id'],
            ['entry_applicant_profiles.id','entry_applicant_profiles.applicant_id','entry_applicant_profiles.case_id'],name='fk_applicant_stay_profile'),
        sa.ForeignKeyConstraint(['previous_id','applicant_id','case_id'],
            ['entry_applicant_stay_history.id','entry_applicant_stay_history.applicant_id','entry_applicant_stay_history.case_id'],name='fk_applicant_stay_previous'),
        sa.CheckConstraint('revision BETWEEN 1 AND 250',name='ck_applicant_stay_revision'),
        sa.CheckConstraint("action IN ('save','withdraw')",name='ck_applicant_stay_action'),
        sa.CheckConstraint("(revision = 1 AND previous_id IS NULL AND action = 'save') OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)",name='ck_applicant_stay_previous'),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64',name='ck_applicant_stay_hashes'))


def downgrade():
    if op.get_context().as_sql:raise RuntimeError('offline downgrade cannot verify personal stay history')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql':
        bind.execute(sa.text('LOCK TABLE entry_applicant_stay_history IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction:bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:bind.exec_driver_sql('UPDATE entry_applicant_stay_history SET id = id WHERE 0')
    else:raise RuntimeError('unsupported personal history migration database')
    if bind.scalar(sa.text('SELECT count(*) FROM entry_applicant_stay_history')):
        raise RuntimeError('preserve populated personal stay history')
    op.drop_table('entry_applicant_stay_history')
