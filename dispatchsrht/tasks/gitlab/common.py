import html
import json
import requests
import sqlalchemy as sa
import yaml
from dispatchsrht.app import app
from dispatchsrht.builds import encrypt_notify_url, first_line, submit_build
from dispatchsrht.builds import decrypt_notify_payload
from flask import abort, redirect, render_template, request, url_for
from flask_login import current_user
from functools import wraps
from srht.config import cfg, cfgb
from srht.database import Base, db
from srht.flask import csrf_bypass, loginrequired
from urllib.parse import urlencode

_root = cfg("dispatch.sr.ht", "origin")
_builds_sr_ht = cfg("builds.sr.ht", "origin", default=None)
_gitlab_enabled = cfgb("dispatch.sr.ht::gitlab", "enabled", default=False)

if _builds_sr_ht:
    from buildsrht.manifest import Manifest, Trigger

if _gitlab_enabled:
    from gitlab import Gitlab
    from gitlab.exceptions import GitlabError

class GitLabAuthorization(Base):
    __tablename__ = "gitlab_authorization"
    id = sa.Column(sa.Integer, primary_key=True)
    created = sa.Column(sa.DateTime, nullable=False)
    updated = sa.Column(sa.DateTime, nullable=False)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("user.id"))
    user = sa.orm.relationship("User")
    upstream = sa.Column(sa.Unicode, nullable=False)
    oauth_token = sa.Column(sa.Unicode(512), nullable=False)

def gitlab_redirect(upstream, return_to):
    gl_authorize_url = f"https://{upstream}/oauth/authorize"
    gl_client = cfg("dispatch.sr.ht::gitlab", upstream, default=None)
    if not gl_client:
        return redirect(url_for("gitlab_no_instance"))
    [instance_name, client_id, secret] = gl_client.split(":")
    parameters = {
        "client_id": client_id,
        "scope": "api",
        "state": return_to,
        "response_type": "code",
        "redirect_uri": _root + url_for("gitlab_callback", upstream=upstream),
    }
    return redirect("{}?{}".format(gl_authorize_url, urlencode(parameters)))

def gitlabloginrequired(f):
    @wraps(f)
    def wrapper(upstream, *args, **kwargs):
        auth = GitLabAuthorization.query.filter(
                GitLabAuthorization.user_id == current_user.id,
                GitLabAuthorization.upstream == upstream,
            ).first()
        if not auth:
            return gitlab_redirect(upstream, request.path)
        try:
            gitlab = Gitlab(f"https://{upstream}", oauth_token=auth.oauth_token)
            return f(gitlab, upstream, *args, **kwargs)
        except GitlabError:
            db.session.delete(auth)
            db.session.commit()
            return gitlab_redirect(upstream, request.path)
    return loginrequired(wrapper)

@app.route("/gitlab/no-instance")
def gitlab_no_instance():
    return render_template("gitlab/no-instance.html")

@app.route("/gitlab/callback/<upstream>")
@loginrequired
def gitlab_callback(upstream):
    code = request.args.get("code")
    state = request.args.get("state")
    gl_client = cfg("dispatch.sr.ht::gitlab", upstream, default=None)
    if not gl_client:
        abort(400)
    [instance_name, client_id, secret] = gl_client.split(":")

    resp = requests.post(
        f"https://{upstream}/oauth/token", headers={
            "Accept": "application/json"
        }, data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": secret,
            "code": code,
            "redirect_uri": _root + url_for("gitlab_callback", upstream=upstream),
        })
    if resp.status_code != 200:
        # TODO: Proper error page
        print(resp.text)
        return "An error occured"
    json = resp.json()
    access_token = json.get("access_token")
    auth = GitLabAuthorization()
    auth.user_id = current_user.id
    auth.oauth_token = access_token
    auth.upstream = upstream
    db.session.add(auth)
    db.session.commit()
    return redirect(state)

def source_url(project, commit, url, source):
    if not url.endswith("/" + project.attributes["name"]):
        return url
    if source.attributes['name'] != project.attributes['name']:
        return (project.name + "::"
                + source.attributes['http_url_to_repo']
                + "#" + commit.sha)
    if project.attributes['visibility'] == 'private':
        return project.attributes['ssh_url_to_repo'] + "#" + commit.get_id()
    return project.attributes['http_url_to_repo'] + "#" + commit.get_id()

