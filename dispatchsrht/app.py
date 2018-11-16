from srht.flask import SrhtFlask
from srht.config import cfg
from srht.database import DbSession

db = DbSession(cfg("dispatch.sr.ht", "connection-string"))

from dispatchsrht.types import User

db.init()

class DispatchApp(SrhtFlask):
    def __init__(self):
        super().__init__("dispatch.sr.ht", __name__)

        from dispatchsrht.blueprints.html import html
        self.register_blueprint(html)

        meta_client_id = cfg("dispatch.sr.ht", "oauth-client-id")
        meta_client_secret = cfg("dispatch.sr.ht", "oauth-client-secret")
        builds_sr_ht = cfg("builds.sr.ht", "oauth-client-id")
        self.configure_meta_auth(meta_client_id, meta_client_secret,
                base_scopes=["profile", "keys"] + [
                    builds_sr_ht + "/jobs:write"
                ] if builds_sr_ht else [])

        # TODO: make this better
        self.no_csrf_prefixes += ['/github/complete_build']

        @self.login_manager.user_loader
        def user_loader(username):
            # TODO: Switch to a session token
            return User.query.filter(User.username == username).one_or_none()

        @self.context_processor
        def inject():
            from dispatchsrht.tasks import taskdefs
            return { "taskdefs": taskdefs }

    def register_tasks(self):
        # This is done in a separate step because we can't import these right
        # away due to a circular dependency on the app variable
        from dispatchsrht.tasks import taskdefs
        for taskdef in taskdefs():
            self.register_blueprint(taskdef.blueprint,
                    url_prefix="/" + taskdef.name)

    def lookup_or_register(self, exchange, profile, scopes):
        user = User.query.filter(User.username == profile["username"]).first()
        if not user:
            user = User()
            db.session.add(user)
        user.username = profile.get("username")
        user.email = profile.get("email")
        user.oauth_token = exchange["token"]
        user.oauth_token_expires = exchange["expires"]
        user.oauth_token_scopes = scopes
        db.session.commit()
        return user

app = DispatchApp()
app.register_tasks()
