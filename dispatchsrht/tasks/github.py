import base64
import html
import json
import requests
import sqlalchemy as sa
import sqlalchemy_utils as sau
import yaml
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from functools import wraps
from github import Github, GithubException
from flask import Blueprint, redirect, request, render_template, url_for, abort
from flask_login import current_user
from jinja2 import Markup
from urllib.parse import urlencode
from uuid import UUID, uuid4
from srht.database import Base, db
from srht.config import cfg
from srht.validation import Validation
from dispatchsrht.app import app
from dispatchsrht.decorators import loginrequired
from dispatchsrht.tasks import TaskDef
from dispatchsrht.types import Task

def first_line(text):
    if not "\n" in text:
        return text
    return text[:text.index("\n") + 1]

_root = "{}://{}".format(cfg("server", "protocol"), cfg("server", "domain"))
_builds_sr_ht = cfg("network", "builds", default=None)
_github_client_id = cfg("github", "oauth-client-id", default=None)
_github_client_secret = cfg("github", "oauth-client-secret", default=None)
_secret_key = cfg("server", "secret-key")
_kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_secret_key.encode(),
        iterations=100000,
        backend=default_backend())
_key = base64.urlsafe_b64encode(_kdf.derive(_secret_key.encode()))
_fernet = Fernet(_key)

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

class GitHubCommitToBuild(TaskDef):
    name = "github_commit_to_build"
    description = Markup('''
        <i class="fa fa-github"></i>
        GitHub commits
        <i class="fa fa-arrow-right"></i>
        builds.sr.ht jobs
    ''')
    enabled = bool(_github_client_id and _github_client_secret and _builds_sr_ht)

    class _GitHubCommitToBuildRecord(Base):
        __tablename__ = "github_commit_to_build"
        id = sa.Column(sau.UUIDType, primary_key=True)
        created = sa.Column(sa.DateTime, nullable=False)
        updated = sa.Column(sa.DateTime, nullable=False)
        user_id = sa.Column(sa.Integer,
                sa.ForeignKey("user.id", ondelete="CASCADE"))
        user = sa.orm.relationship("User")
        task_id = sa.Column(sa.Integer,
                sa.ForeignKey("task.id", ondelete="CASCADE"))
        task = sa.orm.relationship("Task")
        repo = sa.Column(sa.Unicode(1024), nullable=False)
        github_webhook_id = sa.Column(sa.Integer, nullable=False)

    blueprint = Blueprint("github_commit_to_build",
            __name__, template_folder="github_commit_to_build")

    @blueprint.route("/webhook/<record_id>", methods=["POST"])
    def _webhook(record_id):
        record_id = UUID(record_id)
        hook = GitHubCommitToBuild._GitHubCommitToBuildRecord.query.filter(
                GitHubCommitToBuild._GitHubCommitToBuildRecord.id == record_id
            ).first()
        if not hook:
            abort(404)
        valid = Validation(request)
        commit = valid.require("head_commit")
        repo = valid.require("repository")
        if not valid.ok:
            return "Got request, but it has no commits"
        auth = GitHubAuthorization.query.filter(
            GitHubAuthorization.user_id == hook.user_id).first()
        if not auth:
            return "You have not authorized us to access your GitHub account", 401
        github = Github(auth.oauth_token)
        repo = github.get_repo(repo["full_name"])
        commit = repo.get_commit(commit["id"])
        git_commit = commit.commit
        manifest = repo.get_contents(".build.yml", ref=git_commit.sha)
        if not manifest:
            return "There's no build manifest in this repository"
        manifest = base64.b64decode(manifest.content)
        from buildsrht.manifest import Manifest, Trigger
        manifest = Manifest(yaml.safe_load(manifest))
        manifest.sources = [
            source if not source.endswith("/" + repo.name) else
                repo.clone_url + "#" + git_commit.sha
            for source in manifest.sources
        ]
        status = commit.create_status("pending", _builds_sr_ht,
                "preparing builds.sr.ht job", context="builds.sr.ht")
        complete_request = {
            "full_name": repo.full_name,
            "oauth_token": auth.oauth_token,
            "sha": commit.sha,
        }
        complete_payload = _fernet.encrypt(
                json.dumps(complete_request).encode()).decode()
        complete_url = _root + url_for("github_commit_to_build.complete",
                payload=complete_payload)
        manifest.triggers.append(Trigger({
            "action": "webhook",
            "condition": "always",
            "url": complete_url,
        }))
        resp = requests.post(_builds_sr_ht + "/api/jobs", json={
            "manifest": yaml.dump(manifest.to_dict(), default_flow_style=False),
            "note": "{}\n\n[{}]({}) &mdash; [{}](mailto:{})".format(
                html.escape(first_line(git_commit.message)),
                str(git_commit.sha)[:7], commit.url,
                git_commit.author.name,
                git_commit.author.email,
            )
        }, headers={
            "Authorization": "token " + hook.user.oauth_token,
        })
        if resp.status_code != 200:
            return resp.text
        build_id = resp.json()["id"]
        build_url = _builds_sr_ht + "/job/" + str(build_id)
        status = commit.create_status("pending", build_url,
                "builds.sr.ht job is running", context="builds.sr.ht")
        return "Started build: " + build_url

    @blueprint.route("/complete/<payload>", methods=["POST"])
    def complete(payload):
        payload = json.loads(_fernet.decrypt(payload.encode()).decode())
        github = Github(payload["oauth_token"])
        repo = github.get_repo(payload["full_name"])
        commit = repo.get_commit(payload["sha"])
        result = json.loads(request.data.decode('utf-8'))
        commit.create_status(
                "success" if result["status"] == "success" else "failure",
                _builds_sr_ht + "/job/" + str(result["id"]),
                "builds.sr.ht job completed",
                context="builds.sr.ht")
        return "Sent build status to GitHub"

    @blueprint.route("/configure")
    @githubloginrequired
    def configure(github):
        repos = github.get_user().get_repos(sort="updated")
        repos = filter(lambda r: r.permissions.admin and not r.fork, repos)
        existing = GitHubCommitToBuild._GitHubCommitToBuildRecord.query.filter(
                GitHubCommitToBuild._GitHubCommitToBuildRecord.user_id ==
                current_user.id).all()
        existing = [e.repo for e in existing]
        return render_template("github_commit_to_build/configure.html",
                repos=repos, existing=existing)

    @blueprint.route("/configure", methods=["POST"])
    @githubloginrequired
    def _configure_POST(github):
        valid = Validation(request)
        repo = valid.require("repo")
        if not valid.ok:
            return "quit yo hackin bullshit"
        repo = github.get_repo(repo)
        if not repo:
            return "quit yo hackin bullshit"
        task = Task()
        task.name = "{}::github_commit_to_build".format(repo.full_name)
        task._taskdef = "github_commit_to_build"
        db.session.add(task)
        db.session.flush()
        record = GitHubCommitToBuild._GitHubCommitToBuildRecord()
        record.id = uuid4()
        record.user_id = current_user.id
        record.task_id = task.id
        record.github_webhook_id = -1
        record.repo = repo.full_name
        db.session.add(record)
        db.session.flush()
        hook = repo.create_hook("web", {
            "url": _root + url_for("github_commit_to_build._webhook",
                record_id=record.id),
            "content_type": "json",
        }, ["push"], active=True)
        record.github_webhook_id = hook.id
        db.session.commit()
        # TODO: redirect to task page
        return redirect("/")
