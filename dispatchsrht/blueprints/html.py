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
