import sqlalchemy as sa
import sqlalchemy_utils as sau
from github import Github
from flask import Blueprint, redirect, request, render_template, url_for, abort
from flask_login import current_user
from jinja2 import Markup
from uuid import UUID, uuid4
from srht.database import Base, db
from srht.config import cfg
from srht.flask import icon
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

    blueprint = Blueprint("github_commit_to_build",
            __name__, template_folder="github_commit_to_build")

    @blueprint.route("/webhook/<record_id>", methods=["POST"])
    def _webhook(record_id):
        record_id = UUID(record_id)
        hook = GitHubCommitToBuild._GitHubCommitToBuildRecord.query.filter(
                GitHubCommitToBuild._GitHubCommitToBuildRecord.id == record_id
            ).first()
        if not hook:
            return "Unknown hook " + str(record_id), 404
        valid = Validation(request)
        commit = valid.require("head_commit")
        repo = valid.require("repository")
        if not valid.ok:
            return "Got request, but it has no commits"
        return submit_build(hook, repo, commit)

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
        # TODO: redirect to task page
        return redirect("/")
