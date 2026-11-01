"""Vaults: a person's markdown directories — the ones Obsidian opens — read and written in the browser,
behind the site sign-in (docs/vault.md).

    GET    /vault/api/v1/vaults                         {vaults: [...], roots: [...]} — theirs, and where they may add one
    POST   /vault/api/v1/vaults   {path, name}          register a directory of their storage
    DELETE /vault/api/v1/vaults/<id>                    forget it (the files stay)
    GET    /vault/api/v1/vaults/<id>/tree               folders and notes (dotted folders hidden)
    GET    /vault/api/v1/vaults/<id>/file?path=         {path, text, sha256, mtime, size}
    PUT    /vault/api/v1/vaults/<id>/file?path=         {text}, If-Match: <sha256> (412 on a change meanwhile)
    GET    /vault/api/v1/vaults/<id>/raw?path=          an attachment (an image a note shows)
    POST   /vault/api/v1/vaults/<id>/move {from, to}
    DELETE /vault/api/v1/vaults/<id>/file?path=         to .trash/
    GET    /vault/api/v1/vaults/<id>/search?q=          full text (FTS5), with snippets
    GET    /vault/api/v1/vaults/<id>/links?path=        {links, backlinks}
    GET    /vault/api/v1/vaults/<id>/recent?n=          the notes last changed

The service runs as its own user and cannot see a person's files: root stages each registered
directory, idmapped, under PORTAL_VAULT_STAGE (<name>-vault-mounts, the same reconciler as the
handbook's sandbox mounts: refhandbook/agents/mounts.py with --picks vault). Without a stage (a
local run, the tests) the real path is used. A registered path must lie under an offered root
(PORTAL_VAULT_ROOTS, the syntax of RHB_SANDBOX_MOUNTS). The index (search, links) is the service's
own SQLite per vault, refreshed from the files' mtimes when asked.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from refhandbook.agents import mounts

from . import tokens
from .config import Settings
from .i18n import t
from .security import SecurityHeadersMiddleware

AUDIENCE = "vault"
PREFIX = "/vault/api/v1"
TEXT = {".md", ".txt", ".json", ".canvas", ".csv"}
NOTE = ".md"
HIDDEN = (".obsidian", ".git", ".trash")
TRASH = ".trash"
MAX_TEXT = 4 << 20  # bytes of one note
MAX_RAW = 64 << 20
MAX_ENTRIES = 20000  # of one tree
REFRESH_EVERY = 2.0  # seconds between two walks of the same vault
WIKILINK = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]")
TAG = re.compile(r"(?<![\w/])#([\w][\w/-]*)")
SEGMENT = re.compile(r"^[^/\0]{1,255}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS vaults (
    id      TEXT PRIMARY KEY,
    uid     TEXT NOT NULL,
    name    TEXT NOT NULL,
    path    TEXT NOT NULL,
    created REAL NOT NULL,
    UNIQUE (uid, path)
);
"""
INDEX = """
CREATE TABLE IF NOT EXISTS notes (path TEXT PRIMARY KEY, title TEXT NOT NULL, mtime REAL NOT NULL, size INTEGER NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(path UNINDEXED, title, body, tokenize = 'unicode61');
CREATE TABLE IF NOT EXISTS links (src TEXT NOT NULL, dst TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS links_dst ON links(dst);
CREATE INDEX IF NOT EXISTS links_src ON links(src);
CREATE TABLE IF NOT EXISTS tags (path TEXT NOT NULL, tag TEXT NOT NULL);
"""


class VaultError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class VaultRecord:
    id: str
    uid: str
    name: str
    path: str
    created: float


