"""Atomic bounded binary quarantine; no backfill or live storage configuration."""
import sqlalchemy as sa
from alembic import op

revision = 'e6_document_quarantine_0026'
down_revision = 'e6_document_packages_0025'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('entry_quarantined_files',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('application_id',sa.Integer(),nullable=False),
        sa.Column('package_event_id',sa.Integer(),nullable=False),
        sa.Column('item_id',sa.String(41),nullable=False),
        sa.Column('document_version',sa.Integer(),nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('byte_size',sa.Integer(),nullable=False),
        sa.Column('media_type',sa.String(32),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('policy',sa.JSON(),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('content',sa.LargeBinary(),nullable=False),
        sa.UniqueConstraint('application_id','request_key',name='uq_entry_quarantine_request'),
        sa.UniqueConstraint('package_event_id',name='uq_entry_quarantine_receipt'),
        sa.ForeignKeyConstraint(['package_event_id','application_id','case_id'],
            ['entry_document_package_events.id','entry_document_package_events.application_id','entry_document_package_events.case_id'],name='fk_entry_quarantine_receipt'),
        sa.CheckConstraint('document_version BETWEEN 1 AND 500',name='ck_entry_quarantine_version'),
        sa.CheckConstraint('byte_size BETWEEN 8 AND 8388608 AND length(content) = byte_size',name='ck_entry_quarantine_size'),
        sa.CheckConstraint("media_type IN ('application/pdf','image/jpeg')",name='ck_entry_quarantine_type'),
        sa.CheckConstraint('length(fingerprint) = 64 AND length(request_hash) = 64 AND length(snapshot_hash) = 64',name='ck_entry_quarantine_hashes'))
    op.create_index('ix_entry_quarantine_application','entry_quarantined_files',['application_id'])


def downgrade():
    if op.get_context().as_sql: raise RuntimeError('offline downgrade cannot verify quarantine is empty')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql': bind.execute(sa.text('LOCK TABLE entry_quarantined_files IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction: bind.exec_driver_sql('BEGIN IMMEDIATE')
        else: bind.exec_driver_sql('UPDATE entry_quarantined_files SET id = id WHERE 0')
    if bind.scalar(sa.text('SELECT count(*) FROM entry_quarantined_files')):
        raise RuntimeError('preserve populated quarantine and retention evidence')
    op.drop_index('ix_entry_quarantine_application',table_name='entry_quarantined_files')
    op.drop_table('entry_quarantined_files')
