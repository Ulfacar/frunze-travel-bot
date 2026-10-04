"""E2-03: журнал денег по услуге — оплаты, возвраты, остаток.

Аддитивная: создаёт одну новую таблицу, существующие не трогает. Остаток нигде не
хранится, он считается по журналу, поэтому колонок с «итого» здесь нет и быть
не должно — иначе появится второй источник правды.

Revision ID: e2_payments_0009
Revises: e1_contract_0008
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2_payments_0009"
down_revision = "e1_contract_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("service_cases.id"),
                  nullable=False, index=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("fx_rate", sa.Numeric(18, 6), nullable=True),
        sa.Column("fx_to", sa.String(length=3), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("corrects_id", sa.Integer(), sa.ForeignKey("service_payments.id"),
                  nullable=True),
        sa.Column("settles_id", sa.Integer(), sa.ForeignKey("service_payments.id"),
                  nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("recorded_by", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_service_payment_idempotency"),
        sa.CheckConstraint("amount > 0", name="ck_service_payment_amount_positive"),
        sa.CheckConstraint("length(trim(currency)) = 3",
                           name="ck_service_payment_currency"),
        sa.CheckConstraint("fx_rate IS NULL OR fx_rate > 0",
                           name="ck_service_payment_rate_positive"),
        sa.CheckConstraint("(fx_rate IS NULL) = (fx_to IS NULL)",
                           name="ck_service_payment_rate_needs_target"),
        sa.CheckConstraint("corrects_id IS NULL OR corrects_id <> id",
                           name="ck_service_payment_no_self_correction"),
        sa.CheckConstraint("settles_id IS NULL OR settles_id <> id",
                           name="ck_service_payment_no_self_settlement"),
        sa.CheckConstraint(
            "kind IN ('payment', 'refund_due', 'refund_paid', 'correction', 'void')",
            name="ck_service_payment_kind"),
    )
    # Одну строку исправляет ровно одна: вторая поправка к той же строке не
    # проходит, иначе обе суммировались бы в остатке.
    op.create_index("uq_service_payment_corrects", "service_payments", ["corrects_id"],
                    unique=True, sqlite_where=sa.text("corrects_id IS NOT NULL"),
                    postgresql_where=sa.text("corrects_id IS NOT NULL"))


def downgrade() -> None:
    # Внимание: сносит всю денежную историю. Планом отката после первой реальной
    # оплаты это не является — там нужен бэкап, а не downgrade.
    op.drop_index("uq_service_payment_corrects", table_name="service_payments")
    op.drop_table("service_payments")
