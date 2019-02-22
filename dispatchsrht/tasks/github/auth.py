import base64
import html
import json
import sqlalchemy as sa
import re
import requests
import yaml
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import redirect, request, url_for
from flask_login import current_user
from functools import wraps
from github import Github, GithubException
from urllib.parse import urlencode
from srht.config import cfg
from srht.database import Base, db
from srht.flask import loginrequired, csrf_bypass
from dispatchsrht.app import app

def _first_line(text):
    if not "\n" in text:
        return text
    return text[:text.index("\n") + 1]

_github_client_id = cfg("dispatch.sr.ht::github",
        "oauth-client-id", default=None)
_github_client_secret = cfg("dispatch.sr.ht::github",
        "oauth-client-secret", default=None)

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
    return loginrequired(wrapper)

@app.route("/github/callback")
@loginrequired
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

_root = cfg("dispatch.sr.ht", "origin")
_builds_sr_ht = cfg("builds.sr.ht", "origin", default=None)
_secret_key = cfg("sr.ht", "secret-key")
_kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_secret_key.encode(),
        iterations=100000,
        backend=default_backend())
_key = base64.urlsafe_b64encode(_kdf.derive(_secret_key.encode()))
_fernet = Fernet(_key)

def submit_build(hook, repo, commit, base=None, secrets=False, extras=dict()):
    if base == None:
        base = repo
    auth = GitHubAuthorization.query.filter(
        GitHubAuthorization.user_id == hook.user_id).first()
    if not auth:
        return "You have not authorized us to access your GitHub account", 401
    github = Github(auth.oauth_token)
    try:
        repo = github.get_repo(repo["full_name"])
        base = github.get_repo(base["full_name"])
        sha = commit.get("sha") or commit.get("id")
        commit = repo.get_commit(sha)
    except GithubException:
        return ("We can't access your GitHub account. "
            "Did you revoke our access?"), 401
    base_commit = base.get_commit(sha)
    git_commit = commit.commit
    try:
        manifest = repo.get_contents(".build.yml", ref=git_commit.sha)
    except GithubException:
        manifest = None
    if manifest is not None:
        manifests = [manifest]
    else:
        try:
            manifests = repo.get_dir_contents(
                    ".builds", ref=git_commit.sha) or []
            manifests = [repo.get_contents(m.path, ref=git_commit.sha)
                    for m in manifests]
        except GithubException:
            manifests = []
    if not manifests:
        return "There are no build manifest in this repository"
    build_urls = []
    for manifest in manifests:
        name = manifest.name
        manifest = base64.b64decode(manifest.content)
        from buildsrht.manifest import Manifest, Trigger
        try:
            manifest = Manifest(yaml.safe_load(manifest))
        except Exception as ex:
            return f"There are errors in {name}:\n{str(ex)}", 400
        if manifest.sources:
            manifest.sources = [
                source if not source.endswith("/" + repo.name) else
                    repo.clone_url + "#" + git_commit.sha
                for source in manifest.sources
            ]
        context = "builds.sr.ht" + (f": {name}" if name else "")
        try:
            status = base_commit.create_status("pending", _builds_sr_ht,
                    "preparing builds.sr.ht job", context=context)
        except GithubException:
            return "Unable to add status to commit", 400
        complete_url = completion_url(base.full_name, auth.user.username,
                auth.oauth_token, commit.sha, context, extras)
        manifest.triggers.append(Trigger({
            "action": "webhook",
            "condition": "always",
            "url": complete_url,
        }))
        repo_name = re.sub(r"[^a-z0-9_.-]", "", repo.name.lower())
        if name:
            name = re.sub(r"[^a-z0-9_.-]", "", name.lower())
        resp = requests.post(_builds_sr_ht + "/api/jobs", json={
            "manifest": yaml.dump(manifest.to_dict(), default_flow_style=False),
            "tags": [repo_name] + ([name] if name else []),
            "note": "{}\n\n[{}]({}) &mdash; [{}](mailto:{})".format(
                html.escape(_first_line(git_commit.message)),
                str(git_commit.sha)[:7], commit.html_url,
                git_commit.author.name,
                git_commit.author.email,
            ),
            "secrets": secrets,
        }, headers={
            "Authorization": "token " + hook.user.oauth_token,
        })
        if resp.status_code != 200:
            return resp.text
        build_id = resp.json()["id"]
        build_url = "{}/~{}/job/{}".format(
                _builds_sr_ht, auth.user.username, build_id)
        status = base_commit.create_status("pending", build_url,
                "builds.sr.ht job is running",
                context=context)
        build_urls.append(build_url)
    return "Started builds:\n\n" + "\n".join(build_urls)

def completion_url(full_name, username, oauth_token, sha, context, extras):
    complete_request = {
        "full_name": full_name,
        "oauth_token": oauth_token,
        "username": username,
        "sha": sha,
        "context": context,
    }
    complete_request.update(extras)
    complete_payload = _fernet.encrypt(
            json.dumps(complete_request).encode()).decode()
    complete_url = _root + url_for("github_complete_build",
            payload=complete_payload)
    return complete_url

@csrf_bypass
@app.route("/github/complete_build/<payload>", methods=["POST"])
def github_complete_build(payload):
    payload = json.loads(_fernet.decrypt(payload.encode()).decode())
    github = Github(payload["oauth_token"])
    repo = github.get_repo(payload["full_name"])
    commit = repo.get_commit(payload["sha"])
    result = json.loads(request.data.decode('utf-8'))
    context = payload.get("context")
    try:
        commit.create_status(
            "success" if result["status"] == "success" else "failure",
            "{}/~{}/job/{}".format(_builds_sr_ht, payload["username"], result["id"]),
            "builds.sr.ht job {}".format(
                "completed successfully" if result["status"] == "success"
                    else "failed"),
            context=context)
    except GithubException:
        return "Error updating GitHub status"
    pr = payload.get("pr")
    if pr:
        pr = repo.get_pull(pr)
    automerge = payload.get("automerge")
    if pr and not pr.is_merged() and automerge and result["status"] == "success":
        requested_reviews = pr.get_review_requests()
        # Don't merge if there are outstanding review requests
        if not any(requested_reviews[0]) and not any(requested_reviews[1]):
            try:
                pr.merge()
            except GithubException:
                return "Unable to merge automatically (failing rules?)"
    return "Sent build status to GitHub"
