"""qr scan tracking

Revision ID: b4e2c7d91a05
Revises: 3c7e1a9b2d40
Create Date: 2026-11-05 13:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4e2c7d91a05'
down_revision: Union[str, Sequence[str], None] = '3c7e1a9b2d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'qr_links',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('label', sa.String(length=300), nullable=False),
        sa.Column('target_url', sa.Text(), nullable=False),
        sa.Column('media_id', sa.Uuid(), nullable=True),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_qr_links_code'), 'qr_links', ['code'], unique=True)
    op.create_index(op.f('ix_qr_links_media_id'), 'qr_links', ['media_id'], unique=False)
    op.create_table(
        'qr_scans',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('link_id', sa.Uuid(), nullable=False),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('visitor', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['link_id'], ['qr_links.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_qr_scans_link_id'), 'qr_scans', ['link_id'], unique=False)
    op.create_index(op.f('ix_qr_scans_scanned_at'), 'qr_scans', ['scanned_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_qr_scans_scanned_at'), table_name='qr_scans')
    op.drop_index(op.f('ix_qr_scans_link_id'), table_name='qr_scans')
    op.drop_table('qr_scans')
    op.drop_index(op.f('ix_qr_links_media_id'), table_name='qr_links')
    op.drop_index(op.f('ix_qr_links_code'), table_name='qr_links')
    op.drop_table('qr_links')
