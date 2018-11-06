from flask import Blueprint, render_template, request, redirect, url_for, abort
from flask_login import current_user
from srht.config import cfg
from srht.database import db
from srht.flask import loginrequired, paginate_query
from dispatchsrht.types import Task
import requests

html = Blueprint('html', __name__)

meta_uri = cfg("meta.sr.ht", "origin")

@html.route("/")
def index():
    if not current_user:
        return render_template("index.html")
    tasks = Task.query.filter(Task.user_id == current_user.id)
    search = request.args.get("search")
    if search:
        tasks = tasks.filter(Task.name.ilike("%" + search + "%"))
    tasks = tasks.order_by(Task.updated.desc())
    tasks, pagination = paginate_query(tasks)
    return render_template("dashboard.html",
            tasks=tasks, search=search, **pagination)

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
    return render_template("task-settings.html", view="summary",
            task=task, taskdef=taskdef)

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

@html.route("/delete/<task_id>")
@loginrequired
def delete_task(task_id):
    task = Task.query.filter(Task.id == task_id).one_or_none()
    if not task:
        abort(404)
    if task.user_id != current_user.id:
        abort(401)
    return render_template("task-delete.html", view="delete", task=task)

@html.route("/delete/<task_id>", methods=["POST"])
@loginrequired
def delete_task_POST(task_id):
    task = Task.query.filter(Task.id == task_id).one_or_none()
    if not task:
        abort(404)
    if task.user_id != current_user.id:
        abort(401)
    db.session.delete(task)
    db.session.commit()
    return redirect(url_for("html.index"))
