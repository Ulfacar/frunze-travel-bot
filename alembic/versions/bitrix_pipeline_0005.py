"""Add Bitrix lead pipeline bookkeeping fields.

Revision ID: bitrix_pipeline_0005
Revises: sprint1_calendar_0004
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bitrix_pipeline_0005"
down_revision: Union[str, None] = "sprint1_calendar_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The domain-only migration test database intentionally has no legacy panel tables.
    if not sa.inspect(op.get_bind()).has_table("conversations"):
        return
    op.add_column("conversations", sa.Column("bitrix_stage_by_bot", sa.String(32),
                                              server_default="", nullable=False))
    op.add_column("conversations", sa.Column("bitrix_deal_id", sa.String(32),
                                              server_default="", nullable=False))


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("conversations"):
        return
    op.drop_column("conversations", "bitrix_deal_id")
    op.drop_column("conversations", "bitrix_stage_by_bot")
