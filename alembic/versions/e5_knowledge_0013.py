"""E5-02B: пустое хранилище снимков и журнал импорта (без публикации/сидера).

Ревизия не импортирует приложение. Только новые таблицы; обратный FK set_id
проверяет ORM по существующему паттерну workflow_versions. Downgrade заполненного
хранилища запрещён: откат приложения не требует удаления знаний/журнала.
"""
import sqlalchemy as sa
from alembic import op

revision = "e5_knowledge_0013"
down_revision = "e2_taskclaim_0012"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True)


def _time(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.create_table(
        "knowledge_versions", _id(),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_document", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("bundle_hash", sa.String(64), nullable=False),
        sa.Column("source_prepared_by", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False), _time("created_at"),
        sa.Column("bundle_meta", sa.JSON(), nullable=False),
        sa.Column("country_aliases", sa.JSON(), nullable=False),
        sa.Column("import_report", sa.JSON(), nullable=False),
        sa.UniqueConstraint("set_id", "version", name="uq_knowledge_version_number"),
        sa.UniqueConstraint("set_id", "bundle_hash", name="uq_knowledge_version_bundle"),
        sa.UniqueConstraint("id", "set_id", name="uq_knowledge_version_set"),
        sa.CheckConstraint("version >= 1", name="ck_knowledge_version_positive"),
        sa.CheckConstraint("status IN ('draft','review','approved','active','retired','rejected')",
                           name="ck_knowledge_version_status"),
        sa.CheckConstraint("length(source_hash) = 64 AND length(bundle_hash) = 64",
                           name="ck_knowledge_version_hashes"),
    )
    op.create_index("uq_knowledge_active", "knowledge_versions", ["set_id"], unique=True,
                    sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))
    op.create_table(
        "knowledge_sets", _id(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("jurisdiction", sa.String(2), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("review_period_days", sa.Integer(), nullable=True),
        sa.Column("active_version_id", sa.Integer(), nullable=True),
        _time("created_at"), _time("updated_at"), sa.UniqueConstraint("code"),
        sa.ForeignKeyConstraint(["active_version_id", "id"],
                                ["knowledge_versions.id", "knowledge_versions.set_id"],
                                name="fk_knowledge_active_version"),
        sa.CheckConstraint("review_period_days IS NULL OR review_period_days > 0",
                           name="ck_knowledge_review_period"),
    )
    op.create_table(
        "knowledge_units", _id(),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("knowledge_versions.id"), nullable=False),
        *[sa.Column(n, sa.Text(), nullable=False) for n in
          ("unit_id", "title", "section", "page", "source_ref", "owner")],
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("label", sa.String(16), nullable=False),
        sa.Column("confirmation_status", sa.String(32), nullable=False),
        sa.Column("value", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("value_schema_version", sa.Integer(), nullable=False),
        sa.Column("blocked_value", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("conflict_ref", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        _time("verified_at", True), sa.Column("verified_by", sa.Text(), nullable=True),
        _time("review_due_at", True), _time("created_at"),
        sa.Column("source_record", sa.JSON(), nullable=False),
        sa.UniqueConstraint("version_id", "unit_id", name="uq_knowledge_unit"),
        sa.CheckConstraint("kind IN ('visa_free_regime','registration_exemption','registration_default',"
                           "'registration_term','special_regime','visa_required_regime','rule_param',"
                           "'deadline','processing_time','tariff','template','escalation_trigger')",
                           name="ck_knowledge_unit_kind"),
        sa.CheckConstraint("label IN ('none','verify','practice','decision')", name="ck_knowledge_unit_label"),
        sa.CheckConstraint("confirmation_status IN ('confirmed','needs_verification','blocked','decision_pending')",
                           name="ck_knowledge_unit_confirmation"),
        sa.CheckConstraint("confirmation_status NOT IN ('blocked','decision_pending') OR "
                           "(value IS NULL AND blocked_value IS NOT NULL)", name="ck_knowledge_unit_pending"),
        sa.CheckConstraint("confirmation_status != 'blocked' OR conflict_ref IS NOT NULL",
                           name="ck_knowledge_unit_conflict"),
        sa.CheckConstraint("effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
                           name="ck_knowledge_unit_dates"),
        sa.CheckConstraint("(verified_at IS NULL AND verified_by IS NULL) OR "
                           "(verified_at IS NOT NULL AND verified_by IS NOT NULL)", name="ck_knowledge_unit_verifier"),
        sa.CheckConstraint("value_schema_version = 1", name="ck_knowledge_unit_schema"),
    )
    op.create_table(
        "knowledge_imports", _id(),
        sa.Column("set_id", sa.Integer(), sa.ForeignKey("knowledge_sets.id"), nullable=False),
        sa.Column("bundle_hash", sa.String(64), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("started_by", sa.String(64), nullable=False),
        _time("started_at"), _time("finished_at"),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=True),
        sa.Column("error_stage", sa.String(16), nullable=True),
        sa.Column("error_location", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["version_id", "set_id"],
                                ["knowledge_versions.id", "knowledge_versions.set_id"],
                                name="fk_knowledge_import_version"),
        sa.CheckConstraint("(result = 'accepted' AND version_id IS NOT NULL AND error_stage IS NULL) OR "
                           "(result = 'rejected' AND version_id IS NULL AND error_stage IS NOT NULL)",
                           name="ck_knowledge_import_result"),
        sa.CheckConstraint("error_stage IS NULL OR error_stage IN ('syntax','schema','semantic','db')",
                           name="ck_knowledge_import_stage"),
        sa.CheckConstraint("finished_at >= started_at", name="ck_knowledge_import_dates"),
    )


def downgrade():
    tables = ("knowledge_imports", "knowledge_units", "knowledge_sets", "knowledge_versions")
    # Guard before the first DROP, including audit-only/rejected attempts.
    if op.get_context().as_sql:
        raise RuntimeError("knowledge downgrade requires an online emptiness check")
    bind = op.get_bind()
    if any(bind.execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first() for name in tables):
        raise RuntimeError("knowledge downgrade refused: preserve populated tables and import journal")
    for name in tables:
        op.drop_table(name)
