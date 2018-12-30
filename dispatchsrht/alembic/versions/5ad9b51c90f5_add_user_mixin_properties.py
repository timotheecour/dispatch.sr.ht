"""Add user mixin properties

Revision ID: 5ad9b51c90f5
Revises: 0b17393b3c4d
Create Date: 2018-12-30 16:10:26.970921

"""

# revision identifiers, used by Alembic.
revision = '5ad9b51c90f5'
down_revision = '0b17393b3c4d'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("user", sa.Column("url", sa.String(256)))
    op.add_column("user", sa.Column("location", sa.Unicode(256)))
    op.add_column("user", sa.Column("bio", sa.Unicode(4096)))


def downgrade():
    op.delete_column("user", "url")
    op.delete_column("user", "location")
    op.delete_column("user", "bio")
