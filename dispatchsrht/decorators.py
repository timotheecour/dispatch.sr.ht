from flask import redirect, request, abort
from flask_login import current_user
from functools import wraps
from dispatchsrht.app import oauth_url

import urllib

def loginrequired(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user:
            return redirect(oauth_url(request.url))
        else:
            return f(*args, **kwargs)
    return wrapper
