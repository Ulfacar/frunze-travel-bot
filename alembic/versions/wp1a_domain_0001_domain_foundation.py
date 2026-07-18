"""WP1A domain foundation: contacts, contact_identities, requests, dialogs,
assignments, external_references.

Additive-only first revision. Creates the six new domain tables on their own
``DomainBase`` metadata. Touches NO legacy table (deals / conversations /
messages / audit_log / app_flags / faq_entries) — those remain under the runtime
``create_all`` + ``_ensure_columns`` mechanism and are outside Alembic's scope.

Mirrors app/domain/models.py exactly, including the three partial unique indexes
(one active Request / Assignment per contact+direction, one active external
reference), rendered per-dialect for SQLite and PostgreSQL.

Revision ID: wp1a_domain_0001
Revises:
Create Date: 2026-07-18

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "wp1a_domain_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- contacts --------------------------------------------------------------
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- contact_identities ----------------------------------------------------
    op.create_table(
        "contact_identities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("identity_type", sa.String(length=32), nullable=False),
        sa.Column("normalized_value", sa.String(length=190), nullable=False),
        sa.Column("display_value", sa.String(length=190), nullable=False),
        sa.Column("provider_scope", sa.String(length=64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_type", "normalized_value", "provider_scope",
                            name="uq_contact_identity_normalized"),
    )
    op.create_index("ix_contact_identities_contact_id", "contact_identities",
                    ["contact_id"])
    op.create_index("ix_contact_identities_normalized_value", "contact_identities",
                    ["normalized_value"])

    # --- requests --------------------------------------------------------------
    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_requests_contact_id", "requests", ["contact_id"])
    # At most one ACTIVE (closed_at IS NULL) request per (contact, direction).
    op.create_index(
        "uq_active_request_per_contact_direction", "requests",
        ["contact_id", "direction"], unique=True,
        sqlite_where=sa.text("closed_at IS NULL"),
        postgresql_where=sa.text("closed_at IS NULL"),
    )

    # --- dialogs ---------------------------------------------------------------
    op.create_table(
        "dialogs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("bot_id", sa.String(length=64), nullable=False),
        sa.Column("channel_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dialogs_contact_id", "dialogs", ["contact_id"])
    op.create_index("ix_dialogs_request_id", "dialogs", ["request_id"])

    # --- assignments -----------------------------------------------------------
    op.create_table(
        "assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("manager_id", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_by", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assignments_contact_id", "assignments", ["contact_id"])
    # At most one ACTIVE assignment per (contact, direction).
    op.create_index(
        "uq_active_assignment_per_contact_direction", "assignments",
        ["contact_id", "direction"], unique=True,
        sqlite_where=sa.text("active = 1"),
        postgresql_where=sa.text("active"),
    )

    # --- external_references ---------------------------------------------------
    op.create_table(
        "external_references",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("request_ref", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["request_ref"], ["requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_external_references_request_ref", "external_references",
                    ["request_ref"])
    # At most one ACTIVE external reference per (provider, external_type, external_id).
    op.create_index(
        "uq_active_external_reference", "external_references",
        ["provider", "external_type", "external_id"], unique=True,
        sqlite_where=sa.text("active = 1"),
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    # Reverse creation order; drop indexes then tables. Only these six domain
    # tables are removed — no legacy table is touched.
    op.drop_index("uq_active_external_reference", table_name="external_references")
    op.drop_index("ix_external_references_request_ref", table_name="external_references")
    op.drop_table("external_references")

    op.drop_index("uq_active_assignment_per_contact_direction", table_name="assignments")
    op.drop_index("ix_assignments_contact_id", table_name="assignments")
    op.drop_table("assignments")

    op.drop_index("ix_dialogs_request_id", table_name="dialogs")
    op.drop_index("ix_dialogs_contact_id", table_name="dialogs")
    op.drop_table("dialogs")

    op.drop_index("uq_active_request_per_contact_direction", table_name="requests")
    op.drop_index("ix_requests_contact_id", table_name="requests")
    op.drop_table("requests")

    op.drop_index("ix_contact_identities_normalized_value", table_name="contact_identities")
    op.drop_index("ix_contact_identities_contact_id", table_name="contact_identities")
    op.drop_table("contact_identities")

    op.drop_table("contacts")
