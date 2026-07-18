"""WP1B: DB-level Dialog idempotency — unique index on (channel, bot_id, channel_key).

Additive-only. Adds a single unique index to the existing ``dialogs`` domain table
so the shadow bridge cannot create a duplicate Dialog for the same channel thread.
Touches NO legacy table and no other domain table.

Revision ID: wp1b_dialog_uidx_0002
Revises: wp1a_domain_0001
Create Date: 2026-07-18

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "wp1b_dialog_uidx_0002"
down_revision: Union[str, None] = "wp1a_domain_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_dialog_channel_bot_key", "dialogs",
        ["channel", "bot_id", "channel_key"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_dialog_channel_bot_key", table_name="dialogs")
