"""Sprint 1: calendar tasks — calendar_tasks + calendar_task_events.

Additive-only. Creates the two new domain tables (manager tasks + their audit
history) with FKs to contacts/requests/assignments. Touches NO legacy table and
no existing domain table.

Revision ID: sprint1_calendar_0004
Revises: wp2_messages_0003
Create Date: 2026-07-18

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "sprint1_calendar_0004"
down_revision: Union[str, None] = "wp2_messages_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=True),
        sa.Column("assignment_id", sa.Integer(), nullable=True),
        sa.Column("manager_id", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("ai_summary", sa.Text(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"]),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calendar_tasks_contact_id", "calendar_tasks", ["contact_id"])
    op.create_index("ix_calendar_tasks_user_id", "calendar_tasks", ["user_id"])
    op.create_index("ix_calendar_tasks_manager_id", "calendar_tasks", ["manager_id"])
    op.create_index("ix_calendar_tasks_manager_date", "calendar_tasks",
                    ["manager_id", "scheduled_date"])

    op.create_table(
        "calendar_task_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=24), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=True),
        sa.Column("from_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("to_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["calendar_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calendar_task_events_task_id", "calendar_task_events", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_calendar_task_events_task_id", table_name="calendar_task_events")
    op.drop_table("calendar_task_events")

    op.drop_index("ix_calendar_tasks_manager_date", table_name="calendar_tasks")
    op.drop_index("ix_calendar_tasks_manager_id", table_name="calendar_tasks")
    op.drop_index("ix_calendar_tasks_user_id", table_name="calendar_tasks")
    op.drop_index("ix_calendar_tasks_contact_id", table_name="calendar_tasks")
    op.drop_table("calendar_tasks")
