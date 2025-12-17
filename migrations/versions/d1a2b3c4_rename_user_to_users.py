"""rename user table to users

Revision ID: d1a2b3c4rename
Revises: c8f9a1db2e3f
Create Date: 2025-12-18 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd1a2b3c4rename'
down_revision = 'c8f9a1db2e3f'
branch_labels = None
depends_on = None


def upgrade():
    # Rename the table 'user' to 'users' to avoid reserved keyword issues
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()
    # Only rename if source exists and target does not (avoid DuplicateTable)
    if 'user' in tables and 'users' not in tables:
        try:
            op.rename_table('user', 'users')
        except Exception:
            # best-effort: if rename fails because users exists, ignore
            pass


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = insp.get_table_names()
    if 'users' in tables and 'user' not in tables:
        try:
            op.rename_table('users', 'user')
        except Exception:
            pass
