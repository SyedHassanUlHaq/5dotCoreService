"""add bug_reports table

Revision ID: c9b6e2a4f7d3
Revises: a7c4e5f8d1b2
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9b6e2a4f7d3'
down_revision: Union[str, Sequence[str], None] = 'a7c4e5f8d1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'bug_reports',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('steps_to_reproduce', sa.Text(), nullable=True),
        sa.Column('severity', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('platform', sa.String(), nullable=True),
        sa.Column('app_version', sa.String(), nullable=True),
        sa.Column('os_version', sa.String(), nullable=True),
        sa.Column('device_model', sa.String(), nullable=True),
        sa.Column('context', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('bug_reports')
