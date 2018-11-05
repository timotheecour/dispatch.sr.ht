"""Add secrets and autosubmit to Github

Revision ID: 919b5f68d824
Revises: None
Create Date: 2018-11-05 07:31:28.046345

"""

# revision identifiers, used by Alembic.
revision = '919b5f68d824'
down_revision = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column("github_commit_to_build", sa.Column("secrets",
        sa.Boolean(), nullable=False, server_default='t'))
    op.add_column("github_pr_to_build", sa.Column("automerge",
        sa.Boolean(), nullable=False, server_default='f'))


def downgrade():
    op.drop_column("github_commit_to_build", "secrets")
    op.drop_column("github_pr_to_build", "automerge")