class Registry:
    """Who registered which directory as a vault (PORTAL_VAULT_DB)."""

    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.executescript(SCHEMA)
        if path != ":memory:":
            os.chmod(path, 0o600)

    def _rec(self, row: tuple) -> VaultRecord:
        return VaultRecord(*row)

    def of(self, uid: str) -> list[VaultRecord]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM vaults WHERE uid=? ORDER BY created", (uid,)).fetchall()
        return [self._rec(r) for r in rows]

    def get(self, uid: str, vid: str) -> VaultRecord | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM vaults WHERE uid=? AND id=?", (uid, vid)).fetchone()
        return self._rec(row) if row else None

    def add(self, uid: str, name: str, path: str) -> VaultRecord:
        vid = uuid.uuid4().hex[:10]
        with self._lock:
            try:
                self.db.execute("INSERT INTO vaults VALUES (?,?,?,?,?)", (vid, uid, name, path, time.time()))
            except sqlite3.IntegrityError as e:
                raise VaultError(409, t("이미 등록한 경로입니다.")) from e
            return self._rec(self.db.execute("SELECT * FROM vaults WHERE id=?", (vid,)).fetchone())

    def remove(self, uid: str, vid: str) -> bool:
        with self._lock:
            return self.db.execute("DELETE FROM vaults WHERE uid=? AND id=?", (uid, vid)).rowcount > 0


# ── paths ─────────────────────────────────────────────────────────────────


def clean(rel: str) -> str:
    """A path inside a vault, as kept: forward slashes, no empty or dot segments, nothing hidden."""
    rel = (rel or "").replace("\\", "/").strip().strip("/")
    if not rel:
        raise VaultError(400, t("경로를 주세요."))
    parts = [x for x in rel.split("/") if x]  # a doubled slash is nothing
    for p in parts:
        if p.startswith("."):  # . and .. included: nothing hidden, nothing above
            raise VaultError(400, t("점으로 시작하는 이름은 쓰지 않습니다: {name}", name=p))
        if not SEGMENT.match(p):
            raise VaultError(400, t("경로를 읽을 수 없습니다: {path}", path=rel))
    return "/".join(parts)


def is_text(rel: str) -> bool:
    return Path(rel).suffix.lower() in TEXT


def is_note(rel: str) -> bool:
    return rel.lower().endswith(NOTE)


def note_name(rel: str) -> str:
    return rel[:-len(NOTE)] if is_note(rel) else rel


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── one vault's files and index ───────────────────────────────────────────


