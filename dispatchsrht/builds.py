import base64
import json
import re
import requests
import yaml
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import url_for
from srht.api import get_authorization
from srht.config import cfg
from typing import Any, Callable, Dict, Iterable, Tuple

_root = cfg("dispatch.sr.ht", "origin")
_builds_sr_ht = cfg("builds.sr.ht", "origin", default=None)
_secret_key = cfg("sr.ht", "service-key",
        default=cfg("sr.ht", "secret-key", default=None))
_kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_secret_key.encode(),
        iterations=100000,
        backend=default_backend())
_key = base64.urlsafe_b64encode(_kdf.derive(_secret_key.encode()))
_fernet = Fernet(_key)

if _builds_sr_ht:
    from buildsrht.manifest import Manifest

def first_line(text):
    """Returns the first line of a string. Useful for commit messages."""
    if not "\n" in text:
        return text
    return text[:text.index("\n") + 1]

def encrypt_notify_url(route, payload):
    encpayload = _fernet.encrypt(
            json.dumps(payload).encode()).decode()
    return _root + url_for(route, payload=encpayload)

def decrypt_notify_payload(payload):
    return json.loads(_fernet.decrypt(payload.encode()).decode())

def submit_build(build_tag,
        manifests: Iterable[Tuple[str, Manifest]],
        user,
        note: str=None,
        secrets: bool=False,
        preparing: Callable[[str], Any]=None,
        submitted: Callable[[str, str], str]=None) -> str:
    """
    Submits a build, or builds, to builds.sr.ht. Returns a user-friendly
    summary of the builds submitted.

    @build_tag:      Build tags for this set of manifests, usually a repo name
    @manifests:      List of build manifests to submit and their names
    @user:           The dispatch.sr.ht user record submitting the build
    @note:           Note to add to build submission, e.g. commit message
    @secrets:        Whether to enable secrets for this build
    @preparing:      A callable called when each manifest is being prepared
                     Called with the manifest name.
    @submitted:      A callable called when each manifest has been submitted.
                     Called with the manifest name and the job URL. Should
                     return a brief statement for the summary string.
    """
    build_urls = []
    for name, manifest in manifests:
        if preparing:
            preparing(name)
        build_tag = [re.sub(r"[^a-z0-9_.-]", "", bt.lower()) for bt in build_tag]
        if name:
            name = re.sub(r"[^a-z0-9_.-]", "", name.lower())
        resp = requests.post(_builds_sr_ht + "/api/jobs", json={
            "manifest": yaml.dump(manifest.to_dict(), default_flow_style=False),
            "tags": build_tag + ([name] if name else []),
            "note": note,
            "secrets": secrets,
        }, headers=get_authorization(user))
        if resp.status_code != 200:
            return resp.text
        build_id = resp.json()["id"]
        build_url = "{}/~{}/job/{}".format(
                _builds_sr_ht, user.username, build_id)
        build_urls.append((name, build_url))
        if submitted:
            submitted(name, build_id)
    return build_urls
