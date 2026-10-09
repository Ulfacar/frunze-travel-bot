"""Add immutable application deadline evidence; no backfill or live scheduling."""
import sqlalchemy as sa
from alembic import op

revision = "e6_deadlines_0021"
down_revision = "e6_profiles_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("entry_deadline_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("rule_unit_id", sa.String(80), nullable=False),
        sa.Column("knowledge_version_id", sa.Integer(), sa.ForeignKey("knowledge_versions.id"), nullable=False),
        sa.Column("anchor_event_id", sa.Integer(), nullable=True),
        sa.Column("anchor_issued_id", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_id", sa.Integer(), nullable=True),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "application_id", "case_id", "rule_unit_id", name="uq_entry_deadline_scope"),
        sa.UniqueConstraint("application_id", "rule_unit_id", "revision", name="uq_entry_deadline_revision"),
        sa.UniqueConstraint("application_id", "rule_unit_id", "request_key", name="uq_entry_deadline_request"),
        sa.ForeignKeyConstraint(["application_id", "case_id"], ["entry_applications.id", "entry_applications.case_id"], name="fk_entry_deadline_application"),
        sa.ForeignKeyConstraint(["previous_id", "application_id", "case_id", "rule_unit_id"],
            ["entry_deadline_revisions.id", "entry_deadline_revisions.application_id", "entry_deadline_revisions.case_id", "entry_deadline_revisions.rule_unit_id"], name="fk_entry_deadline_previous"),
        sa.ForeignKeyConstraint(["anchor_event_id", "application_id"], ["entry_application_events.id", "entry_application_events.application_id"], name="fk_entry_deadline_event"),
        sa.ForeignKeyConstraint(["anchor_issued_id", "application_id", "case_id"],
            ["entry_issued_revisions.id", "entry_issued_revisions.application_id", "entry_issued_revisions.case_id"], name="fk_entry_deadline_travel"),
        sa.CheckConstraint("revision BETWEEN 1 AND 250", name="ck_entry_deadline_revision"),
        sa.CheckConstraint("anchor_event_id IS NULL OR anchor_issued_id IS NULL", name="ck_entry_deadline_anchor"),
        sa.CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)", name="ck_entry_deadline_previous"),
        sa.CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_deadline_hashes"))


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("offline downgrade cannot verify deadline history is empty")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("LOCK TABLE entry_deadline_revisions IN ACCESS EXCLUSIVE MODE"))
    elif bind.dialect.name == "sqlite":
        if not bind.connection.driver_connection.in_transaction:
            bind.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            bind.exec_driver_sql("UPDATE entry_deadline_revisions SET id = id WHERE 0")
    if bind.scalar(sa.text("SELECT count(*) FROM entry_deadline_revisions")):
        raise RuntimeError("preserve populated deadline history")
    op.drop_table("entry_deadline_revisions")