class Vault:
    def __init__(self, root: Path, index_path: str):
        self.root = root
        self.index = sqlite3.connect(index_path, check_same_thread=False, isolation_level=None)
        self.index.executescript(INDEX)
        if index_path != ":memory:":
            os.chmod(index_path, 0o600)
        self._lock = threading.Lock()
        self._refreshed = 0.0

    # files
    def resolve(self, rel: str) -> Path:
        """The file for a cleaned path, refused when it leads outside the vault (a symlink out)."""
        p = self.root / rel
        root = os.path.realpath(self.root)
        if not mounts._under(os.path.realpath(p), root):
            raise VaultError(400, t("볼트 밖으로 나가는 경로입니다: {path}", path=rel))
        return p

    def walk(self):  # noqa: ANN201
        """(rel, Path) of every file, dotted folders and files left out, at most MAX_ENTRIES."""
        n = 0
        for dirpath, dirs, files in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(dirpath, d)))
            for f in sorted(files):
                if f.startswith("."):
                    continue
                p = Path(dirpath) / f
                if p.is_symlink():
                    continue
                n += 1
                if n > MAX_ENTRIES:
                    return
                yield p.relative_to(self.root).as_posix(), p

    def tree(self) -> dict:
        top: dict = {"name": "", "path": "", "type": "dir", "children": []}
        nodes: dict[str, dict] = {"": top}

        def folder(rel: str) -> dict:
            if rel in nodes:
                return nodes[rel]
            parent = folder(rel.rpartition("/")[0])
            node = {"name": rel.rpartition("/")[2], "path": rel, "type": "dir", "children": []}
            parent["children"].append(node)
            nodes[rel] = node
            return node

        for rel, p in self.walk():
            parent = folder(rel.rpartition("/")[0])
            try:
                st = p.stat()
            except OSError:
                continue
            parent["children"].append({"name": rel.rpartition("/")[2], "path": rel,
                                       "type": "note" if is_note(rel) else "text" if is_text(rel) else "file",
                                       "mtime": st.st_mtime, "size": st.st_size})
        return top

    def read(self, rel: str) -> dict:
        p = self.resolve(rel)
        if not is_text(rel):
            raise VaultError(415, t("글 파일이 아닙니다: {path}", path=rel))
        try:
            data = p.read_bytes()
        except FileNotFoundError as e:
            raise VaultError(404, t("그런 노트가 없습니다: {path}", path=rel)) from e
        except IsADirectoryError as e:
            raise VaultError(404, t("그런 노트가 없습니다: {path}", path=rel)) from e
        if len(data) > MAX_TEXT:
            raise VaultError(413, t("너무 큰 파일입니다: {path}", path=rel))
        st = p.stat()
        return {"path": rel, "text": data.decode("utf-8", "replace"), "sha256": sha(data), "mtime": st.st_mtime, "size": st.st_size}

    def write(self, rel: str, text: str, if_match: str | None) -> dict:
        p = self.resolve(rel)
        if not is_text(rel):
            raise VaultError(415, t("글 파일이 아닙니다: {path}", path=rel))
        data = text.encode()
        if len(data) > MAX_TEXT:
            raise VaultError(413, t("너무 큰 파일입니다: {path}", path=rel))
        with self._lock:
            exists = p.exists()
            if exists:
                if p.is_dir():
                    raise VaultError(409, t("폴더입니다: {path}", path=rel))
                current = sha(p.read_bytes())
                if if_match is None:
                    raise VaultError(409, t("이미 있는 노트입니다. 지금 내용을 읽은 뒤 고치세요."))
                if if_match != current:
                    raise VaultError(412, t("그 사이 다른 데서 고쳐졌습니다. 다시 읽은 뒤 고치세요."))
            elif if_match:
                raise VaultError(412, t("그 노트는 이제 없습니다."))
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:6]}.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
            st = p.stat()
        self._refreshed = 0
        return {"path": rel, "sha256": sha(data), "mtime": st.st_mtime, "size": st.st_size}

    def raw(self, rel: str) -> tuple[bytes, str]:
        p = self.resolve(rel)
        try:
            if p.stat().st_size > MAX_RAW:
                raise VaultError(413, t("너무 큰 파일입니다: {path}", path=rel))
            data = p.read_bytes()
        except (FileNotFoundError, IsADirectoryError) as e:
            raise VaultError(404, t("그런 파일이 없습니다: {path}", path=rel)) from e
        return data, mimetypes.guess_type(rel)[0] or "application/octet-stream"

    def move(self, src: str, dst: str) -> None:
        a, b = self.resolve(src), self.resolve(dst)
        with self._lock:
            if not a.exists():
                raise VaultError(404, t("그런 노트가 없습니다: {path}", path=src))
            if b.exists():
                raise VaultError(409, t("이미 있는 이름입니다: {path}", path=dst))
            b.parent.mkdir(parents=True, exist_ok=True)
            os.replace(a, b)
        self._refreshed = 0

    def trash(self, rel: str) -> str:
        p = self.resolve(rel)
        with self._lock:
            if not p.exists():
                raise VaultError(404, t("그런 노트가 없습니다: {path}", path=rel))
            target = self.root / TRASH / rel
            if target.exists():
                target = target.with_name(f"{target.stem}.{int(time.time())}{target.suffix}")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(p, target)
        self._refreshed = 0
        return target.relative_to(self.root).as_posix()

    # index
    def refresh(self, force: bool = False) -> None:
        """Read the notes whose mtime changed since the index saw them; forget the ones gone."""
        if not force and time.monotonic() - self._refreshed < REFRESH_EVERY:
            return
        with self._lock:
            known = {r[0]: r[1] for r in self.index.execute("SELECT path, mtime FROM notes")}
            seen = set()
            for rel, p in self.walk():
                if not is_note(rel):
                    continue
                seen.add(rel)
                try:
                    st = p.stat()
                except OSError:
                    continue
                if known.get(rel) == st.st_mtime:
                    continue
                try:
                    text = p.read_bytes()[:MAX_TEXT].decode("utf-8", "replace")
                except OSError:
                    continue
                title = note_name(rel).rpartition("/")[2]
                self.index.execute("DELETE FROM fts WHERE path=?", (rel,))
                self.index.execute("DELETE FROM links WHERE src=?", (rel,))
                self.index.execute("DELETE FROM tags WHERE path=?", (rel,))
                self.index.execute("INSERT OR REPLACE INTO notes VALUES (?,?,?,?)", (rel, title, st.st_mtime, st.st_size))
                self.index.execute("INSERT INTO fts VALUES (?,?,?)", (rel, title, text))
                for m in WIKILINK.finditer(text):
                    self.index.execute("INSERT INTO links VALUES (?,?)", (rel, m.group(1).strip()))
                for m in TAG.finditer(text):
                    self.index.execute("INSERT INTO tags VALUES (?,?)", (rel, m.group(1)))
            for rel in set(known) - seen:
                self.index.execute("DELETE FROM notes WHERE path=?", (rel,))
                self.index.execute("DELETE FROM fts WHERE path=?", (rel,))
                self.index.execute("DELETE FROM links WHERE src=?", (rel,))
                self.index.execute("DELETE FROM tags WHERE path=?", (rel,))
            self._refreshed = time.monotonic()

    def search(self, q: str, limit: int = 50) -> list[dict]:
        self.refresh()
        terms = [x for x in re.split(r"\s+", q.strip()) if x]
        if not terms:
            return []
        match = " ".join('"' + x.replace('"', '""') + '"*' for x in terms)
        with self._lock:
            rows = self.index.execute(
                "SELECT path, title, snippet(fts, 2, '[', ']', '…', 12) FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",
                (match, limit)).fetchall()
        return [{"path": r[0], "title": r[1], "snippet": r[2]} for r in rows]

    def resolve_link(self, target: str, paths: set[str]) -> str | None:
        """Where a [[wikilink]] points: the note of that path, else the one note with that name."""
        name = target.strip().strip("/")
        if not name:
            return None
        for cand in (name, name + NOTE):
            if cand in paths:
                return cand
        tail = name.rpartition("/")[2].lower() + NOTE
        hits = sorted(p for p in paths if p.rpartition("/")[2].lower() == tail)
        return hits[0] if hits else None

    def links(self, rel: str) -> dict:
        self.refresh()
        with self._lock:
            paths = {r[0] for r in self.index.execute("SELECT path FROM notes")}
            out = [r[0] for r in self.index.execute("SELECT dst FROM links WHERE src=? ORDER BY rowid", (rel,))]
            rows = self.index.execute("SELECT src, dst FROM links").fetchall()
        links, seen = [], set()
        for dst in out:
            to = self.resolve_link(dst, paths)
            if (to or dst) in seen:
                continue
            seen.add(to or dst)
            links.append({"path": to, "text": dst})
        backlinks = sorted({src for src, dst in rows if src != rel and self.resolve_link(dst, paths) == rel})
        return {"path": rel, "links": links, "backlinks": backlinks}

    def recent(self, n: int = 10) -> list[dict]:
        self.refresh()
        with self._lock:
            rows = self.index.execute("SELECT path, title, mtime, size FROM notes ORDER BY mtime DESC LIMIT ?", (n,)).fetchall()
        return [{"path": r[0], "title": r[1], "mtime": r[2], "size": r[3]} for r in rows]

    def tags(self) -> list[dict]:
        self.refresh()
        with self._lock:
            rows = self.index.execute("SELECT tag, count(*) FROM tags GROUP BY tag ORDER BY count(*) DESC, tag").fetchall()
        return [{"tag": r[0], "notes": r[1]} for r in rows]


