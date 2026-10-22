"""Each signed-in user's own storage for the site's apps: /apps/<app>/api/, behind the site sign-in.

An app of the site file with `storage = true` (portal/site.py) keeps JSON values here under names
of its choosing, per user, so what someone saves follows their account rather than a browser. The
app's static files are nginx's; only this API is served from here.

    GET    /apps/<app>/api/me            {"uid": ...}
    GET    /apps/<app>/api/store         {"keys": [{"key", "updated", "size"}, ...]}
    GET    /apps/<app>/api/store/<key>   the value (404 if none)
    PUT    /apps/<app>/api/store/<key>   the value (a JSON body); 204
    DELETE /apps/<app>/api/store/<key>   204

nginx mints the token for the app's own audience (its id), and the token must name the app in the
path: a token for one app does not open another app's data. A write must say `Content-Type:
application/json`, which a cross-site form cannot send and a cross-site script cannot send without a
CORS preflight this service never answers.
"""
import json
import os
import re
import sqlite3
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import tokens
from .config import Settings
from .security import SecurityHeadersMiddleware

KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS store (
    app     TEXT NOT NULL,
    uid     TEXT NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    updated REAL NOT NULL,
    PRIMARY KEY (app, uid, key)
);
"""


class Store:
    def __init__(self, path: str, max_keys: int = 200):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.max_keys = max_keys
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.executescript(SCHEMA)
        if path != ":memory:":
            os.chmod(path, 0o600)

    def keys(self, app: str, uid: str) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT key, updated, length(value) FROM store WHERE app=? AND uid=? ORDER BY key",
                                   (app, uid)).fetchall()
        return [{"key": k, "updated": u, "size": n} for k, u, n in rows]

    def get(self, app: str, uid: str, key: str) -> str | None:
        with self._lock:
            row = self.db.execute("SELECT value FROM store WHERE app=? AND uid=? AND key=?", (app, uid, key)).fetchone()
        return row[0] if row else None

    def put(self, app: str, uid: str, key: str, value: str) -> bool:
        """False when the user already has max_keys other keys in this app."""
        with self._lock:
            exists = self.db.execute("SELECT 1 FROM store WHERE app=? AND uid=? AND key=?", (app, uid, key)).fetchone()
            if not exists:
                n = self.db.execute("SELECT count(*) FROM store WHERE app=? AND uid=?", (app, uid)).fetchone()[0]
                if n >= self.max_keys:
                    return False
            self.db.execute("INSERT OR REPLACE INTO store VALUES (?,?,?,?,?)", (app, uid, key, value, time.time()))
        return True

    def delete(self, app: str, uid: str, key: str) -> None:
        with self._lock:
            self.db.execute("DELETE FROM store WHERE app=? AND uid=? AND key=?", (app, uid, key))


def create_app(settings: Settings | None = None, store: Store | None = None, public_key=None) -> FastAPI:
    s = settings or Settings()
    apps = {a.id for a in s.site().apps if a.storage}  # read at start: a bad site file stops the service
    public_key = public_key or tokens.load_public_key(s.sso_public_key_file)
    store = store or Store(s.apps_db, s.apps_max_keys)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeadersMiddleware)

    def err(status: int, message: str) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    def who(request: Request, name: str) -> str | None:
        """The uid, if the token was minted for this very app."""
        token = request.headers.get("x-auth-token", "")
        try:
            return tokens.verify(public_key, token, s.sso_issuer, name) if token else None
        except tokens.TokenError:
            return None

    def gate(request: Request, name: str, key: str | None = None) -> tuple[str | None, JSONResponse | None]:
        if name not in apps:
            return None, err(404, "no such app")
        uid = who(request, name)
        if uid is None:
            return None, err(401, "sign in first")
        if key is not None and not KEY.match(key):
            return None, err(400, "a key is lowercase letters, digits, _ . - (up to 64)")
        return uid, None

    @app.get("/apps/{name}/api/me")
    async def me(request: Request, name: str):
        uid, bad = gate(request, name)
        return bad or {"uid": uid}

    @app.get("/apps/{name}/api/store")
    async def list_keys(request: Request, name: str):
        uid, bad = gate(request, name)
        return bad or {"keys": store.keys(name, uid)}

    @app.get("/apps/{name}/api/store/{key}")
    async def get(request: Request, name: str, key: str):
        uid, bad = gate(request, name, key)
        if bad:
            return bad
        value = store.get(name, uid, key)
        if value is None:
            return err(404, "no such key")
        return Response(value, media_type="application/json")

    @app.put("/apps/{name}/api/store/{key}")
    async def put(request: Request, name: str, key: str):
        uid, bad = gate(request, name, key)
        if bad:
            return bad
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return err(415, "send application/json")
        body = await request.body()
        if len(body) > s.apps_max_value:
            return err(413, f"a value is at most {s.apps_max_value} bytes")
        try:
            value = json.dumps(json.loads(body), ensure_ascii=False, separators=(",", ":"))
        except (ValueError, UnicodeDecodeError):
            return err(400, "the body is not JSON")
        if not store.put(name, uid, key, value):
            return err(409, f"at most {s.apps_max_keys} keys per app")
        return Response(status_code=204)

    @app.delete("/apps/{name}/api/store/{key}")
    async def delete(request: Request, name: str, key: str):
        uid, bad = gate(request, name, key)
        if bad:
            return bad
        store.delete(name, uid, key)
        return Response(status_code=204)

    @app.get("/apps/healthz")
    async def healthz():
        return Response("ok", media_type="text/plain")

    return app
