"""Add secrets to GitHub PRs

Revision ID: 986fd25d5184
Revises: 5ad9b51c90f5
Create Date: 2019-06-21 10:36:22.290121

"""

# revision identifiers, used by Alembic.
revision = '986fd25d5184'
down_revision = '5ad9b51c90f5'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('github_pr_to_build', sa.Column('private',
            sa.Boolean, nullable=False, server_default='f'))
    op.add_column('github_pr_to_build', sa.Column('secrets',
            sa.Boolean, nullable=False, server_default='f'))


def downgrade():
    op.add_drop('github_pr_to_build', 'private')
    op.add_drop('github_pr_to_build', 'secrets')
