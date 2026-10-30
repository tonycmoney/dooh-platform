"""trillboards programmatic fill

Revision ID: 3c7e1a9b2d40
Revises: 85bef5fbe374
Create Date: 2026-10-30 13:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c7e1a9b2d40'
down_revision: Union[str, Sequence[str], None] = '85bef5fbe374'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('devices', sa.Column('programmatic_fill', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('devices', sa.Column('trillboards_embed_url', sa.Text(), nullable=True))
    op.add_column('devices', sa.Column('trillboards_screen_id', sa.String(length=100), nullable=True))
    op.add_column('devices', sa.Column('trillboards_attempted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('devices', sa.Column('trillboards_error', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('devices', 'trillboards_error')
    op.drop_column('devices', 'trillboards_attempted_at')
    op.drop_column('devices', 'trillboards_screen_id')
    op.drop_column('devices', 'trillboards_embed_url')
    op.drop_column('devices', 'programmatic_fill')
