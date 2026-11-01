"""Projects: groups people make themselves, for what they do together (docs/projects.md).

A project is a POSIX group under the projects' OU (`ou=Projects` beneath the groups' OU): its
members are its `memberUid`, which NSS, the file server and the sandbox see as they see any group.
What the directory does not hold — who owns it, how one joins, whether it is listed, the join
requests and the invitation links — is the portal's, in PORTAL_PROJECTS_DB (SQLite, 0600), as
account requests and invitations are.

Every operation checks who may do it, validates what it is given, does it (directory, store) and
records it (audit), once, for the pages and the API alike (as portal/accounts.py). Refusals are
Forbidden and ValidationError as there; a backend failure (DirectoryError) propagates as it is.

Who is what to a project: a member (in its group); an owner (a member who manages it: there is
always at least one); a site admin (an owner's rights on every project, a member of none unless
added). Nothing is deleted: a project is archived — its group and its members stay, so their files
stay theirs; the portal refuses changes until it is restored, and the provisioner withdraws what it
set up for it.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from . import audit, validators
from .accounts import Forbidden
from .config import Settings
from .directory import DirectoryError, Project
from .i18n import t
from .rbac import Actor
from .validators import ValidationError

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    cn          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    join_policy TEXT NOT NULL DEFAULT 'request',
    listed      INTEGER NOT NULL DEFAULT 1,
    created     REAL NOT NULL,
    created_by  TEXT NOT NULL,
    archived    REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS owners (
    cn  TEXT NOT NULL,
    uid TEXT NOT NULL,
    PRIMARY KEY (cn, uid)
);
CREATE TABLE IF NOT EXISTS requests (
    id      TEXT PRIMARY KEY,
    cn      TEXT NOT NULL,
    uid     TEXT NOT NULL,
    note    TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL,
    UNIQUE (cn, uid)
);
CREATE TABLE IF NOT EXISTS invites (
    id         TEXT PRIMARY KEY,
    cn         TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    note       TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created    REAL NOT NULL,
    expires    REAL NOT NULL
);
"""

MANAGERS = ("owner", "admin")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Record:
    """The portal's side of a project (the directory holds the group itself)."""
    cn: str
    title: str
    description: str
    join_policy: str
    listed: bool
    created: float
    created_by: str
    archived: float  # 0: live; else when it was archived
    owners: list[str] = field(default_factory=list)


@dataclass
class JoinRequest:
    id: str
    cn: str
    uid: str
    note: str
    created: float


@dataclass
class ProjectInvite:
    id: str
    cn: str
    token_hash: str
    note: str
    created_by: str
    created: float
    expires: float


@dataclass
class View:
    """A project as a person sees it: the group, the record, and what they are to it."""
    cn: str
    gid: int
    title: str
    description: str
    join_policy: str
    listed: bool
    created: float
    created_by: str
    archived: float
    members: list[str]
    owners: list[str]
    role: str  # owner | admin | member | none — what the viewer is to it
    member: bool  # the viewer is in its group (an admin may or may not be)
    requested: bool  # the viewer has asked to join and waits

    @property
    def manages(self) -> bool:
        return self.role in MANAGERS


