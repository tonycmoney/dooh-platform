"""formatted media with kept originals

Revision ID: d99eee6e0bdf
Revises: f87b25338da6
Create Date: 2026-10-10 23:04:36.730405

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd99eee6e0bdf'
down_revision: Union[str, Sequence[str], None] = 'f87b25338da6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

fit_mode = sa.Enum('fit', 'fill', name='fit_mode')


def upgrade() -> None:
    """Upgrade schema."""
    # add_column doesn't create the Postgres enum type on its own.
    fit_mode.create(op.get_bind(), checkfirst=True)
    op.add_column('media', sa.Column('source_filename', sa.String(length=300), nullable=True))
    op.add_column('media', sa.Column('source_sha256', sa.String(length=64), nullable=True))
    op.add_column('media', sa.Column('source_size_bytes', sa.BigInteger(), nullable=True))
    op.add_column('media', sa.Column('source_width', sa.Integer(), nullable=True))
    op.add_column('media', sa.Column('source_height', sa.Integer(), nullable=True))
    op.add_column('media', sa.Column('fit_mode', fit_mode, server_default='fit', nullable=False))
    op.add_column('media', sa.Column('format_version', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('media', 'format_version')
    op.drop_column('media', 'fit_mode')
    op.drop_column('media', 'source_height')
    op.drop_column('media', 'source_width')
    op.drop_column('media', 'source_size_bytes')
    op.drop_column('media', 'source_sha256')
    op.drop_column('media', 'source_filename')
    fit_mode.drop(op.get_bind(), checkfirst=True)
