"""Add immutable qualification revisions; no seeds or live data rewrites."""
import sqlalchemy as sa
from alembic import op

revision = "e5_qualification_0016"
down_revision = "e5_calculation_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "entry_qualifications",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_id", sa.Integer(), nullable=True),
        sa.Column("history_id", sa.Integer(), nullable=True),
        sa.Column("knowledge_version_id", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "contact_id", name="uq_entry_qualification_contact"),
        sa.UniqueConstraint("contact_id", "revision", name="uq_entry_qualification_revision"),
        sa.UniqueConstraint("contact_id", "request_key", name="uq_entry_qualification_request"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["knowledge_version_id"], ["knowledge_versions.id"]),
        sa.ForeignKeyConstraint(["previous_id", "contact_id"], ["entry_qualifications.id", "entry_qualifications.contact_id"],
                                name="fk_entry_qualification_previous"),
        sa.ForeignKeyConstraint(["history_id", "contact_id"], ["stay_histories.id", "stay_histories.contact_id"],
                                name="fk_entry_qualification_history"),
        sa.CheckConstraint("revision >= 1", name="ck_entry_qualification_revision"),
        sa.CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL)",
                           name="ck_entry_qualification_previous"),
        sa.CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_qualification_hashes"),
    )


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("offline downgrade cannot verify qualification storage is empty")
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM entry_qualifications")):
        raise RuntimeError("preserve populated entry qualification snapshots")
    op.drop_table("entry_qualifications")