class ProjectStore:
    def __init__(self, path: str, invite_ttl_hours: int = 168, max_invites: int = 100):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.invite_ttl = invite_ttl_hours * 3600
        self.max_invites = max_invites
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.executescript(SCHEMA)
        if path != ":memory:":
            os.chmod(path, 0o600)

    # ── projects and owners ───────────────────────────────────────────────

    def _record(self, row: tuple) -> Record:
        cn, title, description, policy, listed, created, by, archived = row
        owners = [r[0] for r in self.db.execute("SELECT uid FROM owners WHERE cn=? ORDER BY uid", (cn,))]
        return Record(cn, title, description, policy, bool(listed), created, by, archived, owners)

    def add(self, cn: str, title: str, description: str, join_policy: str, listed: bool, by: str) -> Record:
        with self._lock:
            self.db.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,0)",
                            (cn, title, description, join_policy, int(listed), time.time(), by))
            self.db.execute("INSERT INTO owners VALUES (?,?)", (cn, by))
            return self.get(cn)  # type: ignore[return-value]

    def get(self, cn: str) -> Record | None:
        row = self.db.execute("SELECT * FROM projects WHERE cn=?", (cn,)).fetchone()
        return self._record(row) if row else None

    def all(self) -> list[Record]:
        return [self._record(r) for r in self.db.execute("SELECT * FROM projects ORDER BY cn").fetchall()]

    def update(self, cn: str, **changes: Any) -> Record:
        cols = {"title", "description", "join_policy", "listed"}
        bad = set(changes) - cols
        if bad:
            raise ValueError(f"not a project column: {', '.join(sorted(bad))}")
        if changes:
            sets = ", ".join(f"{k}=?" for k in changes)
            vals = [int(v) if k == "listed" else v for k, v in changes.items()]
            with self._lock:
                self.db.execute(f"UPDATE projects SET {sets} WHERE cn=?", (*vals, cn))
        return self.get(cn)  # type: ignore[return-value]

    def set_owner(self, cn: str, uid: str, owner: bool) -> None:
        with self._lock:
            if owner:
                self.db.execute("INSERT OR IGNORE INTO owners VALUES (?,?)", (cn, uid))
            else:
                self.db.execute("DELETE FROM owners WHERE cn=? AND uid=?", (cn, uid))

    def set_archived(self, cn: str, archived: bool) -> Record:
        with self._lock:
            self.db.execute("UPDATE projects SET archived=? WHERE cn=?", (time.time() if archived else 0, cn))
        return self.get(cn)  # type: ignore[return-value]

    def remove(self, cn: str) -> None:
        """Only to undo a creation that failed halfway: a project is otherwise archived, never removed."""
        with self._lock:
            for table in ("owners", "requests", "invites", "projects"):
                self.db.execute(f"DELETE FROM {table} WHERE cn=?", (cn,))

    # ── join requests ─────────────────────────────────────────────────────

    def request_add(self, cn: str, uid: str, note: str) -> JoinRequest:
        r = JoinRequest(secrets.token_urlsafe(9), cn, uid, note, time.time())
        with self._lock:
            self.db.execute("INSERT INTO requests VALUES (?,?,?,?,?)", (r.id, r.cn, r.uid, r.note, r.created))
        return r

    def requests(self, cn: str) -> list[JoinRequest]:
        return [JoinRequest(*r) for r in self.db.execute("SELECT * FROM requests WHERE cn=? ORDER BY created", (cn,))]

    def request(self, cn: str, rid: str) -> JoinRequest | None:
        row = self.db.execute("SELECT * FROM requests WHERE cn=? AND id=?", (cn, rid)).fetchone()
        return JoinRequest(*row) if row else None

    def requested(self, cn: str, uid: str) -> bool:
        return self.db.execute("SELECT 1 FROM requests WHERE cn=? AND uid=?", (cn, uid)).fetchone() is not None

    def request_delete(self, cn: str, uid: str) -> bool:
        with self._lock:
            return self.db.execute("DELETE FROM requests WHERE cn=? AND uid=?", (cn, uid)).rowcount > 0

    # ── invitation links (as portal/invites.py: the token's hash alone is kept) ──

    def _sweep(self) -> None:
        self.db.execute("DELETE FROM invites WHERE expires < ?", (time.time(),))

    def invite_create(self, cn: str, by: str, note: str) -> tuple[ProjectInvite, str]:
        token = secrets.token_urlsafe(32)
        now = time.time()
        inv = ProjectInvite(secrets.token_urlsafe(9), cn, _hash(token), note, by, now, now + self.invite_ttl)
        with self._lock:
            self._sweep()
            if self.db.execute("SELECT count(*) FROM invites WHERE cn=?", (cn,)).fetchone()[0] >= self.max_invites:
                raise ValidationError(t("살아 있는 초대 링크가 너무 많습니다. 몇 개를 먼저 거두세요."))
            self.db.execute("INSERT INTO invites VALUES (?,?,?,?,?,?,?)",
                            (inv.id, inv.cn, inv.token_hash, inv.note, inv.created_by, inv.created, inv.expires))
        return inv, token

    def invites(self, cn: str) -> list[ProjectInvite]:
        with self._lock:
            self._sweep()
            rows = self.db.execute("SELECT * FROM invites WHERE cn=? ORDER BY created", (cn,)).fetchall()
        return [ProjectInvite(*r) for r in rows]

    def invite_claim(self, token: str) -> ProjectInvite | None:
        """Take the invite out, so a second use of the link (even a concurrent one) finds nothing."""
        with self._lock:
            self._sweep()
            row = self.db.execute("SELECT * FROM invites WHERE token_hash=?", (_hash(token),)).fetchone()
            if row is None:
                return None
            self.db.execute("DELETE FROM invites WHERE id=?", (row[0],))
        return ProjectInvite(*row)

    def invite_restore(self, inv: ProjectInvite) -> None:
        with self._lock:
            self.db.execute("INSERT OR IGNORE INTO invites VALUES (?,?,?,?,?,?,?)",
                            (inv.id, inv.cn, inv.token_hash, inv.note, inv.created_by, inv.created, inv.expires))

    def invite_revoke(self, cn: str, iid: str) -> bool:
        with self._lock:
            return self.db.execute("DELETE FROM invites WHERE cn=? AND id=?", (cn, iid)).rowcount == 1


