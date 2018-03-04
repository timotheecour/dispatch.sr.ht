from flask import render_template, request
from flask_login import LoginManager, current_user
from jinja2 import Markup
import locale
import urllib

from srht.config import cfg, cfgi, load_config
load_config("dispatch")
from srht.database import DbSession
db = DbSession(cfg("sr.ht", "connection-string"))
from dispatchsrht.types import User
db.init()

from srht.flask import SrhtFlask
app = SrhtFlask("dispatch", __name__)
app.secret_key = cfg("server", "secret-key")
login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.user_loader
def load_user(username):
    return User.query.filter(User.username == username).first()

login_manager.anonymous_user = lambda: None

try:
    locale.setlocale(locale.LC_ALL, 'en_US')
except:
    pass

builds_sr_ht = cfg("builds.sr.ht", "oauth-client-id")

def oauth_url(return_to):
    return "{}/oauth/authorize?client_id={}&scopes=profile{}&state={}".format(
        meta_sr_ht, meta_client_id,
        "," + builds_sr_ht + "/jobs:write" if builds_sr_ht else "",
        urllib.parse.quote_plus(return_to))

from dispatchsrht.blueprints.html import html
from dispatchsrht.blueprints.auth import auth

app.register_blueprint(html)
app.register_blueprint(auth)

from dispatchsrht.tasks import taskdefs
for taskdef in taskdefs():
    app.register_blueprint(taskdef.blueprint, url_prefix="/" + taskdef.name)

meta_sr_ht = cfg("network", "meta")
meta_client_id = cfg("meta.sr.ht", "oauth-client-id")

@app.context_processor
def inject():
    return {
        "oauth_url": oauth_url(request.full_path),
        "current_user": User.query.filter(User.id == current_user.id).first() \
                if current_user else None,
        "taskdefs": taskdefs
    }
