"""add image blob and mime columns

Revision ID: c8f9a1db2e3f
Revises: b3e4f6a5e76a
Create Date: 2025-12-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8f9a1db2e3f'
down_revision = 'b3e4f6a5e76a'
branch_labels = None
depends_on = None


def upgrade():
    # Add columns to store image bytes and mime types
    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.add_column(sa.Column('image_blob', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('image_mime', sa.String(length=100), nullable=True))

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar_blob', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('avatar_mime', sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('avatar_mime')
        batch_op.drop_column('avatar_blob')

    with op.batch_alter_table('post', schema=None) as batch_op:
        batch_op.drop_column('image_mime')
        batch_op.drop_column('image_blob')