@dataclass
class Projects:
    """What a signed-in person can do with projects."""
    s: Settings
    directory: Any
    store: ProjectStore

    # ── who ──────────────────────────────────────────────────────────────

    def may_create(self, actor: Actor) -> bool:
        return "admin" in actor.roles or self.s.project_create == "user"

    def _role(self, actor: Actor, rec: Record, members: list[str]) -> str:
        if actor.uid in rec.owners:
            return "owner"
        if "admin" in actor.roles:
            return "admin"
        if actor.uid in members:
            return "member"
        return "none"

    def _view(self, actor: Actor, p: Project, rec: Record) -> View:
        return View(cn=p.cn, gid=p.gid_number, title=rec.title, description=rec.description,
                    join_policy=rec.join_policy, listed=rec.listed, created=rec.created, created_by=rec.created_by,
                    archived=rec.archived, members=p.members, owners=rec.owners,
                    role=self._role(actor, rec, p.members), member=actor.uid in p.members,
                    requested=self.store.requested(p.cn, actor.uid))

    def _load(self, cn: str) -> tuple[Project, Record]:
        """The group and the record, or Forbidden (the same answer whether it is absent or hidden)."""
        try:
            cn = validators.group(cn)
        except ValidationError:
            cn = ""
        p = self.directory.get_project(cn) if cn else None
        rec = self.store.get(cn) if p is not None else None
        if p is None or rec is None:
            raise Forbidden(t("그런 프로젝트가 없습니다."))
        return p, rec

    def _manage(self, actor: Actor, cn: str, live: bool = True) -> tuple[Project, Record]:
        p, rec = self._load(cn)
        if self._role(actor, rec, p.members) not in MANAGERS:
            raise Forbidden(t("이 프로젝트를 관리할 권한이 없습니다."))
        if live and rec.archived:
            raise Forbidden(t("보관된 프로젝트는 바꿀 수 없습니다. 먼저 되살리세요."))
        return p, rec

    def _user(self, uid: str) -> Any:
        try:
            user = self.directory.get_user(validators.uid(uid))
        except ValidationError:
            user = None
        if user is None or user.disabled:
            raise Forbidden(t("그런 사용자가 없습니다."))
        return user

    # ── reading ──────────────────────────────────────────────────────────

    def list(self, actor: Actor) -> list[View]:
        """The projects a person may see: their own, every listed one, and (an admin) all of them.
        An archived project shows only to its members and to admins."""
        recs = {r.cn: r for r in self.store.all()}
        admin = "admin" in actor.roles
        out = []
        for p in self.directory.list_projects():
            rec = recs.get(p.cn)
            if rec is None:
                continue  # a group under the OU the portal did not make: not a project here
            mine = actor.uid in p.members
            if (rec.listed and not rec.archived) or mine or admin:
                out.append(self._view(actor, p, rec))
        return sorted(out, key=lambda v: (not v.member, v.title.lower(), v.cn))

    def get(self, actor: Actor, cn: str) -> View:
        p, rec = self._load(cn)
        v = self._view(actor, p, rec)
        if not (v.member or v.role in MANAGERS or (rec.listed and not rec.archived)):
            raise Forbidden(t("그런 프로젝트가 없습니다."))
        return v

    def mine(self, uid: str) -> list[str]:
        return self.directory.projects_of(uid)

    # ── the project itself ───────────────────────────────────────────────

    def create(self, actor: Actor, values: dict[str, Any], ip: str) -> View:
        if not self.may_create(actor):
            raise Forbidden(t("이 사이트에서는 관리자만 프로젝트를 만듭니다."))
        cn = validators.project_name(str(values.get("name", "")))
        title = validators.name(str(values.get("title", "")) or cn, t("프로젝트 이름"))
        description = validators.description(str(values.get("description", "")))
        policy = validators.join_policy(str(values.get("join_policy", "request")))
        listed = bool(values.get("listed", True))
        if self.store.get(cn) is not None:
            raise ValidationError(t("'{cn}'은(는) 이미 쓰이는 이름입니다. 다른 이름을 고르세요.", cn=cn))
        p = self.directory.create_project(cn, description, [actor.uid])  # DirectoryError if a user or group has the name
        try:
            rec = self.store.add(cn, title, description, policy, listed, actor.uid)
        except sqlite3.Error:
            self.directory.delete_project(cn)
            raise
        audit.record(actor.uid, "project_create", cn, True, ip, f"gid={p.gid_number} join={policy} listed={int(listed)}")
        return self._view(actor, p, rec)

    def update(self, actor: Actor, cn: str, values: dict[str, Any], ip: str) -> View:
        p, rec = self._manage(actor, cn)
        changes: dict[str, Any] = {}
        if "title" in values:
            changes["title"] = validators.name(str(values["title"]), t("프로젝트 이름"))
        if "description" in values:
            changes["description"] = validators.description(str(values["description"]))
        if "join_policy" in values:
            changes["join_policy"] = validators.join_policy(str(values["join_policy"]))
        if "listed" in values:
            changes["listed"] = bool(values["listed"])
        if not changes:
            raise ValidationError(t("바꿀 것이 없습니다."))
        if "description" in changes and changes["description"] != p.description:
            self.directory.set_project_description(p.cn, changes["description"])
            p = self.directory.get_project(p.cn)
        rec = self.store.update(p.cn, **changes)
        audit.record(actor.uid, "project_update", p.cn, True, ip, ",".join(changes))
        return self._view(actor, p, rec)

    def archive(self, actor: Actor, cn: str, ip: str) -> View:
        p, rec = self._manage(actor, cn)
        rec = self.store.set_archived(p.cn, True)
        audit.record(actor.uid, "project_archive", p.cn, True, ip)
        return self._view(actor, p, rec)

    def restore(self, actor: Actor, cn: str, ip: str) -> View:
        p, rec = self._manage(actor, cn, live=False)
        if not rec.archived:
            raise ValidationError(t("보관된 프로젝트가 아닙니다."))
        rec = self.store.set_archived(p.cn, False)
        audit.record(actor.uid, "project_restore", p.cn, True, ip)
        return self._view(actor, p, rec)

    # ── members and owners ───────────────────────────────────────────────

    def _add(self, by: str, p: Project, uid: str, ip: str, how: str) -> Project:
        self.directory.set_project_member(p.cn, uid, True)
        self.store.request_delete(p.cn, uid)  # a request this answers
        audit.record(by, "project_member_add", p.cn, True, ip, f"{uid} {how}")
        return self.directory.get_project(p.cn)

    def _remove(self, by: str, p: Project, rec: Record, uid: str, ip: str, how: str) -> Project:
        if uid not in p.members:
            raise ValidationError(t("{uid}은(는) 구성원이 아닙니다.", uid=uid))
        if uid in rec.owners and len(rec.owners) == 1:
            raise Forbidden(t("마지막 소유자는 뺄 수 없습니다. 먼저 다른 소유자를 두세요."))
        self.directory.set_project_member(p.cn, uid, False)
        self.store.set_owner(p.cn, uid, False)
        audit.record(by, "project_member_remove", p.cn, True, ip, f"{uid} {how}")
        return self.directory.get_project(p.cn)

    def add_member(self, actor: Actor, cn: str, uid: str, ip: str) -> View:
        p, rec = self._manage(actor, cn)
        user = self._user(uid)
        if user.uid in p.members:
            raise ValidationError(t("{uid}은(는) 이미 구성원입니다.", uid=user.uid))
        p = self._add(actor.uid, p, user.uid, ip, "added")
        return self._view(actor, p, rec)

    def remove_member(self, actor: Actor, cn: str, uid: str, ip: str) -> View:
        p, rec = self._manage(actor, cn)
        try:
            uid = validators.uid(uid)
        except ValidationError as e:
            raise Forbidden(str(e)) from e
        p = self._remove(actor.uid, p, rec, uid, ip, "removed")
        return self._view(actor, p, self.store.get(p.cn))  # type: ignore[arg-type]

    def leave(self, actor: Actor, cn: str, ip: str) -> View:
        p, rec = self._load(cn)
        if actor.uid not in p.members:
            raise Forbidden(t("이 프로젝트의 구성원이 아닙니다."))
        if actor.uid in rec.owners and len(rec.owners) == 1:
            raise Forbidden(t("마지막 소유자는 나갈 수 없습니다. 먼저 다른 소유자를 두거나 프로젝트를 보관하세요."))
        p = self._remove(actor.uid, p, rec, actor.uid, ip, "left")
        return self._view(actor, p, self.store.get(p.cn))  # type: ignore[arg-type]

    def set_owner(self, actor: Actor, cn: str, uid: str, owner: bool, ip: str) -> View:
        p, rec = self._manage(actor, cn)
        try:
            uid = validators.uid(uid)
        except ValidationError as e:
            raise Forbidden(str(e)) from e
        if uid not in p.members:
            raise ValidationError(t("{uid}은(는) 구성원이 아닙니다.", uid=uid))
        if not owner and uid in rec.owners and len(rec.owners) == 1:
            raise Forbidden(t("마지막 소유자는 해임할 수 없습니다. 먼저 다른 소유자를 두세요."))
        self.store.set_owner(p.cn, uid, owner)
        audit.record(actor.uid, "project_owner_add" if owner else "project_owner_remove", p.cn, True, ip, uid)
        return self._view(actor, p, self.store.get(p.cn))  # type: ignore[arg-type]

    # ── joining ──────────────────────────────────────────────────────────

    def join(self, actor: Actor, cn: str, note: str, ip: str) -> View:
        """By the project's policy: in at once (open), a request for an owner (request), or refused
        (invite: a link alone opens it)."""
        p, rec = self._load(cn)
        if rec.archived:
            raise Forbidden(t("보관된 프로젝트에는 들어갈 수 없습니다."))
        if actor.uid in p.members:
            raise ValidationError(t("이미 이 프로젝트의 구성원입니다."))
        if rec.join_policy == "open":
            p = self._add(actor.uid, p, actor.uid, ip, "joined")
        elif rec.join_policy == "request":
            if self.store.requested(p.cn, actor.uid):
                raise ValidationError(t("이미 가입을 신청했습니다. 소유자의 답을 기다리세요."))
            self.store.request_add(p.cn, actor.uid, " ".join(note.split())[:200])
            audit.record(actor.uid, "project_request", p.cn, True, ip)
        else:
            raise Forbidden(t("초대 링크로만 들어갈 수 있는 프로젝트입니다."))
        return self._view(actor, p, rec)

    def withdraw(self, actor: Actor, cn: str, ip: str) -> View:
        p, rec = self._load(cn)
        if not self.store.request_delete(p.cn, actor.uid):
            raise ValidationError(t("기다리는 가입 신청이 없습니다."))
        audit.record(actor.uid, "project_request_withdraw", p.cn, True, ip)
        return self._view(actor, p, rec)

    def requests(self, actor: Actor, cn: str) -> list[JoinRequest]:
        p, _ = self._manage(actor, cn, live=False)
        return self.store.requests(p.cn)

    def approve(self, actor: Actor, cn: str, rid: str, ip: str) -> View:
        p, rec = self._manage(actor, cn)
        r = self.store.request(p.cn, rid[:32])
        if r is None:
            raise Forbidden(t("그 신청은 더 이상 없습니다."))
        user = self._user(r.uid)
        p = self._add(actor.uid, p, user.uid, ip, "approved")
        return self._view(actor, p, rec)

    def reject(self, actor: Actor, cn: str, rid: str, ip: str) -> View:
        p, rec = self._manage(actor, cn)
        r = self.store.request(p.cn, rid[:32])
        if r is None:
            raise Forbidden(t("그 신청은 더 이상 없습니다."))
        self.store.request_delete(p.cn, r.uid)
        audit.record(actor.uid, "project_reject", p.cn, True, ip, r.uid)
        return self._view(actor, p, rec)

    def invites(self, actor: Actor, cn: str) -> list[ProjectInvite]:
        p, _ = self._manage(actor, cn, live=False)
        return self.store.invites(p.cn)

    def invite(self, actor: Actor, cn: str, note: str, ip: str) -> tuple[ProjectInvite, str]:
        """A link that puts whoever opens it (signed in) into the project; its token is shown once."""
        p, _ = self._manage(actor, cn)
        note = " ".join(note.split())[:120]
        inv, token = self.store.invite_create(p.cn, actor.uid, note)
        audit.record(actor.uid, "project_invite", p.cn, True, ip, f"id={inv.id}" + (f" {note}" if note else ""))
        return inv, token

    def revoke_invite(self, actor: Actor, cn: str, iid: str, ip: str) -> bool:
        p, _ = self._manage(actor, cn, live=False)
        gone = self.store.invite_revoke(p.cn, iid[:32])
        if gone:
            audit.record(actor.uid, "project_invite_revoke", p.cn, True, ip, f"id={iid[:32]}")
        return gone

    def join_by_invite(self, actor: Actor, token: str, ip: str) -> View:
        """The link's holder, signed in, becomes a member. The link is used up by that; it stays usable
        when nothing happened (already a member, the project archived, the directory failing)."""
        inv = self.store.invite_claim(token[:64])
        if inv is None:
            raise Forbidden(t("그 초대 링크는 더 이상 쓸 수 없습니다 (쓰였거나, 거둬졌거나, 기한이 지났습니다)."))
        try:
            p, rec = self._load(inv.cn)
            if rec.archived:
                raise Forbidden(t("보관된 프로젝트에는 들어갈 수 없습니다."))
            if actor.uid in p.members:
                raise ValidationError(t("이미 이 프로젝트의 구성원입니다."))
            p = self._add(actor.uid, p, actor.uid, ip, f"invited by {inv.created_by} id={inv.id}")
        except (Forbidden, ValidationError, DirectoryError):
            self.store.invite_restore(inv)
            raise
        return self._view(actor, p, rec)
