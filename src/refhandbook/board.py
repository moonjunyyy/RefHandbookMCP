"""The public board (docs/board.md): what the site's people share with each other, in one place.

Two things live here, in one SQLite file of the server's (<data>/board.db):

- a share: a copy of something of one person's that others may take — a preset (the agents' flow: its
  blocks, their commands and models, the run's limits; never its keys) or a layer (the sandbox's: its
  build script, its parents among the server's shared layers, its env). It is a snapshot taken when it
  is shared: what the author changes afterwards reaches the board only when they share it again (its
  version goes up). Taking it (import) copies it into the taker's own store, under their own name; a
  layer taken is built by its taker, in their sandbox, under their own policy.
- a notice: the site's administrators' word to everyone (the server's news), pinned or not.

Who: everyone signed in reads; a share is its author's to change and to take down; an administrator may
hide a share (with the reason, which its author sees) or take it down, and writes the notices. There is
no comment and no free post: the board is not a bulletin board (docs/board.md, "What is not here").

The kinds and their limits are declared below, once; the API (board_api.py) and the page read them.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from portal.i18n import t

KINDS = ("preset", "layer")  # what may be shared: the agents' presets, the sandbox's layers
TITLE_MAX = 80  # a share's or a notice's title
ABOUT_MAX = 240  # a share's line: what it is for
NOTICE_MAX = 4000  # a notice's text (markdown, rendered without HTML)
PAYLOAD_MAX = 256 * 1024  # the copy a share carries
SHARES_PER_AUTHOR = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS shares (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, author TEXT NOT NULL,
  title TEXT NOT NULL, about TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, imports INTEGER NOT NULL DEFAULT 0,
  created REAL NOT NULL, updated REAL NOT NULL, hidden_by TEXT, hidden_why TEXT,
  UNIQUE (kind, author, name));
CREATE TABLE IF NOT EXISTS notices (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, author TEXT NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
"""


class BoardError(ValueError):
    """A request the board refuses, said to the person (status: the HTTP status the API answers with)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Share:
    id: str
    kind: str
    name: str
    author: str
    title: str
    about: str
    payload: dict[str, Any]
    version: int
    imports: int
    created: float
    updated: float
    hidden_by: str | None
    hidden_why: str | None

    def json(self, *, payload: bool = False) -> dict[str, Any]:
        out = {"id": self.id, "kind": self.kind, "name": self.name, "author": self.author, "title": self.title,
               "about": self.about, "version": self.version, "imports": self.imports, "created": self.created,
               "updated": self.updated, "hidden": bool(self.hidden_by), "hidden_why": self.hidden_why}
        return {**out, "payload": self.payload} if payload else out


@dataclass(frozen=True)
class Notice:
    id: str
    title: str
    body: str
    author: str
    pinned: bool
    created: float
    updated: float

    def json(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "body": self.body, "author": self.author, "pinned": self.pinned,
                "created": self.created, "updated": self.updated}


def _text(value: Any, limit: int, what: str, required: bool = True, oneline: bool = True) -> str:
    """A text the person wrote, checked: required or not, at most `limit` characters; one line unless it is a
    notice's body (its line breaks are its paragraphs)."""
    s = " ".join(str(value or "").split()) if oneline else str(value or "").strip()
    if required and not s:
        raise BoardError(t("{what} 을(를) 적으세요.", what=what))
    if len(s) > limit:
        raise BoardError(t("{what} 은(는) {n}자까지입니다.", what=what, n=limit))
    return s


