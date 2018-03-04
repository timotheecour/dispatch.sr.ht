_taskdefs = dict()

class _TaskDefMeta(type):
    def __new__(cls, clsname, bases, members):
        if clsname == "TaskDef":
            return type.__new__(cls, clsname, bases, members)
        _ = type.__new__(cls, clsname, bases, members)
        _taskdefs[members["name"]] = _
        return _

class TaskDef(metaclass=_TaskDefMeta):
    pass

def taskdefs():
    return _taskdefs.values()

def taskdef_by_name(name):
    return _taskdefs.get(name)
