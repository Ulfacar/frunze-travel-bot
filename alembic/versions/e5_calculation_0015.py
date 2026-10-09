"""Add immutable trip, calendar and review calculation snapshots; no runtime data changes."""
import sqlalchemy as sa
from alembic import op

revision = "e5_calculation_0015"
down_revision = "e5_projection_0014"
branch_labels = None
depends_on = None

TABLES = ('entry_calculation_calendars', 'entry_calculation_intervals', 'entry_calculations', 'work_calendar_days', 'work_calendars', 'stay_intervals', 'stay_histories')


def upgrade():
    op.create_table(
        'stay_histories',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('previous_id', sa.Integer(), nullable=True),
        sa.Column('as_of', sa.Date(), nullable=False),
        sa.Column('history_complete', sa.Boolean(), nullable=True),
        sa.Column('request_key', sa.String(64), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('snapshot_hash', sa.String(64), nullable=False),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_stay_history_hashes'),
        sa.CheckConstraint('(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL)', name='ck_stay_history_previous'),
        sa.CheckConstraint('revision >= 1', name='ck_stay_history_revision'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.ForeignKeyConstraint(['previous_id', 'contact_id'], ['stay_histories.id', 'stay_histories.contact_id'], name='fk_stay_history_previous'),
        sa.UniqueConstraint('id', 'contact_id', name='uq_stay_history_contact'),
        sa.UniqueConstraint('contact_id', 'request_key', name='uq_stay_history_request'),
        sa.UniqueConstraint('contact_id', 'revision', name='uq_stay_history_revision'),
    )
    op.create_table(
        'stay_intervals',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('history_id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('ref', sa.String(64), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('exit_date', sa.Date(), nullable=True),
        sa.Column('basis', sa.String(32), nullable=False),
        sa.Column('passport_country', sa.String(3), nullable=True),
        sa.Column('passport_ref', sa.String(32), nullable=True),
        sa.Column('evidence', sa.String(32), nullable=False),
        sa.Column('confirmed', sa.Boolean(), nullable=False),
        sa.Column('confirmed_by', sa.String(64), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("basis IN ('visa_free','visa','ep','resident_card','residence_permit','registration_contract','unknown')", name='ck_stay_interval_basis'),
        sa.CheckConstraint('(confirmed AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL) OR (NOT confirmed AND confirmed_by IS NULL AND confirmed_at IS NULL)', name='ck_stay_interval_confirmation'),
        sa.CheckConstraint('exit_date IS NULL OR exit_date >= entry_date', name='ck_stay_interval_dates'),
        sa.CheckConstraint("evidence IN ('esuvm','passport_stamp','boarding_pass','visa_document','client_statement','crm_record')", name='ck_stay_interval_evidence'),
        sa.CheckConstraint('passport_ref IS NULL OR length(passport_ref) = 32', name='ck_stay_interval_passport'),
        sa.CheckConstraint("evidence <> 'client_statement' OR NOT confirmed", name='ck_stay_interval_statement'),
        sa.ForeignKeyConstraint(['history_id', 'contact_id'], ['stay_histories.id', 'stay_histories.contact_id'], name='fk_stay_interval_history'),
        sa.UniqueConstraint('id', 'history_id', name='uq_stay_interval_history'),
        sa.UniqueConstraint('history_id', 'ref', name='uq_stay_interval_ref'),
    )
    op.create_index('uq_stay_history_open', 'stay_intervals', ['history_id'], unique=True, sqlite_where=sa.text('exit_date IS NULL'), postgresql_where=sa.text('exit_date IS NULL'))
    op.create_table(
        'work_calendars',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('jurisdiction', sa.String(2), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('document', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('length(content_hash) = 64', name='ck_work_calendar_hash'),
        sa.CheckConstraint("jurisdiction = 'KG' AND status = 'draft'", name='ck_work_calendar_scope'),
        sa.CheckConstraint('year BETWEEN 1 AND 9999 AND version BETWEEN 1 AND 1000000', name='ck_work_calendar_version'),
        sa.UniqueConstraint('jurisdiction', 'year', 'version', name='uq_work_calendar_version'),
    )
    op.create_table(
        'work_calendar_days',
        sa.Column('calendar_id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('day', sa.Date(), nullable=False, primary_key=True),
        sa.Column('is_working', sa.Boolean(), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('source_ref', sa.Text(), nullable=False),
        sa.CheckConstraint("kind IN ('public_holiday','floating_holiday','transfer_rest','transfer_working','weekend_override')", name='ck_work_calendar_day_kind'),
        sa.CheckConstraint("(kind = 'weekend_override') OR (kind = 'transfer_working' AND is_working) OR (kind IN ('public_holiday','floating_holiday','transfer_rest') AND NOT is_working)", name='ck_work_calendar_day_working'),
        sa.ForeignKeyConstraint(['calendar_id'], ['work_calendars.id']),
    )
    op.create_table(
        'entry_calculations',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('history_id', sa.Integer(), nullable=True),
        sa.Column('knowledge_version_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('request_key', sa.String(64), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('snapshot_hash', sa.String(64), nullable=False),
        sa.Column('input_snapshot', sa.JSON(), nullable=False),
        sa.Column('result_snapshot', sa.JSON(), nullable=False),
        sa.Column('provenance', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_entry_calculation_hashes'),
        sa.CheckConstraint("(kind = 'stay' AND history_id IS NOT NULL) OR (kind = 'deadline' AND history_id IS NULL)", name='ck_entry_calculation_kind'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.ForeignKeyConstraint(['history_id', 'contact_id'], ['stay_histories.id', 'stay_histories.contact_id'], name='fk_entry_calculation_history'),
        sa.ForeignKeyConstraint(['knowledge_version_id'], ['knowledge_versions.id']),
        sa.UniqueConstraint('id', 'history_id', name='uq_entry_calculation_history'),
        sa.UniqueConstraint('contact_id', 'request_key', name='uq_entry_calculation_request'),
    )
    op.create_table(
        'entry_calculation_intervals',
        sa.Column('calculation_id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('interval_id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('history_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['calculation_id', 'history_id'], ['entry_calculations.id', 'entry_calculations.history_id'], name='fk_calculation_interval_calculation'),
        sa.ForeignKeyConstraint(['interval_id', 'history_id'], ['stay_intervals.id', 'stay_intervals.history_id'], name='fk_calculation_interval_history'),
    )
    op.create_table(
        'entry_calculation_calendars',
        sa.Column('calculation_id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('calendar_id', sa.Integer(), nullable=False, primary_key=True),
        sa.ForeignKeyConstraint(['calculation_id'], ['entry_calculations.id']),
        sa.ForeignKeyConstraint(['calendar_id'], ['work_calendars.id']),
    )


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("offline downgrade cannot verify empty entry storage")
    connection = op.get_bind()
    if any(connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) for table in TABLES):
        raise RuntimeError("preserve populated entry storage; downgrade refused")
    for table in TABLES:
        op.drop_table(table)