class Board:
    """The board's file. Every method takes the store's own lock: callers need none."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    # ── shares ───────────────────────────────────────────────────────────

    @staticmethod
    def _share(r: tuple) -> Share:
        return Share(r[0], r[1], r[2], r[3], r[4], r[5], json.loads(r[6]), r[7], r[8], r[9], r[10], r[11], r[12])

    _COLS = "id, kind, name, author, title, about, payload, version, imports, created, updated, hidden_by, hidden_why"

    def shares(self, viewer: str, admin: bool = False, kind: str | None = None) -> list[Share]:
        """What `viewer` sees, newest first: every share not hidden, and the hidden ones that are theirs (an
        administrator sees all)."""
        q = f"SELECT {self._COLS} FROM shares WHERE (hidden_by IS NULL OR author = ? OR ?)"
        args: list[Any] = [viewer, int(admin)]
        if kind:
            q += " AND kind = ?"
            args.append(kind)
        with self._lock:
            return [self._share(r) for r in self._db.execute(q + " ORDER BY updated DESC", args)]

    def share(self, sid: str, viewer: str, admin: bool = False) -> Share:
        with self._lock:
            r = self._db.execute(f"SELECT {self._COLS} FROM shares WHERE id = ?", (sid,)).fetchone()
        s = self._share(r) if r else None
        if s is None or (s.hidden_by and s.author != viewer and not admin):
            raise BoardError(t("그런 공유가 없습니다."), 404)
        return s

    def put(self, kind: str, name: str, author: str, title: str, about: str, payload: dict[str, Any]) -> Share:
        """Share (or share again: the same author's same kind and name — a new version) a snapshot."""
        if kind not in KINDS:
            raise BoardError(t("공유할 수 있는 것은 {kinds} 입니다.", kinds=", ".join(KINDS)))
        title = _text(title, TITLE_MAX, t("제목"))
        about = _text(about, ABOUT_MAX, t("설명"), required=False)
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(data.encode()) > PAYLOAD_MAX:
            raise BoardError(t("공유하기에 너무 큽니다 ({n} KB 까지).", n=PAYLOAD_MAX // 1024))
        now = round(time.time(), 3)
        with self._lock, self._db:
            r = self._db.execute("SELECT id FROM shares WHERE kind = ? AND author = ? AND name = ?", (kind, author, name)).fetchone()
            if r:
                self._db.execute("UPDATE shares SET title = ?, about = ?, payload = ?, version = version + 1, updated = ? WHERE id = ?",
                                 (title, about, data, now, r[0]))
                sid = r[0]
            else:
                if self._db.execute("SELECT count(*) FROM shares WHERE author = ?", (author,)).fetchone()[0] >= SHARES_PER_AUTHOR:
                    raise BoardError(t("공유는 한 사람이 {n}개까지입니다.", n=SHARES_PER_AUTHOR))
                sid = secrets.token_hex(6)
                self._db.execute(f"INSERT INTO shares ({self._COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, NULL, NULL)",
                                 (sid, kind, name, author, title, about, data, now, now))
        return self.share(sid, author)

    def remove(self, sid: str, actor: str, admin: bool = False) -> None:
        s = self.share(sid, actor, admin)
        if s.author != actor and not admin:
            raise BoardError(t("자기 공유만 내릴 수 있습니다."), 403)
        with self._lock, self._db:
            self._db.execute("DELETE FROM shares WHERE id = ?", (sid,))

    def hide(self, sid: str, actor: str, why: str, admin: bool) -> Share:
        if not admin:
            raise BoardError(t("관리자만 숨길 수 있습니다."), 403)
        why = _text(why, ABOUT_MAX, t("숨기는 까닭"))
        self.share(sid, actor, admin)
        with self._lock, self._db:
            self._db.execute("UPDATE shares SET hidden_by = ?, hidden_why = ? WHERE id = ?", (actor, why, sid))
        return self.share(sid, actor, admin)

    def show(self, sid: str, actor: str, admin: bool) -> Share:
        if not admin:
            raise BoardError(t("관리자만 다시 보일 수 있습니다."), 403)
        self.share(sid, actor, admin)
        with self._lock, self._db:
            self._db.execute("UPDATE shares SET hidden_by = NULL, hidden_why = NULL WHERE id = ?", (sid,))
        return self.share(sid, actor, admin)

    def taken(self, sid: str) -> None:
        """Count one taking of a share."""
        with self._lock, self._db:
            self._db.execute("UPDATE shares SET imports = imports + 1 WHERE id = ?", (sid,))

    # ── notices ──────────────────────────────────────────────────────────

    def notices(self) -> list[Notice]:
        with self._lock:
            rows = self._db.execute("SELECT id, title, body, author, pinned, created, updated FROM notices "
                                    "ORDER BY pinned DESC, created DESC").fetchall()
        return [Notice(r[0], r[1], r[2], r[3], bool(r[4]), r[5], r[6]) for r in rows]

    def notice(self, nid: str) -> Notice:
        n = next((x for x in self.notices() if x.id == nid), None)
        if n is None:
            raise BoardError(t("그런 공지가 없습니다."), 404)
        return n

    def post(self, actor: str, admin: bool, title: str, body: str, pinned: bool = False) -> Notice:
        if not admin:
            raise BoardError(t("공지는 관리자가 씁니다."), 403)
        title, body = _text(title, TITLE_MAX, t("제목")), _text(body, NOTICE_MAX, t("내용"), oneline=False)
        now = round(time.time(), 3)
        nid = secrets.token_hex(6)
        with self._lock, self._db:
            self._db.execute("INSERT INTO notices (id, title, body, author, pinned, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (nid, title, body, actor, int(bool(pinned)), now, now))
        return self.notice(nid)

    def edit(self, nid: str, admin: bool, *, title: Any = None, body: Any = None, pinned: Any = None) -> Notice:
        if not admin:
            raise BoardError(t("공지는 관리자가 씁니다."), 403)
        n = self.notice(nid)
        title = n.title if title is None else _text(title, TITLE_MAX, t("제목"))
        body = n.body if body is None else _text(body, NOTICE_MAX, t("내용"), oneline=False)
        pin = n.pinned if pinned is None else bool(pinned)
        with self._lock, self._db:
            self._db.execute("UPDATE notices SET title = ?, body = ?, pinned = ?, updated = ? WHERE id = ?",
                             (title, body, int(pin), round(time.time(), 3), nid))
        return self.notice(nid)

    def unpost(self, nid: str, admin: bool) -> None:
        if not admin:
            raise BoardError(t("공지는 관리자가 씁니다."), 403)
        self.notice(nid)
        with self._lock, self._db:
            self._db.execute("DELETE FROM notices WHERE id = ?", (nid,))
