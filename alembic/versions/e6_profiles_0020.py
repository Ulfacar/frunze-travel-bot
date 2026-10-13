"""Add individual applicant qualification revisions; no data conversion."""
import sqlalchemy as sa
from alembic import op

revision = "e6_profiles_0020"
down_revision = "e6_issued_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("entry_applicant_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("applicant_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_id", sa.Integer(), nullable=True),
        sa.Column("knowledge_version_id", sa.Integer(), sa.ForeignKey("knowledge_versions.id"), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "applicant_id", "case_id", name="uq_entry_profile_scope"),
        sa.UniqueConstraint("applicant_id", "revision", name="uq_entry_profile_revision"),
        sa.UniqueConstraint("applicant_id", "request_key", name="uq_entry_profile_request"),
        sa.ForeignKeyConstraint(["applicant_id", "case_id"], ["entry_applicants.id", "entry_applicants.case_id"], name="fk_entry_profile_applicant"),
        sa.ForeignKeyConstraint(["previous_id", "applicant_id", "case_id"],
            ["entry_applicant_profiles.id", "entry_applicant_profiles.applicant_id", "entry_applicant_profiles.case_id"], name="fk_entry_profile_previous"),
        sa.CheckConstraint("revision BETWEEN 1 AND 250", name="ck_entry_profile_revision"),
        sa.CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)", name="ck_entry_profile_previous"),
        sa.CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_profile_hashes"))


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("offline downgrade cannot verify applicant profile history is empty")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("LOCK TABLE entry_applicant_profiles IN ACCESS EXCLUSIVE MODE"))
    elif bind.dialect.name == "sqlite":
        if not bind.connection.driver_connection.in_transaction:
            bind.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            bind.exec_driver_sql("UPDATE entry_applicant_profiles SET id = id WHERE 0")
    if bind.scalar(sa.text("SELECT count(*) FROM entry_applicant_profiles")):
        raise RuntimeError("preserve populated applicant profile history")
    op.drop_table("entry_applicant_profiles")
