import sqlalchemy as sa
from srht.database import Base

class Task(Base):
    __tablename__ = 'task'
    id = sa.Column(sa.Integer, primary_key=True)
    created = sa.Column(sa.DateTime, nullable=False)
    updated = sa.Column(sa.DateTime, nullable=False)
    name = sa.Column(sa.Unicode(1024), nullable=False)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("user.id"), nullable=False)
    user = sa.orm.relationship("User", backref=sa.orm.backref("tasks"))
    _taskdef = sa.Column("taskdef", sa.Unicode(1024), nullable=False)

    @property
    def taskdef(self):
        from dispatchsrht.tasks.taskdef import taskdef_by_name
        return taskdef_by_name(self._taskdef)
