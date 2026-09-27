"""stub: reconnect missing production revision

This revision was applied to the production database but the migration file
was never committed to the repository. This stub re-anchors the chain so
subsequent migrations can run.

Revision ID: d4a1f7b9c2e6
Revises: 35fb9f0dfd88
Create Date: 2026-09-27

"""
from alembic import op
import sqlalchemy as sa
from typing import Union, Sequence

revision: str = 'd4a1f7b9c2e6'
down_revision: Union[str, Sequence[str], None] = '35fb9f0dfd88'
branch_labels = None
depends_on = None


def upgrade():
    pass  # already applied on production


def downgrade():
    pass
