"""E2-01: попытки бронирования тура.

Аддитивная: одна новая таблица. Отказ оператора не закрывает услугу и не трогает
деньги — поэтому здесь нет ни флагов закрытия, ни денежных колонок: деньги живут
в journal `service_payments` (E2-03), а этапы — в `service_cases`.

Revision ID: e2_bookings_0011
Revises: e2_tickets_0010
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2_bookings_0011"
down_revision = "e2_tickets_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booking_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("service_cases.id"),
                  nullable=False, index=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("operator", sa.String(length=128), nullable=False),
        sa.Column("country", sa.String(length=64), nullable=False),
        sa.Column("hotel", sa.String(length=255), nullable=False),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column("tourists", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("price", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="requested"),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decline_reason", sa.String(length=500), nullable=True),
        sa.Column("supersedes_id", sa.Integer(),
                  sa.ForeignKey("booking_attempts.id"), nullable=True),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("case_id", "attempt", name="uq_booking_attempt_number"),
        sa.CheckConstraint("attempt >= 1", name="ck_booking_attempt_number"),
        sa.CheckConstraint("check_out > check_in", name="ck_booking_attempt_dates"),
        sa.CheckConstraint("price IS NULL OR price > 0",
                           name="ck_booking_attempt_price"),
        sa.CheckConstraint("(price IS NULL) = (currency IS NULL)",
                           name="ck_booking_attempt_price_currency"),
        sa.CheckConstraint(
            "status IN ('requested', 'confirmed', 'declined', 'cancelled')",
            name="ck_booking_attempt_status"),
        # Подтверждённая бронь обязана иметь номер и дату: иначе «подтверждено» —
        # это слово менеджера, которое потом нечем подтвердить (FLOW-03).
        sa.CheckConstraint(
            "status <> 'confirmed'"
            " OR (reference IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_booking_attempt_confirmed_facts"),
        sa.CheckConstraint("status <> 'declined' OR decline_reason IS NOT NULL",
                           name="ck_booking_attempt_decline_reason"),
        sa.CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id",
                           name="ck_booking_attempt_no_self_supersede"),
    )


def downgrade() -> None:
    op.drop_table("booking_attempts")
