import sqlalchemy as sa
import requests
from flask import redirect, request
from flask_login import current_user
from functools import wraps
from github import Github, GithubException
from urllib.parse import urlencode
from srht.database import Base, db
from srht.config import cfg
from dispatchsrht.decorators import loginrequired
from dispatchsrht.app import app

_github_client_id = cfg("github", "oauth-client-id", default=None)
_github_client_secret = cfg("github", "oauth-client-secret", default=None)

class GitHubAuthorization(Base):
    __tablename__ = "github_authorization"
    id = sa.Column(sa.Integer, primary_key=True)
    created = sa.Column(sa.DateTime, nullable=False)
    updated = sa.Column(sa.DateTime, nullable=False)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("user.id"))
    user = sa.orm.relationship("User")
    scopes = sa.Column(sa.Unicode(512), nullable=False)
    oauth_token = sa.Column(sa.Unicode(512), nullable=False)

def github_redirect(return_to):
    gh_authorize_url = "https://github.com/login/oauth/authorize"
    # TODO: Do we want to generalize the scopes?
    parameters = {
        "client_id": _github_client_id,
        "scope": "repo",
        "state": return_to,
    }
    return redirect("{}?{}".format(gh_authorize_url, urlencode(parameters)))

def githubloginrequired(f):
    f = loginrequired(f)

    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = GitHubAuthorization.query.filter(
                GitHubAuthorization.user_id == current_user.id
            ).first()
        if not auth:
            return github_redirect(request.path)
        try:
            github = Github(auth.oauth_token)
            return f(github, *args, **kwargs)
        except GithubException:
            db.session.delete(auth)
            db.session.commit()
            return github_redirect(request.path)
    return wrapper

@app.route("/github/callback")
def github_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    resp = requests.post(
            "https://github.com/login/oauth/access_token", headers={
                "Accept": "application/json"
            }, data={
                "client_id": _github_client_id,
                "client_secret": _github_client_secret,
                "code": code,
                "state": state,
            })
    if resp.status_code != 200:
        # TODO: Proper error page
        return "Error"
    json = resp.json()
    access_token = json.get("access_token")
    scopes = json.get("scope")
    auth = GitHubAuthorization()
    auth.user_id = current_user.id
    auth.scopes = scopes
    auth.oauth_token = access_token
    db.session.add(auth)
    db.session.commit()
    return redirect(state)
