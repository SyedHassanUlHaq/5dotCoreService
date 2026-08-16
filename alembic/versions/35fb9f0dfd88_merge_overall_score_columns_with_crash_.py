"""merge overall-score columns with crash and bug reports

Revision ID: 35fb9f0dfd88
Revises: c9b6e2a4f7d3, e1ff2120acec
Create Date: 2026-08-16 11:05:57.612716

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '35fb9f0dfd88'
down_revision: Union[str, Sequence[str], None] = ('c9b6e2a4f7d3', 'e1ff2120acec')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
