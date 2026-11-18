"""hosts go back to a revenue share: every host earns 10%

Revision ID: e8f4c0b2d357
Revises: d7e3b9a1c246
Create Date: 2026-11-18 14:00:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e8f4c0b2d357'
down_revision: Union[str, Sequence[str], None] = 'd7e3b9a1c246'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE hosts SET share_percent = 10")
    op.drop_column('hosts', 'monthly_fee')


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column('hosts', sa.Column('monthly_fee', sa.Integer(), server_default='1500', nullable=False))
