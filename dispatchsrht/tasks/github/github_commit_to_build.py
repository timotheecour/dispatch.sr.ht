import sqlalchemy as sa
import sqlalchemy_utils as sau
from dispatchsrht.tasks import TaskDef
from dispatchsrht.tasks.github.common import GitHubAuthorization
from dispatchsrht.tasks.github.common import githubloginrequired
from dispatchsrht.tasks.github.common import submit_github_build
from dispatchsrht.types import Task
from flask import Blueprint, redirect, request, render_template, url_for, abort
from flask_login import current_user
from github import Github
from jinja2 import Markup
from srht.config import cfg
from srht.database import Base, db
from srht.flask import icon, csrf_bypass
from srht.validation import Validation
from uuid import UUID, uuid4

_root = cfg("dispatch.sr.ht", "origin")
_builds_sr_ht = cfg("builds.sr.ht", "origin", default=None)
_github_client_id = cfg("dispatch.sr.ht::github",
        "oauth-client-id", default=None)
_github_client_secret = cfg("dispatch.sr.ht::github",
        "oauth-client-secret", default=None)

class GitHubCommitToBuild(TaskDef):
    name = "github_commit_to_build"
    enabled = bool(_github_client_id
            and _github_client_secret
            and _builds_sr_ht)

    def description():
        return (icon("github") + Markup(" GitHub commits ") +
            icon("caret-right") + Markup(" builds.sr.ht jobs"))

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
        secrets = sa.Column(sa.Boolean, nullable=False, server_default='t')

    blueprint = Blueprint("github_commit_to_build",
            __name__, template_folder="github_commit_to_build")

    def edit_GET(task):
        record = GitHubCommitToBuild._GitHubCommitToBuildRecord.query.filter(
            GitHubCommitToBuild._GitHubCommitToBuildRecord.task_id == task.id
        ).one_or_none()
        if not record:
            abort(404)
        return render_template("github/edit.html", task=task, record=record)

    def edit_POST(task):
        record = GitHubCommitToBuild._GitHubCommitToBuildRecord.query.filter(
            GitHubCommitToBuild._GitHubCommitToBuildRecord.task_id == task.id
        ).one_or_none()
        valid = Validation(request)
        secrets = valid.optional("secrets", cls=bool, default=False)
        record.secrets = bool(secrets)
        db.session.commit()
        return redirect(url_for("html.edit_task", task_id=task.id))

    @csrf_bypass
    @blueprint.route("/webhook/<record_id>", methods=["POST"])
    def _webhook(record_id):
        record_id = UUID(record_id)
        hook = GitHubCommitToBuild._GitHubCommitToBuildRecord.query.filter(
                GitHubCommitToBuild._GitHubCommitToBuildRecord.id == record_id
            ).one_or_none()
        if not hook:
            return "Unknown hook " + str(record_id), 404
        valid = Validation(request)
        commit = valid.require("head_commit")
        repo = valid.require("repository")
        ref = valid.require("ref")
        if not valid.ok:
            return "Got request, but it has no commits"
        return submit_github_build(hook, repo, commit, env={
            "GITHUB_DELIVERY": request.headers.get("X-GitHub-Delivery"),
            "GITHUB_EVENT": request.headers.get("X-GitHub-Event"),
            "GITHUB_REF": ref,
            "GITHUB_REPO": repo["full_name"],
        }, secrets=hook.secrets)

    @blueprint.route("/configure")
    @githubloginrequired
    def configure(github):
        repos = github.get_user().get_repos(sort="updated")
        repos = filter(lambda r: r.permissions.admin and not r.fork, repos)
        existing = GitHubCommitToBuild._GitHubCommitToBuildRecord.query.filter(
                GitHubCommitToBuild._GitHubCommitToBuildRecord.user_id ==
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
        task.name = "{}::github_commit_to_build".format(repo.full_name)
        task.user_id = current_user.id
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
        return redirect(url_for("html.edit_task", task_id=task.id))
