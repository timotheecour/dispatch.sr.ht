import base64
import html
import json
import requests
import sqlalchemy as sa
import yaml
from dispatchsrht.app import app
from dispatchsrht.builds import decrypt_notify_payload, submit_build
from dispatchsrht.builds import first_line, encrypt_notify_url
from flask import redirect, request, url_for
from functools import wraps
from github import Github, GithubException
from srht.config import cfg
from srht.database import Base, db
from srht.flask import csrf_bypass
from srht.oauth import current_user, loginrequired
from urllib.parse import urlencode

_github_client_id = cfg("dispatch.sr.ht::github",
        "oauth-client-id", default=None)
_github_client_secret = cfg("dispatch.sr.ht::github",
        "oauth-client-secret", default=None)
_builds_sr_ht = cfg("builds.sr.ht", "origin", default=None)

if _builds_sr_ht:
    from buildsrht.manifest import Manifest, Trigger

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

context = lambda name: "builds.sr.ht" + (f": {name}" if name else "")

def source_url(repo, base, git_commit, source):
    if not source.endswith("/" + base.name):
        return source
    if base.name != repo.name:
        return base.name + "::" + repo.clone_url + "#" + git_commit.sha
    if repo.private:
        return repo.ssh_url + "#" + git_commit.sha
    return repo.clone_url + "#" + git_commit.sha

def update_preparing(base_commit):
    def go(name):
        try:
            base_commit.create_status("pending", _builds_sr_ht,
                    "preparing builds.sr.ht job", context=context(name))
        except GithubException:
            pass
    return go

def update_submitted(base_commit, username):
    def go(name, build_id):
        try:
            build_url = "{}/~{}/job/{}".format(
                    _builds_sr_ht, username, build_id)
            base_commit.create_status("pending", build_url,
                    "builds.sr.ht job is running", context=context(name))
        except GithubException:
            pass
    return go

def submit_github_build(hook, repo, commit, base=None,
        secrets=False, env=dict(), extras=dict()):
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
        files = [repo.get_contents(".build.yml", ref=git_commit.sha)]
    except GithubException:
        try:
            files = repo.get_dir_contents(
                    ".builds", ref=git_commit.sha) or []
            files = [repo.get_contents(
                f.path, ref=git_commit.sha) for f in files]
        except GithubException:
            files = []
    if not files:
        return "There are no build manifest in this repository"

    manifests = list()
    for f in files:
        name = f.name
        manifest = base64.b64decode(f.content)
        try:
            manifest = Manifest(yaml.safe_load(manifest))
        except Exception as ex:
            return f"There are errors in {name}:\n{str(ex)}", 400

        if manifest.sources:
            manifest.sources = [source_url(repo, base, git_commit, s)
                    for s in manifest.sources]
        if not manifest.environment:
            manifest.environment = env
        else:
            manifest.environment.update(env)

        notify_payload = {
            "full_name": base.full_name,
            "oauth_token": auth.oauth_token,
            "username": auth.user.username,
            "sha": commit.sha,
            "context": context(name),
        }
        if extras:
            notify_payload.update(extras)
        notify_url = encrypt_notify_url("github_complete_build", notify_payload)

        manifest.triggers.append(Trigger({
            "action": "webhook",
            "condition": "always",
            "url": notify_url,
        }))

        manifests.append((name, manifest))

    note = "{}\n\n[{}]({}) &mdash; [{}](mailto:{})".format(
            html.escape(first_line(git_commit.message)),
            str(git_commit.sha)[:7], commit.html_url,
            git_commit.author.name,
            git_commit.author.email)

    urls = submit_build(repo.name, manifests,
            hook.user.oauth_token, hook.user.username,
            note=note, secrets=secrets,
            preparing=update_preparing(base_commit),
            submitted=update_submitted(base_commit, auth.user.username))
    if isinstance(urls, str):
        return urls
    return "Submitted:\n\n" + "\n".join([f"{n}: {u}" for n, u in urls])

@csrf_bypass
@app.route("/github/complete_build/<payload>", methods=["POST"])
def github_complete_build(payload):
    payload = decrypt_notify_payload(payload)
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
