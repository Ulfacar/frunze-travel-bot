"""Add immutable review projections; no historic version backfill or publication."""
import sqlalchemy as sa
from alembic import op

revision = "e5_projection_0014"
down_revision = "e5_knowledge_0013"
branch_labels = None
depends_on = None

TABLES = ("knowledge_condition_links", "knowledge_country_links", "knowledge_projections")


def upgrade():
    op.create_table(
        "knowledge_projections",
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("knowledge_versions.id"), primary_key=True),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("projection_hash", sa.String(64), nullable=False),
        sa.Column("catalog_hash", sa.String(64), nullable=True),
        sa.Column("country_summary", sa.JSON(), nullable=False),
        sa.Column("condition_catalog", sa.JSON(none_as_null=True), nullable=True),
        sa.CheckConstraint("format_version = 1", name="ck_knowledge_projection_format"),
        sa.CheckConstraint("length(projection_hash) = 64 AND (catalog_hash IS NULL OR length(catalog_hash) = 64)",
                           name="ck_knowledge_projection_hash"),
        sa.CheckConstraint("(catalog_hash IS NULL AND condition_catalog IS NULL) OR "
                           "(catalog_hash IS NOT NULL AND condition_catalog IS NOT NULL)",
                           name="ck_knowledge_projection_catalog"),
    )
    op.create_table(
        "knowledge_country_links",
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("knowledge_projections.version_id"), primary_key=True),
        sa.Column("country_iso3", sa.String(3), primary_key=True),
        sa.Column("unit_id", sa.Text(), primary_key=True),
        sa.Column("association", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["version_id", "unit_id"], ["knowledge_units.version_id", "knowledge_units.unit_id"],
                                name="fk_knowledge_country_unit"),
        sa.CheckConstraint("length(country_iso3) = 3", name="ck_knowledge_country_iso3"),
        sa.CheckConstraint("association IN ('value_country','unit_id_country','evidence_country','explicit_not_in_list')",
                           name="ck_knowledge_country_association"),
    )
    op.create_table(
        "knowledge_condition_links",
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("knowledge_projections.version_id"), primary_key=True),
        sa.Column("unit_id", sa.Text(), primary_key=True),
        sa.ForeignKeyConstraint(["version_id", "unit_id"], ["knowledge_units.version_id", "knowledge_units.unit_id"],
                                name="fk_knowledge_condition_unit"),
    )


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("offline downgrade cannot verify empty knowledge projections")
    connection = op.get_bind()
    # Check every table BEFORE dropping any; application rollback can retain them.
    if any(connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) for table in TABLES):
        raise RuntimeError("preserve populated knowledge projections; downgrade refused")
    for table in TABLES:
        op.drop_table(table)
