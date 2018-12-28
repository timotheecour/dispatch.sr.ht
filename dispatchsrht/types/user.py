import sqlalchemy as sa
import sqlalchemy_utils as sau
from srht.database import Base
from enum import Enum

class UserType(Enum):
    unconfirmed = "unconfirmed"
    active_non_paying = "active_non_paying"
    active_free = "active_free"
    active_paying = "active_paying"
    active_delinquent = "active_delinquent"
    admin = "admin"

class User(Base):
    __tablename__ = 'user'
    id = sa.Column(sa.Integer, primary_key=True)
    username = sa.Column(sa.Unicode(256))
    created = sa.Column(sa.DateTime, nullable=False)
    updated = sa.Column(sa.DateTime, nullable=False)
    oauth_token = sa.Column(sa.String(256), nullable=False)
    oauth_token_expires = sa.Column(sa.DateTime, nullable=False)
    oauth_token_scopes = sa.Column(sa.String, nullable=False, default="")
    email = sa.Column(sa.String(256), nullable=False)
    user_type = sa.Column(
            sau.ChoiceType(UserType, impl=sa.String()),
            nullable=False,
            default=UserType.unconfirmed)

    def __repr__(self):
        return '<User {} {}>'.format(self.id, self.username)

    def is_authenticated(self):
        return True
    def is_active(self):
        return True
    def is_anonymous(self):
        return False
    def get_id(self):
        return self.username

