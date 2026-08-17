"""Remember Bitrix dossiers written by the bot.

Revision ID: bitrix_dossier_0006
Revises: bitrix_pipeline_0005
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bitrix_dossier_0006"
down_revision: Union[str, None] = "bitrix_pipeline_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("conversations"):
        return
    op.add_column(
        "conversations",
        sa.Column("bitrix_dossier_by_bot", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("conversations"):
        return
    op.drop_column("conversations", "bitrix_dossier_by_bot")
