"""E1-01: пустой реестр продуктов, процессы, услуги и история.

Сидер запускается отдельно, чтобы миграция не включала рабочие процессы.
Обратная связь workflow_versions.product_id проверяется доменом: два FK
образовали бы цикл, требующий ALTER TABLE в PostgreSQL. Эта ревизия ограничена
CREATE TABLE и не изменяет ни одну ранее существовавшую таблицу.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Направления выписаны литералами намеренно. Импорт из app.domain.models сделал бы
# историческую ревизию «живой»: поменяется кортеж DIRECTIONS — задним числом поменяется
# CHECK в уже накатанной миграции, и upgrade на свежей базе разойдётся с тем, что стоит
# на проде. Ревизия обязана быть снимком схемы на свою дату.
PRODUCT_DIRECTIONS = ("tours", "visa", "tickets")

revision = "e1_services_0007"
down_revision = "bitrix_dossier_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("transitions", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_id", "version", name="uq_workflow_product_version"),
        sa.UniqueConstraint("id", "product_id", name="uq_workflow_id_product"),
        sa.CheckConstraint("version >= 1", name="ck_workflow_version_positive"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code"),
        sa.CheckConstraint("direction IN (" + ", ".join(repr(d) for d in PRODUCT_DIRECTIONS) + ")",
                           name="ck_products_direction"),
        sa.ForeignKeyConstraint(
            ["current_version_id", "id"], ["workflow_versions.id", "workflow_versions.product_id"],
            name="fk_products_current_version"),
    )
    op.create_table(
        "service_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("workflow_version_id", sa.Integer(), nullable=False),
        sa.Column("owner_login", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=True),
        sa.Column("waiting_party", sa.String(64), nullable=True),
        sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "product_id"],
            ["workflow_versions.id", "workflow_versions.product_id"],
            name="fk_service_cases_workflow_product"),
        sa.CheckConstraint("revision >= 1", name="ck_service_case_revision_positive"),
    )
    op.create_table(
        "service_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_stage", sa.String(64), nullable=True),
        sa.Column("to_stage", sa.String(64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["service_cases.id"]),
    )


def downgrade() -> None:
    op.drop_table("service_events")
    op.drop_table("service_cases")
    op.drop_table("products")
    op.drop_table("workflow_versions")
