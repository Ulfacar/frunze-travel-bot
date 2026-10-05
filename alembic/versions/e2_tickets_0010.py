"""E2-02: сегменты билета и связь задач с услугой и сегментом.

Аддитивная: создаёт `ticket_segments` и добавляет две nullable-колонки в
`calendar_tasks`. Существующие строки задач не затрагиваются — у них связи просто
нет, как и было.

Revision ID: e2_tickets_0010
Revises: e2_payments_0009
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2_tickets_0010"
down_revision = "e2_payments_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket_segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("service_cases.id"),
                  nullable=False, index=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("carrier", sa.String(length=64), nullable=False),
        sa.Column("flight_number", sa.String(length=16), nullable=False),
        sa.Column("departure_airport", sa.String(length=8), nullable=False),
        sa.Column("arrival_airport", sa.String(length=8), nullable=False),
        sa.Column("departure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("departure_tz", sa.String(length=64), nullable=False),
        sa.Column("arrival_tz", sa.String(length=64), nullable=False),
        sa.Column("checkin_opens_hours_before", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="planned"),
        sa.Column("supersedes_id", sa.Integer(), sa.ForeignKey("ticket_segments.id"),
                  nullable=True),
        sa.Column("superseded", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("booking_reference", sa.String(length=64), nullable=True),
        sa.Column("passenger_name", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("position >= 1", name="ck_ticket_segment_position"),
        sa.CheckConstraint("arrival_at > departure_at", name="ck_ticket_segment_order"),
        sa.CheckConstraint(
            "checkin_opens_hours_before IS NULL"
            " OR (checkin_opens_hours_before > 0 AND checkin_opens_hours_before <= 336)",
            name="ck_ticket_segment_checkin_window"),
        sa.CheckConstraint("status IN ('planned', 'confirmed', 'cancelled')",
                           name="ck_ticket_segment_status"),
        sa.CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id",
                           name="ck_ticket_segment_no_self_supersede"),
    )
    # Позиция уникальна только среди действующих сегментов: заменённые остаются
    # в истории и не должны занимать место, иначе второй перенос того же рейса
    # падает, а рейсы двигают по нескольку раз.
    op.create_index("uq_ticket_segment_active_position", "ticket_segments",
                    ["case_id", "position"], unique=True,
                    sqlite_where=sa.text("superseded = 0 AND status <> 'cancelled'"),
                    postgresql_where=sa.text(
                        "superseded = false AND status <> 'cancelled'"))
    # Связь задачи с услугой и сегментом. Без неё перенос рейса не знает, какое
    # напоминание отменять (AC-08).
    # batch_alter_table, а не прямой add_column: SQLite не умеет ALTER ограничений,
    # и добавление колонки С ВНЕШНИМ КЛЮЧОМ падает `NotImplementedError`. На
    # PostgreSQL batch разворачивается в обычный ALTER. Ровно та же ловушка уже
    # встречалась в `e1_contract_0008`.
    with op.batch_alter_table("calendar_tasks") as batch:
        batch.add_column(sa.Column("service_case_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("ticket_segment_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_calendar_tasks_service_case", "service_cases",
                                 ["service_case_id"], ["id"])
        batch.create_foreign_key("fk_calendar_tasks_ticket_segment", "ticket_segments",
                                 ["ticket_segment_id"], ["id"])
    op.create_index("ix_calendar_tasks_service_case_id", "calendar_tasks",
                    ["service_case_id"])
    op.create_index("ix_calendar_tasks_ticket_segment_id", "calendar_tasks",
                    ["ticket_segment_id"])


def downgrade() -> None:
    op.drop_index("uq_ticket_segment_active_position", table_name="ticket_segments")
    op.drop_index("ix_calendar_tasks_ticket_segment_id", table_name="calendar_tasks")
    op.drop_index("ix_calendar_tasks_service_case_id", table_name="calendar_tasks")
    with op.batch_alter_table("calendar_tasks") as batch:
        batch.drop_constraint("fk_calendar_tasks_ticket_segment", type_="foreignkey")
        batch.drop_constraint("fk_calendar_tasks_service_case", type_="foreignkey")
        batch.drop_column("ticket_segment_id")
        batch.drop_column("service_case_id")
    op.drop_table("ticket_segments")
