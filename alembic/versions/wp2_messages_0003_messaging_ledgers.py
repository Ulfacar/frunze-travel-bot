"""WP2: messaging foundation — canonical_messages, inbox_events, outbox_jobs.

Additive-only. Creates the three new domain ledgers (unified history + inbox +
outbox) with DB-level dedup indexes. Touches NO legacy table and no existing
domain table. Nothing here is wired into live delivery, and the Bitrix mirror is
untouched.

Revision ID: wp2_messages_0003
Revises: wp1b_dialog_uidx_0002
Create Date: 2026-07-18

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "wp2_messages_0003"
down_revision: Union[str, None] = "wp1b_dialog_uidx_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- canonical_messages (unified history) ----------------------------------
    op.create_table(
        "canonical_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dialog_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("sender_role", sa.String(length=16), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider_msg_id", sa.String(length=128), nullable=False),
        sa.Column("dedup_key", sa.String(length=190), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["dialog_id"], ["dialogs.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canonical_messages_dialog_id", "canonical_messages", ["dialog_id"])
    op.create_index("ix_canonical_messages_contact_id", "canonical_messages", ["contact_id"])
    op.create_index("ix_canonical_messages_provider_msg_id", "canonical_messages",
                    ["provider_msg_id"])
    # Dedup: one timeline row per (dialog, direction, dedup_key) when a key is present.
    op.create_index(
        "uq_canonical_message_dedup", "canonical_messages",
        ["dialog_id", "direction", "dedup_key"], unique=True,
        sqlite_where=sa.text("dedup_key <> ''"),
        postgresql_where=sa.text("dedup_key <> ''"),
    )

    # --- inbox_events (incoming ledger) ----------------------------------------
    op.create_table(
        "inbox_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        # account_scope = receiving bot/provider account (bot_id): external ids are
        # unique only within one account, never across accounts.
        sa.Column("account_scope", sa.String(length=190), nullable=False),
        sa.Column("external_event_id", sa.String(length=190), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("dialog_id", sa.Integer(), nullable=True),
        sa.Column("canonical_message_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dialog_id"], ["dialogs.id"]),
        sa.ForeignKeyConstraint(["canonical_message_id"], ["canonical_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inbox_events_dialog_id", "inbox_events", ["dialog_id"])
    # Dedup scoped to (provider, account_scope, external_event_id); partial (skip empty).
    op.create_index(
        "uq_inbox_event_dedup", "inbox_events",
        ["provider", "account_scope", "external_event_id"], unique=True,
        sqlite_where=sa.text("external_event_id <> ''"),
        postgresql_where=sa.text("external_event_id <> ''"),
    )

    # --- outbox_jobs (outgoing ledger) -----------------------------------------
    op.create_table(
        "outbox_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dialog_id", sa.Integer(), nullable=False),
        sa.Column("canonical_message_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        # Dedup scope: provider (wappi/telegram/…), sending account (bot_id) and
        # destination (recipient). idempotency keys are unique only within this scope.
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("account_scope", sa.String(length=190), nullable=False),
        sa.Column("destination_scope", sa.String(length=190), nullable=False),
        sa.Column("idempotency_key", sa.String(length=190), nullable=False),
        sa.Column("provider_msg_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["dialog_id"], ["dialogs.id"]),
        sa.ForeignKeyConstraint(["canonical_message_id"], ["canonical_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_jobs_dialog_id", "outbox_jobs", ["dialog_id"])
    op.create_index("ix_outbox_jobs_provider_msg_id", "outbox_jobs", ["provider_msg_id"])
    # Dedup scoped to (provider, account_scope, destination_scope, idempotency_key).
    op.create_index(
        "uq_outbox_job_idem", "outbox_jobs",
        ["provider", "account_scope", "destination_scope", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key <> ''"),
        postgresql_where=sa.text("idempotency_key <> ''"),
    )


def downgrade() -> None:
    # Reverse creation order; only these three new tables are removed.
    op.drop_index("uq_outbox_job_idem", table_name="outbox_jobs")
    op.drop_index("ix_outbox_jobs_provider_msg_id", table_name="outbox_jobs")
    op.drop_index("ix_outbox_jobs_dialog_id", table_name="outbox_jobs")
    op.drop_table("outbox_jobs")

    op.drop_index("uq_inbox_event_dedup", table_name="inbox_events")
    op.drop_index("ix_inbox_events_dialog_id", table_name="inbox_events")
    op.drop_table("inbox_events")

    op.drop_index("uq_canonical_message_dedup", table_name="canonical_messages")
    op.drop_index("ix_canonical_messages_provider_msg_id", table_name="canonical_messages")
    op.drop_index("ix_canonical_messages_contact_id", table_name="canonical_messages")
    op.drop_index("ix_canonical_messages_dialog_id", table_name="canonical_messages")
    op.drop_table("canonical_messages")
