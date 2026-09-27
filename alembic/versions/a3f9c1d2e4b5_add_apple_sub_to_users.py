"""add apple_sub to users

Revision ID: a3f9c1d2e4b5
Revises: f3a1c9d2e7b4
Create Date: 2026-09-08

"""
from alembic import op
import sqlalchemy as sa

revision = 'a3f9c1d2e4b5'
down_revision = 'd4a1f7b9c2e6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('apple_sub', sa.String(), nullable=True))
    op.create_index('ix_users_apple_sub', 'users', ['apple_sub'], unique=True)


def downgrade():
    op.drop_index('ix_users_apple_sub', table_name='users')
    op.drop_column('users', 'apple_sub')
