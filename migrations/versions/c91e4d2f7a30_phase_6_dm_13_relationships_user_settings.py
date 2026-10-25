"""phase 6 (DM-13, DM-07/DM-09): relationship types, product relationships, user settings

Revision ID: c91e4d2f7a30
Revises: a28bb6bffd12
Create Date: 2026-10-25 15:10:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'c91e4d2f7a30'
down_revision = 'a28bb6bffd12'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('relationship_type',
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('direction', sa.String(length=8), nullable=False),
    sa.Column('level', sa.String(length=16), nullable=False),
    sa.Column('allows_quantity', sa.Boolean(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('help_text', sa.String(length=300), nullable=True),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('product_relationship',
    sa.Column('type_code', sa.String(length=64), nullable=False),
    sa.Column('from_entity_id', sa.String(length=36), nullable=False),
    sa.Column('to_entity_id', sa.String(length=36), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=True),
    sa.Column('mirror_of', sa.String(length=36), nullable=True),
    sa.Column('created_by', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['from_entity_id'], ['product_entity.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_entity_id'], ['product_entity.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['type_code'], ['relationship_type.code']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('type_code', 'from_entity_id', 'to_entity_id', name='uq_relationship')
    )
    op.create_index('ix_relationship_from', 'product_relationship', ['from_entity_id'], unique=False)
    op.create_index('ix_relationship_to', 'product_relationship', ['to_entity_id'], unique=False)
    op.create_table('user_setting',
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('digest_frequency', sa.String(length=8), nullable=False),
    sa.Column('last_digest_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('email')
    )


def downgrade() -> None:
    op.drop_table('user_setting')
    op.drop_index('ix_relationship_to', table_name='product_relationship')
    op.drop_index('ix_relationship_from', table_name='product_relationship')
    op.drop_table('product_relationship')
    op.drop_table('relationship_type')
