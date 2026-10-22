"""Pending account requests ("사용 신청"), kept in a small SQLite file until an admin decides.

A request holds personal data (name, email), so it lives only as long as it must: it is deleted
when an admin approves or rejects it, and unanswered requests are swept after `ttl_days`.
Nothing here touches LDAP or Kerberos; approval goes through the normal create-user path.
"""
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id      TEXT PRIMARY KEY,
    uid     TEXT NOT NULL UNIQUE,
    name    TEXT NOT NULL DEFAULT '',
    mail    TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL,
    created REAL NOT NULL
);
"""


class RequestError(Exception):
    pass


@dataclass
class AccountRequest:
    id: str
    uid: str
    name: str
    mail: str
    purpose: str
    created: float

    @property
    def created_text(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.created))


class RequestStore:
    def __init__(self, path: str, ttl_days: int = 30, max_pending: int = 100):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.ttl = ttl_days * 86400
        self.max_pending = max_pending
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.executescript(SCHEMA)
        if path != ":memory:":
            os.chmod(path, 0o600)

    def _sweep(self) -> None:
        self.db.execute("DELETE FROM requests WHERE created < ?", (time.time() - self.ttl,))

    def add(self, uid: str, name: str, mail: str, purpose: str) -> bool:
        """False if the name is already requested (the caller shows the same message either way)."""
        with self._lock:
            self._sweep()
            if self.db.execute("SELECT count(*) FROM requests").fetchone()[0] >= self.max_pending:
                raise RequestError("Too many pending requests.")
            cur = self.db.execute("INSERT OR IGNORE INTO requests VALUES (?,?,?,?,?,?)",
                                  (secrets.token_urlsafe(12), uid, name, mail, purpose, time.time()))
            return cur.rowcount == 1

    def list(self) -> list[AccountRequest]:
        with self._lock:
            self._sweep()
            rows = self.db.execute("SELECT * FROM requests ORDER BY created").fetchall()
        return [AccountRequest(*r) for r in rows]

    def count(self) -> int:
        with self._lock:
            self._sweep()
            return self.db.execute("SELECT count(*) FROM requests").fetchone()[0]

    def get(self, rid: str) -> AccountRequest | None:
        with self._lock:
            self._sweep()
            row = self.db.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
        return AccountRequest(*row) if row else None

    def delete(self, rid: str) -> None:
        with self._lock:
            self.db.execute("DELETE FROM requests WHERE id=?", (rid,))