# ── the service ───────────────────────────────────────────────────────────


def create_app(settings: Settings | None = None, registry: Registry | None = None, public_key=None,  # noqa: ANN001
               roots: str | None = None, stage: str | None = None, data_dir: str | None = None) -> FastAPI:
    s = settings or Settings()
    public_key = public_key or tokens.load_public_key(s.sso_public_key_file)
    registry = registry or Registry(s.vault_db)
    offered = mounts.parse(roots if roots is not None else s.vault_roots)
    stage_root = Path(stage) if stage else (Path(s.vault_stage) if s.vault_stage else None)
    data = Path(data_dir or s.vault_data)
    vaults: dict[str, Vault] = {}
    open_lock = threading.Lock()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SecurityHeadersMiddleware)
    from . import i18n

    app.add_middleware(i18n.Language)

    def err(status: int, message: str) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    @app.exception_handler(VaultError)
    async def vault_error(request: Request, e: VaultError):  # noqa: ANN202
        return err(e.status, str(e))

    def gate(request: Request) -> str:
        token = request.headers.get("x-auth-token", "")
        try:
            uid = tokens.verify(public_key, token, s.sso_issuer, AUDIENCE) if token else ""
        except tokens.TokenError:
            uid = ""
        if not uid:
            raise VaultError(401, t("먼저 로그인하세요."))
        return uid

    def status(uid: str, rec: VaultRecord) -> tuple[str, Path | None]:
        """Whether the vault's files can be reached now: ok (with the directory), pending (root has not
        staged it yet), or why not."""
        if stage_root is None:
            p = Path(rec.path)
            return ("ok", p) if p.is_dir() else (t("그런 디렉터리가 없습니다."), None)
        st = mounts.status_of(stage_root, uid).get(rec.path)
        if st == "ok":
            p = mounts.staged_path(stage_root, uid, rec.path)
            return ("ok", p) if p.is_dir() else ("pending", None)
        return (st or "pending", None)

    def item(uid: str, rec: VaultRecord) -> dict:
        st, _ = status(uid, rec)
        return {"id": rec.id, "name": rec.name, "path": rec.path, "status": st, "created": rec.created}

    def opened(uid: str, vid: str) -> Vault:
        rec = registry.get(uid, vid)
        if not rec:
            raise VaultError(404, t("그런 볼트가 없습니다."))
        st, root = status(uid, rec)
        if root is None:
            raise VaultError(409 if st == "pending" else 404, t("볼트가 아직 준비되지 않았습니다.") if st == "pending" else st)
        key = f"{uid}/{rec.id}"
        with open_lock:
            v = vaults.get(key)
            if v is None or v.root != root:
                (data / "index").mkdir(parents=True, exist_ok=True)
                v = vaults[key] = Vault(root, str(data / "index" / f"{uid}-{rec.id}.db"))
        return v

    async def body_of(request: Request) -> dict:
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise VaultError(415, "send application/json")
        try:
            body = await request.body()
            if len(body) > MAX_TEXT + 4096:
                raise VaultError(413, t("너무 큰 파일입니다: {path}", path=request.query_params.get("path", "")))
            d = json.loads(body)
        except ValueError as e:
            raise VaultError(400, "the body is not JSON") from e
        if not isinstance(d, dict):
            raise VaultError(400, "the body is not a JSON object")
        return d

    def rel_of(request: Request, name: str = "path") -> str:
        return clean(request.query_params.get(name, ""))

    # ── vaults
    @app.get(f"{PREFIX}/vaults")
    async def list_vaults(request: Request):
        uid = gate(request)
        try:
            import pwd

            n = pwd.getpwnam(uid).pw_uid
        except KeyError:
            n = 0
        where = [mounts.expand(o.template, uid, n) for o in offered]
        return {"vaults": [item(uid, r) for r in registry.of(uid)], "roots": where}

    @app.post(f"{PREFIX}/vaults")
    async def add_vault(request: Request):
        uid = gate(request)
        d = await body_of(request)
        path = str(d.get("path") or "").strip()
        name = str(d.get("name") or "").strip()[:60]
        if not path:
            raise VaultError(400, t("경로를 주세요."))
        try:
            import pwd

            n = pwd.getpwnam(uid).pw_uid
        except KeyError:
            n = 0
        try:
            host, _ = mounts.source_path(path, offered, uid, n)
        except mounts.MountError as e:
            raise VaultError(400, str(e)) from e
        if len(registry.of(uid)) >= 20:
            raise VaultError(409, t("볼트는 20개까지입니다."))
        rec = registry.add(uid, name or host.rpartition("/")[2] or host, host)
        if stage_root is not None:
            mounts.request(data)  # root stages it now (<name>-vault-mounts.path), else within a minute
        return JSONResponse(item(uid, rec), status_code=201)

    @app.delete(f"{PREFIX}/vaults/{{vid}}")
    async def remove_vault(request: Request, vid: str):
        uid = gate(request)
        if not registry.remove(uid, vid):
            raise VaultError(404, t("그런 볼트가 없습니다."))
        vaults.pop(f"{uid}/{vid}", None)
        if stage_root is not None:
            mounts.request(data)
        return Response(status_code=204)

    # ── files
    @app.get(f"{PREFIX}/vaults/{{vid}}/tree")
    async def tree(request: Request, vid: str):
        return opened(gate(request), vid).tree()

    @app.get(f"{PREFIX}/vaults/{{vid}}/file")
    async def read(request: Request, vid: str):
        return opened(gate(request), vid).read(rel_of(request))

    @app.put(f"{PREFIX}/vaults/{{vid}}/file")
    async def write(request: Request, vid: str):
        uid = gate(request)
        rel = rel_of(request)
        d = await body_of(request)
        text = d.get("text")
        if not isinstance(text, str):
            raise VaultError(400, t("text 에 글을 주세요."))
        return opened(uid, vid).write(rel, text, request.headers.get("if-match"))

    @app.get(f"{PREFIX}/vaults/{{vid}}/raw")
    async def raw(request: Request, vid: str):
        data_, kind = opened(gate(request), vid).raw(rel_of(request))
        # a file that could run as a page (an SVG with a script, an HTML file) is only ever downloaded
        how = "attachment" if kind in ("image/svg+xml", "text/html", "application/xhtml+xml", "text/xml", "application/xml") else "inline"
        return Response(data_, media_type=kind, headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff",
                                                         "Content-Disposition": how})

    @app.post(f"{PREFIX}/vaults/{{vid}}/move")
    async def move(request: Request, vid: str):
        uid = gate(request)
        d = await body_of(request)
        src, dst = clean(str(d.get("from") or "")), clean(str(d.get("to") or ""))
        opened(uid, vid).move(src, dst)
        return {"path": dst}

    @app.delete(f"{PREFIX}/vaults/{{vid}}/file")
    async def trash(request: Request, vid: str):
        rel = rel_of(request)
        return {"path": rel, "trash": opened(gate(request), vid).trash(rel)}

    # ── index
    @app.get(f"{PREFIX}/vaults/{{vid}}/search")
    async def search(request: Request, vid: str):
        q = request.query_params.get("q", "")
        return {"q": q, "hits": opened(gate(request), vid).search(q)}

    @app.get(f"{PREFIX}/vaults/{{vid}}/links")
    async def links(request: Request, vid: str):
        return opened(gate(request), vid).links(rel_of(request))

    @app.get(f"{PREFIX}/vaults/{{vid}}/recent")
    async def recent(request: Request, vid: str):
        try:
            n = max(1, min(100, int(request.query_params.get("n", "10"))))
        except ValueError:
            n = 10
        return {"notes": opened(gate(request), vid).recent(n)}

    @app.get(f"{PREFIX}/vaults/{{vid}}/tags")
    async def tags(request: Request, vid: str):
        return {"tags": opened(gate(request), vid).tags()}

    @app.get("/vault/healthz")
    async def healthz():
        return Response("ok", media_type="text/plain")

    return app
