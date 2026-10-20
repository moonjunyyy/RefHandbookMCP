"""One-time invitation links: an admin makes one, and whoever receives it chooses a username and a
password and has an account at once (portal/main.py: /join/<token>), with no one-time password to
pass on.

Only a hash of the token is kept, so the database alone cannot be used to sign up. A link works
once: it is claimed before the account is made, and put back if making it fails. Unused links
expire after `ttl_hours`.
"""
import hashlib
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS invites (
    id         TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    note       TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created    REAL NOT NULL,
    expires    REAL NOT NULL
);
"""


class InviteError(Exception):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Invite:
    id: str
    token_hash: str
    note: str
    created_by: str
    created: float
    expires: float

    @property
    def expires_text(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.expires))


class InviteStore:
    def __init__(self, path: str, ttl_hours: int = 168, max_active: int = 100):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.ttl = ttl_hours * 3600
        self.max_active = max_active
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.executescript(SCHEMA)
        if path != ":memory:":
            os.chmod(path, 0o600)

    def _sweep(self) -> None:
        self.db.execute("DELETE FROM invites WHERE expires < ?", (time.time(),))

    def create(self, created_by: str, note: str = "") -> tuple[Invite, str]:
        """A new invite and its token (the token is shown once and never stored)."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        inv = Invite(secrets.token_urlsafe(9), _hash(token), note, created_by, now, now + self.ttl)
        with self._lock:
            self._sweep()
            if self.db.execute("SELECT count(*) FROM invites").fetchone()[0] >= self.max_active:
                raise InviteError("Too many open invitations: revoke some first.")
            self.db.execute("INSERT INTO invites VALUES (?,?,?,?,?,?)",
                            (inv.id, inv.token_hash, inv.note, inv.created_by, inv.created, inv.expires))
        return inv, token

    def list(self) -> list[Invite]:
        with self._lock:
            self._sweep()
            rows = self.db.execute("SELECT * FROM invites ORDER BY created").fetchall()
        return [Invite(*r) for r in rows]

    def find(self, token: str) -> Invite | None:
        with self._lock:
            self._sweep()
            row = self.db.execute("SELECT * FROM invites WHERE token_hash=?", (_hash(token),)).fetchone()
        return Invite(*row) if row else None

    def claim(self, token: str) -> Invite | None:
        """Take the invite out, so a second use of the link (even a concurrent one) finds nothing."""
        with self._lock:
            self._sweep()
            row = self.db.execute("SELECT * FROM invites WHERE token_hash=?", (_hash(token),)).fetchone()
            if row is None:
                return None
            self.db.execute("DELETE FROM invites WHERE id=?", (row[0],))
        return Invite(*row)

    def restore(self, inv: Invite) -> None:
        """Put a claimed invite back (making the account failed)."""
        with self._lock:
            self.db.execute("INSERT OR IGNORE INTO invites VALUES (?,?,?,?,?,?)",
                            (inv.id, inv.token_hash, inv.note, inv.created_by, inv.created, inv.expires))

    def revoke(self, iid: str) -> bool:
        with self._lock:
            return self.db.execute("DELETE FROM invites WHERE id=?", (iid,)).rowcount == 1