context = lambda name: "builds.sr.ht" + (f": {name}" if name else "")

def update_preparing(commit):
    def go(name):
        try:
            status = commit.statuses.create({
                "state": "pending",
                "context": context(name),
                "target_url": _builds_sr_ht,
            })
        except GitlabError:
            pass
    return go

def update_submitted(commit, username):
    def go(name, build_id):
        build_url = "{}/~{}/job/{}".format(
                _builds_sr_ht, username, build_id)
        try:
            status = commit.statuses.create({
                "state": "running",
                "context": context(name),
                "target_url": build_url,
            })
            return build_url
        except GitlabError:
            return ""
    return go

def submit_gitlab_build(auth, hook, project, commit,
        source=None, env=dict(), is_mr=False):
    if source is None:
        source = project
    try:
        files = [source.files.get(file_path=".build.yml",
            ref=commit.get_id())]
    except GitlabError:
        try:
            tree = source.repository_tree(
                    path=".builds", ref=commit.get_id())
            files = [source.files.get(file_path=e['path'],
                        ref=commit.get_id())
                    for e in tree if e['path'].endswith(".yml")]
        except GitlabError:
            return "There are no build manifests in this repository."

    env.update({
        "GITLAB_REPOSITORY": hook.repo_name,
        "GITLAB_EVENT": request.headers.get('X-Gitlab-Event'),
    })

    manifests = list()
    for f in files:
        name = f.attributes["file_name"]
        manifest = f.decode()
        try:
            manifest = Manifest(yaml.safe_load(manifest))
        except Exception as ex:
            return f"There are errors in {name}:\n{str(ex)}", 400

        if manifest.sources:
            manifest.sources = [source_url(project, commit, url, source)
                    for url in manifest.sources]
        if not manifest.environment:
            manifest.environment = env
        else:
            manifest.environment.update(env)

        notify_payload = {
            "context": context(name),
            "oauth_token": auth.oauth_token,
            "project_id": project.get_id(),
            "sha": commit.get_id(),
            "upstream": hook.upstream,
            "username": auth.user.username,
        }

        notify_url = encrypt_notify_url(
                "gitlab_complete_build", notify_payload)

        manifest.triggers.append(Trigger({
            "action": "webhook",
            "condition": "always",
            "url": notify_url,
        }))

        manifests.append((name, manifest))

    note = "{}\n\n[{}]({}) &mdash; [{}](mailto:{})".format(
            html.escape(first_line(commit.attributes["message"])),
            str(commit.get_id())[:7], "{}/commit/{}".format(
                project.attributes["web_url"], commit.get_id()),
            commit.attributes["committer_name"],
            commit.attributes["committer_email"])

    return submit_build(project.attributes['name'], manifests,
            hook.user.oauth_token, hook.user.username,
            note=note, secrets=hook.secrets,
            preparing=update_preparing(commit),
            submitted=update_submitted(commit, auth.user.username))

@csrf_bypass
@app.route("/gitlab/complete_build/<payload>", methods=["POST"])
def gitlab_complete_build(payload):
    result = json.loads(request.data.decode('utf-8'))
    build_id = result["id"]
    status = result["status"]

    payload = decrypt_notify_payload(payload)
    context = payload["context"]
    oauth_token = payload["oauth_token"]
    project_id = payload["project_id"]
    sha = payload["sha"]
    upstream = payload["upstream"]
    username = payload["username"]

    gitlab = Gitlab(f"https://{upstream}", oauth_token=oauth_token)
    project = gitlab.projects.get(project_id)
    commit = project.commits.get(sha)

    build_url = "{}/~{}/job/{}".format(
            _builds_sr_ht, username, build_id)

    status = commit.statuses.create({
        "state": "success" if status == "success" else "failed",
        "context": context,
        "target_url": build_url,
        "description": "completed successfully" if status == "success" else "failed",
    })

    return f"Sent build status to {upstream}"
