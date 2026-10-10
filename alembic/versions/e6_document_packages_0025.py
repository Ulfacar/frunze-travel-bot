"""Full-package command journal; existing document histories stay unchanged."""
import sqlalchemy as sa
from alembic import op

revision = 'e6_document_packages_0025'
down_revision = 'e6_kb_publication_0024'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('entry_document_package_events',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('application_id',sa.Integer(),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('action',sa.String(24),nullable=False),
        sa.Column('previous_id',sa.Integer(),nullable=True),
        sa.Column('legacy_inventory_id',sa.Integer(),nullable=True),
        sa.Column('legacy_inventory_hash',sa.String(64),nullable=True),
        sa.Column('definition',sa.JSON(none_as_null=True),nullable=True),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('state_hash',sa.String(64),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','application_id','case_id',name='uq_entry_package_scope'),
        sa.UniqueConstraint('application_id','revision',name='uq_entry_package_revision'),
        sa.UniqueConstraint('application_id','request_key',name='uq_entry_package_request'),
        sa.ForeignKeyConstraint(['application_id','case_id'],['entry_applications.id','entry_applications.case_id'],name='fk_entry_package_application'),
        sa.ForeignKeyConstraint(['previous_id','application_id','case_id'],['entry_document_package_events.id','entry_document_package_events.application_id','entry_document_package_events.case_id'],name='fk_entry_package_previous'),
        sa.ForeignKeyConstraint(['legacy_inventory_id','application_id','case_id'],['entry_document_revisions.id','entry_document_revisions.application_id','entry_document_revisions.case_id'],name='fk_entry_package_legacy'),
        sa.CheckConstraint('revision BETWEEN 1 AND 500',name='ck_entry_package_revision'),
        sa.CheckConstraint("(revision = 1 AND previous_id IS NULL AND action = 'initialize') OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id AND action != 'initialize' AND legacy_inventory_id IS NULL)",name='ck_entry_package_initial'),
        sa.CheckConstraint("action IN ('initialize','facts','receive','review','withdraw_document','passport_change','consent','approve','revoke','upgrade_definition')",name='ck_entry_package_action'),
        sa.CheckConstraint("(action IN ('initialize','upgrade_definition') AND definition IS NOT NULL) OR (action NOT IN ('initialize','upgrade_definition') AND definition IS NULL)",name='ck_entry_package_definition'),
        sa.CheckConstraint('(legacy_inventory_id IS NULL) = (legacy_inventory_hash IS NULL)',name='ck_entry_package_legacy'),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64 AND length(state_hash) = 64 AND (legacy_inventory_hash IS NULL OR length(legacy_inventory_hash) = 64)',name='ck_entry_package_hashes'))


def downgrade():
    if op.get_context().as_sql: raise RuntimeError('offline downgrade cannot verify document package history is empty')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql': bind.execute(sa.text('LOCK TABLE entry_document_package_events IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction: bind.exec_driver_sql('BEGIN IMMEDIATE')
        else: bind.exec_driver_sql('UPDATE entry_document_package_events SET id = id WHERE 0')
    if bind.scalar(sa.text('SELECT count(*) FROM entry_document_package_events')):
        raise RuntimeError('preserve populated document package history')
    op.drop_table('entry_document_package_events')
