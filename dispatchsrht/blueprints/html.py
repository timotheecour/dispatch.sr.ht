from flask import Blueprint, render_template
from flask_login import current_user
from srht.config import cfg
from dispatchsrht.decorators import loginrequired
import requests

html = Blueprint('html', __name__)

meta_uri = cfg("network", "meta")

@html.route("/")
def index():
    if not current_user:
        return render_template("index.html")
    return render_template("dashboard.html")

@html.route("/configure")
@loginrequired
def configure():
    return render_template("configure.html")
