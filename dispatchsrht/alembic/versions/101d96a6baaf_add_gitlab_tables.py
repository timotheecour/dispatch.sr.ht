"""Add gitlab tables

Revision ID: 101d96a6baaf
Revises: 986fd25d5184
Create Date: 2019-10-23 12:40:05.563827

"""

# revision identifiers, used by Alembic.
revision = '101d96a6baaf'
down_revision = '986fd25d5184'

from alembic import op
import sqlalchemy as sa
import sqlalchemy_utils as sau


def upgrade():
    op.create_table('gitlab_authorization',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('created', sa.DateTime, nullable=False),
        sa.Column('updated', sa.DateTime, nullable=False),
        sa.Column('user_id', sa.Integer, sa.ForeignKey("user.id")),
        sa.Column('upstream', sa.Unicode, nullable=False),
        sa.Column('oauth_token', sa.Unicode(512), nullable=False))

    op.create_table('gitlab_commit_to_build',
        sa.Column('id', sau.UUIDType, primary_key=True),
        sa.Column('created', sa.DateTime, nullable=False),
        sa.Column('updated', sa.DateTime, nullable=False),
        sa.Column('user_id', sa.Integer,
            sa.ForeignKey("user.id", ondelete="CASCADE")),
        sa.Column('task_id', sa.Integer,
            sa.ForeignKey("task.id", ondelete="CASCADE")),
        sa.Column('repo_name', sa.Unicode, nullable=False),
        sa.Column('repo_id', sa.Integer, nullable=False),
        sa.Column('web_url', sa.Unicode, nullable=False),
        sa.Column('gitlab_webhook_id', sa.Integer, nullable=False),
        sa.Column('secrets', sa.Boolean, nullable=False, server_default='t'),
        sa.Column('upstream', sa.Unicode, nullable=False))

    op.create_table('gitlab_mr_to_build',
        sa.Column('id', sau.UUIDType, primary_key=True),
        sa.Column('created', sa.DateTime, nullable=False),
        sa.Column('updated', sa.DateTime, nullable=False),
        sa.Column('user_id', sa.Integer,
                sa.ForeignKey("user.id", ondelete="CASCADE")),
        sa.Column('task_id', sa.Integer,
                sa.ForeignKey("task.id", ondelete="CASCADE")),
        sa.Column('repo_name', sa.Unicode(1024), nullable=False),
        sa.Column('repo_id', sa.Integer, nullable=False),
        sa.Column('web_url', sa.Unicode, nullable=False),
        sa.Column('gitlab_webhook_id', sa.Integer, nullable=False),
        sa.Column('upstream', sa.Unicode, nullable=False),
        sa.Column('private', sa.Boolean, nullable=False, server_default='f'),
        sa.Column('secrets', sa.Boolean, nullable=False, server_default='f'))

def downgrade():
    op.drop_table('gitlab_authorization')
    op.drop_table('gitlab_commit_to_build')
    op.drop_table('gitlab_mr_to_build')
