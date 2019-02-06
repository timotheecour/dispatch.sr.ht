from srht.flask import SrhtFlask
from srht.config import cfg
from srht.database import DbSession
from srht.oauth import AbstractOAuthService
from dispatchsrht.types import User

db = DbSession(cfg("dispatch.sr.ht", "connection-string"))
db.init()

client_id = cfg("dispatch.sr.ht", "oauth-client-id")
client_secret = cfg("dispatch.sr.ht", "oauth-client-secret")
buildssrht = cfg("builds.sr.ht", "oauth-client-id")

class DispatchOAuthService(AbstractOAuthService):
    def __init__(self):
        super().__init__(client_id, client_secret,
            required_scopes=["profile", "keys"] + [
                buildssrht + "/jobs:write"
            ] if buildssrht else [],
            user_class=User)

class DispatchApp(SrhtFlask):
    def __init__(self):
        super().__init__("dispatch.sr.ht", __name__,
                oauth_service=DispatchOAuthService())

        from dispatchsrht.blueprints.html import html
        self.register_blueprint(html)

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

app = DispatchApp()
app.register_tasks()
