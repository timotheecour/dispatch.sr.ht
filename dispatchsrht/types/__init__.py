from srht.database import Base
from srht.oauth import ExternalUserMixin

class User(Base, ExternalUserMixin):
    pass

from dispatchsrht.types.task import Task
