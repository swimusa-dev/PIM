"""incremental ingest: fingerprint of each style's source rows as last loaded

Revision ID: d4a8b5c61e92
Revises: c91e4d2f7a30
Create Date: 2026-10-29 20:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'd4a8b5c61e92'
down_revision = 'c91e4d2f7a30'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('source_style_hash',
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('style_number', sa.String(length=64), nullable=False),
    sa.Column('row_hash', sa.String(length=40), nullable=False),
    sa.Column('loaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('source', 'style_number')
    )


def downgrade() -> None:
    op.drop_table('source_style_hash')
