import sqlalchemy as sa
import sqlalchemy_utils as sau
from github import Github
from flask import Blueprint, redirect, request, render_template, url_for, abort
from flask import session
from flask_login import current_user
from jinja2 import Markup
from uuid import UUID, uuid4
from srht.database import Base, db
from srht.config import cfg
from srht.flask import icon, csrf_bypass
from srht.validation import Validation
from dispatchsrht.tasks import TaskDef
from dispatchsrht.tasks.github.auth import GitHubAuthorization
from dispatchsrht.tasks.github.auth import githubloginrequired
from dispatchsrht.tasks.github.auth import submit_build
from dispatchsrht.types import Task

_root = cfg("dispatch.sr.ht", "origin")
_builds_sr_ht = cfg("builds.sr.ht", "origin", default=None)
_github_client_id = cfg("dispatch.sr.ht::github",
        "oauth-client-id", default=None)
_github_client_secret = cfg("dispatch.sr.ht::github",
        "oauth-client-secret", default=None)

class GitHubPRToBuild(TaskDef):
    name = "github_pr_to_build"
    enabled = bool(_github_client_id
            and _github_client_secret
            and _builds_sr_ht)

    def description():
        return (icon("github") + Markup(" GitHub pull requests ") +
            icon("caret-right") + Markup(" builds.sr.ht jobs"))

    class _GitHubPRToBuildRecord(Base):
        __tablename__ = "github_pr_to_build"
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
        automerge = sa.Column(sa.Boolean, nullable=False, server_default='f')
        private = sa.Column(sa.Boolean, nullable=False, server_default='f')
        secrets = sa.Column(sa.Boolean, nullable=False, server_default='f')

    blueprint = Blueprint("github_pr_to_build",
            __name__, template_folder="github_pr_to_build")

    def edit_GET(task):
        record = GitHubPRToBuild._GitHubPRToBuildRecord.query.filter(
            GitHubPRToBuild._GitHubPRToBuildRecord.task_id == task.id
        ).one_or_none()
        if not record:
            abort(404)
        auth = GitHubAuthorization.query.filter(
            GitHubAuthorization.user_id == current_user.id
        ).first()
        github = Github(auth.oauth_token)
        repo = github.get_repo(record.repo)
        if repo.private != record.private:
            record.private = repo.private
            if not repo.private:
                record.secrets = False
            db.session.commit()
        saved = session.pop("saved", False)
        return render_template("github/edit.html",
                task=task, record=record, saved=saved)

    def edit_POST(task):
        record = GitHubPRToBuild._GitHubPRToBuildRecord.query.filter(
            GitHubPRToBuild._GitHubPRToBuildRecord.task_id == task.id
        ).one_or_none()
        valid = Validation(request)
        automerge = valid.optional("automerge", cls=bool, default=False)
        secrets = valid.optional("secrets", cls=bool, default=False)
        record.automerge = bool(automerge)
        record.secrets = bool(secrets)
        if not record.private:
            record.secrets = False
        db.session.commit()
        session["saved"] = True
        return redirect(url_for("html.edit_task", task_id=task.id))

    @csrf_bypass
    @blueprint.route("/webhook/<record_id>", methods=["POST"])
    def _webhook(record_id):
        record_id = UUID(record_id)
        hook = GitHubPRToBuild._GitHubPRToBuildRecord.query.filter(
                GitHubPRToBuild._GitHubPRToBuildRecord.id == record_id
            ).first()
        if not hook:
            return "Unknown hook " + str(record_id), 404
        valid = Validation(request)
        pr = valid.require("pull_request")
        action = valid.require("action")
        if not valid.ok:
            return "Got request, but it has no commits"
        if action not in ["opened", "synchronize"]:
            return "Got update, but there are no new commits"
        head = pr["head"]
        base = pr["base"]
        base_repo = base["repo"]
        head_repo = head["repo"]
        auth = GitHubAuthorization.query.filter(
            GitHubAuthorization.user_id == hook.user_id).first()
        if not auth:
            return (
                "You have not authorized us to access your GitHub account", 401
            )
        secrets = hook.secrets
        if not base_repo["private"]:
            secrets = False
        return submit_build(hook, head_repo, head, base_repo,
                secrets=secrets, extras={
                    "automerge": hook.automerge, 
                    "pr": pr["number"]
                }, env={
                    "GITHUB_DELIVERY": request.headers.get("X-GitHub-Delivery"),
                    "GITHUB_EVENT": request.headers.get("X-GitHub-Event"),
                    "GITHUB_PR_NUMBER": str(pr["number"]),
                    "GITHUB_PR_TITLE": pr["title"],
                    "GITHUB_BASE_REPO": base_repo["full_name"],
                    "GITHUB_HEAD_REPO": head_repo["full_name"],
                })

    @blueprint.route("/configure")
    @githubloginrequired
    def configure(github):
        repos = github.get_user().get_repos(sort="updated")
        repos = filter(lambda r: r.permissions.admin and not r.fork, repos)
        existing = GitHubPRToBuild._GitHubPRToBuildRecord.query.filter(
                GitHubPRToBuild._GitHubPRToBuildRecord.user_id ==
                current_user.id).all()
        existing = [e.repo for e in existing]
        return render_template("github/select-repo.html",
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
        task.name = "{}::github_pr_to_build".format(repo.full_name)
        task.user_id = current_user.id
        task._taskdef = "github_pr_to_build"
        db.session.add(task)
        db.session.flush()
        record = GitHubPRToBuild._GitHubPRToBuildRecord()
        record.id = uuid4()
        record.user_id = current_user.id
        record.task_id = task.id
        record.github_webhook_id = -1
        record.repo = repo.full_name
        record.private = repo.private
        db.session.add(record)
        db.session.flush()
        hook = repo.create_hook("web", {
            "url": _root + url_for("github_pr_to_build._webhook",
                record_id=record.id),
            "content_type": "json",
        }, ["pull_request"], active=True)
        record.github_webhook_id = hook.id
        db.session.commit()
        return redirect(url_for("html.edit_task", task_id=task.id))
