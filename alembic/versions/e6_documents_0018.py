"""Add immutable document metadata inventory. No data backfill or file storage."""
import sqlalchemy as sa
from alembic import op

revision='e6_documents_0018'
down_revision='e6_applications_0017'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('entry_document_revisions',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('case_id',sa.Integer(),nullable=False),
        sa.Column('application_id',sa.Integer(),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('previous_id',sa.Integer(),nullable=True),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('snapshot_hash',sa.String(64),nullable=False),
        sa.Column('command',sa.JSON(),nullable=False),
        sa.Column('snapshot',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('id','application_id','case_id',name='uq_entry_document_parent'),
        sa.UniqueConstraint('application_id','revision',name='uq_entry_document_revision'),
        sa.UniqueConstraint('application_id','request_key',name='uq_entry_document_request'),
        sa.ForeignKeyConstraint(['application_id','case_id'],['entry_applications.id','entry_applications.case_id'],name='fk_entry_document_case'),
        sa.ForeignKeyConstraint(['previous_id','application_id','case_id'],
            ['entry_document_revisions.id','entry_document_revisions.application_id','entry_document_revisions.case_id'],name='fk_entry_document_previous'),
        sa.CheckConstraint('revision BETWEEN 1 AND 150',name='ck_entry_document_revision'),
        sa.CheckConstraint('(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)',name='ck_entry_document_previous'),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64',name='ck_entry_document_hashes'))


def downgrade():
    if op.get_context().as_sql:raise RuntimeError('offline downgrade cannot verify document inventory is empty')
    bind=op.get_bind()
    if bind.dialect.name=='postgresql':
        bind.execute(sa.text('LOCK TABLE entry_document_revisions IN ACCESS EXCLUSIVE MODE'))
    elif bind.dialect.name=='sqlite':
        if not bind.connection.driver_connection.in_transaction:bind.exec_driver_sql('BEGIN IMMEDIATE')
        else:bind.exec_driver_sql('UPDATE entry_document_revisions SET id = id WHERE 0')
    if bind.scalar(sa.text('SELECT count(*) FROM entry_document_revisions')):
        raise RuntimeError('preserve populated document inventory')
    op.drop_table('entry_document_revisions')
