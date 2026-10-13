"""E2-04: захват задачи в обработку — надёжность при рестарте.

Аддитивная: две nullable-колонки в `calendar_tasks`. Существующие задачи не
затрагиваются, у них захвата просто нет.

Зачем: если процесс упал между «взял задачу» и «получил результат», повторять
действие слепо нельзя — клиент получит второе сообщение. Незавершённый захват
остаётся видимым, и перед повтором его сверяют (AC-28).

Revision ID: e2_taskclaim_0012
Revises: e2_bookings_0011
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2_taskclaim_0012"
down_revision = "e2_bookings_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("calendar_tasks") as batch:
        batch.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True),
                                   nullable=True))
        batch.add_column(sa.Column("claimed_by", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("calendar_tasks") as batch:
        batch.drop_column("claimed_by")
        batch.drop_column("claimed_at")
