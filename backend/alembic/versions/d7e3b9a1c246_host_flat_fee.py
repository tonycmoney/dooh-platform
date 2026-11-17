"""hosts earn a flat monthly fee per screen

Revision ID: d7e3b9a1c246
Revises: c5d8a2e4f710
Create Date: 2026-11-17 13:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e3b9a1c246'
down_revision: Union[str, Sequence[str], None] = 'c5d8a2e4f710'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hosts', sa.Column('monthly_fee', sa.Integer(), server_default='1500', nullable=False))
    # Every existing host moves to the flat fee.
    op.execute("UPDATE hosts SET share_percent = 0")


def downgrade() -> None:
    op.drop_column('hosts', 'monthly_fee')
