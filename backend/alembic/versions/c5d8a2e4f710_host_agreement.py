"""host agreement signed on the host page

Revision ID: c5d8a2e4f710
Revises: b4e2c7d91a05
Create Date: 2026-11-17 10:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5d8a2e4f710'
down_revision: Union[str, Sequence[str], None] = 'b4e2c7d91a05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hosts', sa.Column('address', sa.String(length=300), nullable=True))
    op.add_column('hosts', sa.Column('agreement_signed_name', sa.String(length=200), nullable=True))
    op.add_column('hosts', sa.Column('agreement_signed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('hosts', sa.Column('agreement_signed_ip', sa.String(length=64), nullable=True))
    op.add_column('hosts', sa.Column('agreement_version', sa.String(length=20), nullable=True))
    op.add_column('hosts', sa.Column('agreement_text', sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ('agreement_text', 'agreement_version', 'agreement_signed_ip', 'agreement_signed_at',
                'agreement_signed_name', 'address'):
        op.drop_column('hosts', col)
