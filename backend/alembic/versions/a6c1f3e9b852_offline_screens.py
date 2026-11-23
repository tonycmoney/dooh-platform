"""offline screens: per-screen connection mode, tablet-logged outages,
sync overdue alerts; Trillboards removed

Revision ID: a6c1f3e9b852
Revises: e8f4c0b2d357
Create Date: 2026-11-23 17:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a6c1f3e9b852'
down_revision: Union[str, Sequence[str], None] = 'e8f4c0b2d357'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRILLBOARDS_COLUMNS = (
    'trillboards_error',
    'trillboards_attempted_at',
    'trillboards_screen_id',
    'trillboards_embed_url',
    'programmatic_fill',
)


def upgrade() -> None:
    connection_mode = sa.Enum('wifi', 'offline', name='connection_mode')
    connection_mode.create(op.get_bind(), checkfirst=True)
    op.add_column('devices', sa.Column('connection_mode', connection_mode, server_default='wifi', nullable=False))
    op.add_column('devices', sa.Column('connected_since', sa.DateTime(timezone=True), nullable=True))
    for column in TRILLBOARDS_COLUMNS:
        op.drop_column('devices', column)

    op.create_table(
        'device_outages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('device_id', sa.Uuid(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_device_outages_device_id'), 'device_outages', ['device_id'])
    op.create_index(op.f('ix_device_outages_started_at'), 'device_outages', ['started_at'])

    op.execute("ALTER TYPE alert_kind ADD VALUE IF NOT EXISTS 'sync_overdue'")


def downgrade() -> None:
    op.execute("DELETE FROM alerts WHERE kind = 'sync_overdue'")
    # Postgres can't drop one value from an enum; rebuild it without it.
    op.execute("ALTER TYPE alert_kind RENAME TO alert_kind_old")
    op.execute("CREATE TYPE alert_kind AS ENUM ('offline', 'not_playing')")
    op.execute("ALTER TABLE alerts ALTER COLUMN kind TYPE alert_kind USING kind::text::alert_kind")
    op.execute("DROP TYPE alert_kind_old")

    op.drop_index(op.f('ix_device_outages_started_at'), table_name='device_outages')
    op.drop_index(op.f('ix_device_outages_device_id'), table_name='device_outages')
    op.drop_table('device_outages')

    op.add_column('devices', sa.Column('programmatic_fill', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('devices', sa.Column('trillboards_embed_url', sa.Text(), nullable=True))
    op.add_column('devices', sa.Column('trillboards_screen_id', sa.String(length=100), nullable=True))
    op.add_column('devices', sa.Column('trillboards_attempted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('devices', sa.Column('trillboards_error', sa.Text(), nullable=True))
    op.drop_column('devices', 'connected_since')
    op.drop_column('devices', 'connection_mode')
    sa.Enum(name='connection_mode').drop(op.get_bind(), checkfirst=True)
