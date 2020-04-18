import sqlalchemy as sa
import sqlalchemy_utils as sau
from dispatchsrht.tasks.gitlab.common import GitLabAuthorization
from dispatchsrht.tasks.gitlab.common import gitlabloginrequired
from dispatchsrht.tasks.gitlab.common import submit_gitlab_build
from dispatchsrht.tasks import TaskDef
from dispatchsrht.types import Task
from flask import Blueprint, redirect, render_template, request, url_for
from jinja2 import Markup
from srht.config import cfg, cfgb, cfgkeys
from srht.database import Base, db
from srht.flask import icon, csrf_bypass
from srht.oauth import current_user, loginrequired
from srht.validation import Validation
from uuid import UUID, uuid4

_root = cfg("dispatch.sr.ht", "origin")
_builds_sr_ht = cfg("builds.sr.ht", "origin", default=None)
_gitlab_enabled = cfgb("dispatch.sr.ht::gitlab", "enabled", default=False)

if _gitlab_enabled:
    from gitlab import Gitlab

class GitLabCommitToBuild(TaskDef):
    name = "gitlab_commit_to_build"
    enabled = bool(_gitlab_enabled and _builds_sr_ht)

    def description():
        return (icon("gitlab") + Markup(" GitLab commits ") +
            icon("caret-right") + Markup(" builds.sr.ht jobs"))

    class _GitLabCommitToBuildRecord(Base):
        __tablename__ = "gitlab_commit_to_build"
        id = sa.Column(sau.UUIDType, primary_key=True)
        created = sa.Column(sa.DateTime, nullable=False)
        updated = sa.Column(sa.DateTime, nullable=False)
        user_id = sa.Column(sa.Integer,
                sa.ForeignKey("user.id", ondelete="CASCADE"))
        user = sa.orm.relationship("User")
        task_id = sa.Column(sa.Integer,
                sa.ForeignKey("task.id", ondelete="CASCADE"))
        task = sa.orm.relationship("Task")
        repo_name = sa.Column(sa.Unicode, nullable=False)
        repo_id = sa.Column(sa.Integer, nullable=False)
        web_url = sa.Column(sa.Unicode, nullable=False)
        gitlab_webhook_id = sa.Column(sa.Integer, nullable=False)
        secrets = sa.Column(sa.Boolean, nullable=False, server_default='t')
        upstream = sa.Column(sa.Unicode, nullable=False)

    blueprint = Blueprint("gitlab_commit_to_build",
            __name__, template_folder="gitlab_commit_to_build")

    def edit_GET(task):
        record = GitLabCommitToBuild._GitLabCommitToBuildRecord.query.filter(
            GitLabCommitToBuild._GitLabCommitToBuildRecord.task_id == task.id
        ).one_or_none()
        if not record:
            abort(404)
        return render_template("gitlab/edit.html", task=task, record=record)

    def edit_POST(task):
        record = GitLabCommitToBuild._GitLabCommitToBuildRecord.query.filter(
            GitLabCommitToBuild._GitLabCommitToBuildRecord.task_id == task.id
        ).one_or_none()
        valid = Validation(request)
        secrets = valid.optional("secrets", cls=bool, default=False)
        record.secrets = bool(secrets)
        db.session.commit()
        return redirect(url_for("html.edit_task", task_id=task.id))

    @blueprint.route("/configure")
    @loginrequired
    def configure():
        canonical_upstream = cfg("dispatch.sr.ht::gitlab", "canonical-upstream")
        upstreams = [k for k in cfgkeys("dispatch.sr.ht::gitlab") if k not in [
            "enabled", "canonical-upstream", canonical_upstream,
        ]]
        return render_template("gitlab/select-instance.html",
                canonical_upstream=canonical_upstream, upstreams=upstreams,
                instance_name=lambda inst: cfg("dispatch.sr.ht::gitlab",
                    inst).split(":")[0])

    @blueprint.route("/configure/<upstream>")
    @gitlabloginrequired
    def configure_repo_GET(gitlab, upstream):
        repos = gitlab.projects.list(owned=True)
        repos = sorted(repos, key=lambda r: r.attributes["name_with_namespace"])
        existing = GitLabCommitToBuild._GitLabCommitToBuildRecord.query.filter(
                GitLabCommitToBuild._GitLabCommitToBuildRecord.user_id == current_user.id,
                GitLabCommitToBuild._GitLabCommitToBuildRecord.upstream == upstream).all()
        existing = [e.repo_id for e in existing]
        return render_template("gitlab/select-repo.html",
                repos=repos, existing=existing)

    @blueprint.route("/configure/<upstream>", methods=["POST"])
    @gitlabloginrequired
    def configure_repo_POST(gitlab, upstream):
        valid = Validation(request)
        repo_id = valid.require("repo_id")
        if not valid.ok:
            return "quit yo hackin bullshit"
        project = gitlab.projects.get(int(repo_id))
        if not project:
            return "quit yo hackin bullshit"

        task = Task()
        task.name = "{}::gitlab_commit_to_build".format(
                project.attributes["name_with_namespace"])
        task.user_id = current_user.id
        task._taskdef = "gitlab_commit_to_build"
        db.session.add(task)
        db.session.flush()

        record = GitLabCommitToBuild._GitLabCommitToBuildRecord()
        record.id = uuid4()
        record.user_id = current_user.id
        record.task_id = task.id
        record.gitlab_webhook_id = -1
        record.repo_name = project.attributes['name_with_namespace']
        record.repo_id = project.id
        record.web_url = project.attributes['web_url']
        record.upstream = upstream
        db.session.add(record)
        db.session.flush()

        hook = project.hooks.create({
            "url": _root + url_for("gitlab_commit_to_build._webhook",
                record_id=record.id),
            "push_events": 1,
        })
        record.gitlab_webhook_id = hook.id
        db.session.commit()

        return redirect(url_for("html.edit_task", task_id=task.id))

    @csrf_bypass
    @blueprint.route("/webhook/<record_id>", methods=["POST"])
    def _webhook(record_id):
        record_id = UUID(record_id)
        hook = GitLabCommitToBuild._GitLabCommitToBuildRecord.query.filter(
                GitLabCommitToBuild._GitLabCommitToBuildRecord.id == record_id
            ).one_or_none()
        if not hook:
            return "Unknown hook " + str(record_id), 404
        auth = GitLabAuthorization.query.filter(
                GitLabAuthorization.user_id == hook.user_id,
                GitLabAuthorization.upstream == hook.upstream,
            ).first()
        if not auth:
            return "Invalid authorization for this hook"
        gitlab = Gitlab(f"https://{hook.upstream}",
                oauth_token=auth.oauth_token)

        valid = Validation(request)
        commit = valid.require("after")
        ref = valid.require("ref")
        if not valid.ok:
            return "Unexpected hook payload"

        try:
            project = gitlab.projects.get(hook.repo_id)
            commit = project.commits.get(commit)
        except:
            return "Unable to fetch commit information"

        urls = submit_gitlab_build(auth, hook, project, commit, env={
            "GITLAB_REF": ref,
        })
        if isinstance(urls, str):
            return urls
        return "Submitted:\n\n" + "\n".join([f"{n}: {u}" for n, u in urls])
