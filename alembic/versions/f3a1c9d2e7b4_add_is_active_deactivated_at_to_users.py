"""add is_active/deactivated_at to users, cascade payments on user delete

Revision ID: f3a1c9d2e7b4
Revises: 8b12b89bb66e
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a1c9d2e7b4'
down_revision: Union[str, Sequence[str], None] = '8b12b89bb66e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('users', sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('users', 'is_active', server_default=None)

    op.drop_constraint('payments_user_id_fkey', 'payments', type_='foreignkey')
    op.create_foreign_key(
        'payments_user_id_fkey', 'payments', 'users', ['user_id'], ['id'], ondelete='CASCADE'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('payments_user_id_fkey', 'payments', type_='foreignkey')
    op.create_foreign_key('payments_user_id_fkey', 'payments', 'users', ['user_id'], ['id'])

    op.drop_column('users', 'deactivated_at')
    op.drop_column('users', 'is_active')
