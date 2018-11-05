from flask import Blueprint, render_template
from flask_login import current_user
from srht.config import cfg
from srht.flask import loginrequired
from dispatchsrht.types import Task
import requests

html = Blueprint('html', __name__)

meta_uri = cfg("meta.sr.ht", "origin")

@html.route("/")
def index():
    if not current_user:
        return render_template("index.html")
    # TODO: pagination
    tasks = Task.query.filter(Task.user_id == current_user.id).all()
    return render_template("dashboard.html", tasks=tasks)

@html.route("/configure")
@loginrequired
def configure():
    return render_template("configure.html")

@html.route("/edit/<task_id>")
@loginrequired
def edit_task(task_id):
    task = Task.query.filter(Task.id == task_id).one_or_none()
    if not task:
        abort(404)
    if task.user_id != current_user.id:
        abort(401)
    taskdef = task.taskdef
    return render_template("configure_task.html",
            view="summary", task=task, taskdef=taskdef)

@html.route("/edit/<task_id>", methods=["POST"])
@loginrequired
def edit_task_POST(task_id):
    task = Task.query.filter(Task.id == task_id).one_or_none()
    if not task:
        abort(404)
    if task.user_id != current_user.id:
        abort(401)
    taskdef = task.taskdef
    return taskdef.edit_POST(task)
