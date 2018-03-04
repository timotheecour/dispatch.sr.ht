import sqlalchemy as sa
from srht.database import Base

class Task(Base):
    __tablename__ = 'task'
    id = sa.Column(sa.Integer, primary_key=True)
    created = sa.Column(sa.DateTime, nullable=False)
    updated = sa.Column(sa.DateTime, nullable=False)
    name = sa.Column(sa.Unicode(1024), nullable=False)
    _taskdef = sa.Column("taskdef", sa.Unicode(1024), nullable=False)
