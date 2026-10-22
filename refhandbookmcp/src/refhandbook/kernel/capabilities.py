"""Capabilities: what a store can do, kept as versioned records that the model maintains itself.

A capability is anything added to what the system does: a script, a sandbox policy, a layer, a rule,
a card, an alias for a command. Every kind has the same shape and the same life:

    cap:<kind>:<name>     a kernel node: state, owner (its author), the version in force, TTL
    k_cap_versions        every version, immutable: spec (JSON), body (text), author, note

    proposed ──approve──▶ active ──deprecate──▶ deprecated ──grace──▶ retired ──retention──▶ purged
                            ▲                                            │
                            └──────────────────── restore ───────────────┘

One rule set for every kind:

  - The owner (the actor that created a record) changes it. The model changes only its own records;
    the user's and the kernel's are not the model's to edit (it adds its own under another name).
  - A version the model writes that widens a grant (each kind says what widens: more commands, the
    network, a mount, a larger limit) waits for the user's approval; the version in force stays in
    force meanwhile. Every other version takes effect at once: no approval per script or per edit.
  - Every record has a TTL. When `review_after` passes, the sweep runs the kind's check on the
    version in force: a pass renews the TTL (the record updates itself), a failure deprecates it with
    the reason and counts a review signal. A deprecated record still works and warns, naming what
    replaces it; after its grace it retires (no longer in force, history kept). A retired record is
    purged after RETENTION. A proposal nobody approves expires the same way.

Kinds are registered by packages (register()); the kernel knows none by name. What a kind does when
a version comes into force (apply) or goes out of it (unapply) is the kind's: the sandbox writes the
policy and script nodes its runner reads, the rule kind defines the kernel rule, and so on.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from .graph import Forbidden, Graph, KernelError

DAY = 86400.0
RETENTION = 90 * DAY
STATES = {"proposed": ["live"], "active": ["live"], "deprecated": ["live"], "retired": ["finished"]}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SWEEP_EVERY = 60.0


class CapError(KernelError):
    pass


class Kind:
    """A kind of capability. Subclasses override what differs; the defaults suit a plain record."""

    name = ""
    description = ""
    ttl = 30 * DAY  # between reviews
    grace = 14 * DAY  # deprecated → retired, and proposed → expired
    has_body = False

    def validate(self, reg: Registry, name: str, spec: dict[str, Any], body: str | None) -> dict[str, Any]:
        return spec

    def widens(self, reg: Registry, old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
        """Why `new` grants more than `old` (None: nothing in force yet). Empty: it does not."""
        return []

    def apply(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> None:
        pass

    def unapply(self, reg: Registry, rec: dict[str, Any]) -> None:
        pass

    def check(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> tuple[str, str]:
        """("pass" | "fail" | "pending", detail) for the version in force."""
        return "pass", ""

    def repair(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any], detail: str) -> dict[str, Any] | None:
        """A spec that fixes a failed check, for the kernel's own records (they update themselves);
        None: the failure deprecates the record and its owner answers it."""
        return None

    def summary(self, spec: dict[str, Any]) -> str:
        return spec.get("description", "")

    def report(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> str:
        """What the writer should read after a version comes into force (a rule's trial findings)."""
        return ""


KINDS: dict[str, Kind] = {}


def register(kind: Kind) -> Kind:
    KINDS[kind.name] = kind
    return kind


SCHEMA = """
CREATE TABLE IF NOT EXISTS k_cap_versions (
    cap TEXT NOT NULL, version INTEGER NOT NULL, spec TEXT NOT NULL, body TEXT,
    author TEXT NOT NULL, created REAL NOT NULL, note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (cap, version)
);
"""


def install(g: Graph) -> None:
    if g.db.execute("SELECT value FROM k_meta WHERE key = 'pkg:cap'").fetchone() == ("1",):
        return
    with g.tx():
        g.db.execute(SCHEMA)
        g.define_type("cap", "node", actor="kernel", pkg="cap", states=STATES,
                      description="A capability record: a versioned script, policy, layer, rule, card or alias.")
        g.db.execute("INSERT OR REPLACE INTO k_meta VALUES ('pkg:cap', '1')")


def _cid(kind: str, name: str) -> str:
    return f"cap:{kind}:{name}"


class Registry:
    """The capability records of one store. `ctx` carries what kinds need (the workspace, the
    handbook); every method expects the caller to serialize access to the store's connection."""

    def __init__(self, g: Graph, ctx: dict[str, Any] | None = None):
        self.g = g
        self.ctx = ctx or {}
        install(g)

    # ── reading ──────────────────────────────────────────────────────────

    def kind(self, kind: str) -> Kind:
        k = KINDS.get(kind)
        if k is None:
            raise CapError(f"no kind {kind!r}; kinds: {', '.join(sorted(KINDS))}")
        return k

    def find(self, kind: str, name: str) -> dict[str, Any] | None:
        return self.g.get_node(_cid(kind, name))

    def get(self, kind: str, name: str) -> dict[str, Any]:
        rec = self.find(kind, name)
        if rec is None:
            names = [r["attrs"]["name"] for r in self.list(kind)]
            raise CapError(f"no {kind} {name!r}; {kind}s: {', '.join(names) or 'none'}")
        return rec

    def list(self, kind: str | None = None, states: tuple[str, ...] = ("proposed", "active", "deprecated")) \
            -> list[dict[str, Any]]:
        sql = "SELECT id FROM k_nodes WHERE type = 'cap'" + (" AND id LIKE ?" if kind else "") + " ORDER BY id"
        rows = self.g.db.execute(sql, (f"cap:{kind}:%",) if kind else ()).fetchall()
        return [n for n in (self.g.node(r[0]) for r in rows) if n["state"] in states]

    def version(self, rec: dict[str, Any], v: int | None = None) -> dict[str, Any]:
        v = rec["attrs"].get("version") if v is None else v
        r = self.g.db.execute("SELECT * FROM k_cap_versions WHERE cap = ? AND version = ?", (rec["id"], v)).fetchone()
        if r is None:
            raise CapError(f"{rec['id']} has no version {v}")
        d = dict(r)
        d["spec"] = json.loads(d["spec"])
        return d

    def history(self, kind: str, name: str) -> list[dict[str, Any]]:
        rec = self.get(kind, name)
        return [self.version(rec, r[0]) for r in
                self.g.db.execute("SELECT version FROM k_cap_versions WHERE cap = ? ORDER BY version", (rec["id"],))]

    def in_force(self, kind: str, name: str) -> tuple[dict[str, Any], dict[str, Any], str]:
        """(record, version in force, warning) for something about to be used: refused when proposed
        or retired; a deprecated one is used with its warning."""
        rec = self.get(kind, name)
        a = rec["attrs"]
        if rec["state"] == "retired" or not a.get("version"):
            why = f" ({a['reason']})" if a.get("reason") else ""
            raise CapError(f"{kind} {name!r} is {'retired' if rec['state'] == 'retired' else 'not approved yet'}{why}"
                           + (f"; use {a['replaced_by']}" if a.get("replaced_by") else ""))
        warn = ""
        if rec["state"] == "deprecated":
            warn = (f"DEPRECATED {kind} {name}: {a.get('reason') or 'no reason given'}"
                    + (f"; use {a['replaced_by']}" if a.get("replaced_by") else "")
                    + f"; retires {time.strftime('%Y-%m-%d', time.localtime(a.get('retire_at', 0)))}")
        return rec, self.version(rec), warn

    # ── writing ──────────────────────────────────────────────────────────

    @staticmethod
    def _may(rec: dict[str, Any], actor: str) -> None:
        if actor == "model" and rec["author"] != "model":
            raise Forbidden(f"{rec['id']} is the {rec['author']}'s: the model changes only its own records "
                            "(add yours under another name)")

    def _store(self, cid: str, v: int, spec: dict[str, Any], body: str | None, actor: str, note: str) -> dict[str, Any]:
        self.g.db.execute("INSERT INTO k_cap_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (cid, v, json.dumps(spec, ensure_ascii=False, sort_keys=True), body, actor, time.time(), note))
        return self.version(self.g.node(cid), v)

    def _put(self, rec: dict[str, Any], ver: dict[str, Any], actor: str) -> dict[str, Any]:
        """Bring `ver` into force: the kind applies it, the record names it, the TTL starts over."""
        k = self.kind(rec["attrs"]["kind"])
        k.apply(self, rec, ver)
        now = time.time()
        ttl = rec["attrs"].get("ttl", k.ttl)
        # a new version in force is active: for a deprecated record it is the owner's answer
        return self.g.update_node(rec["id"], actor="kernel", state="active", attrs={
            "version": ver["version"], "pending": None, "applied": now, "review_after": now + ttl if ttl else None,
            "reason": None, "replaced_by": None, "retire_at": None, "retired_at": None, "checking": None})

    def add(self, kind: str, name: str, *, spec: dict[str, Any] | None = None, body: str | None = None,
            actor: str, note: str = "", ttl: float | None = None) -> tuple[dict[str, Any], str]:
        k = self.kind(kind)
        if not NAME_RE.match(name or ""):
            raise CapError(f"{kind} name {name!r}: lowercase letters, digits, . _ - (up to 64)")
        if self.find(kind, name) is not None:
            raise CapError(f"{kind} {name!r} exists: update it (or restore it)")
        spec = k.validate(self, name, dict(spec or {}), self._body(k, body))
        cid = _cid(kind, name)
        with self.g.tx():
            self.g.put_node(cid, "cap", actor=actor, state="proposed", content=k.summary(spec),
                            attrs={"kind": kind, "name": name, "version": 0, "ttl": k.ttl if ttl is None else ttl,
                                   "created": time.time()})
            ver = self._store(cid, 1, spec, body, actor, note)
            rec = self.g.node(cid)
            wide = k.widens(self, None, spec) if actor == "model" else []
            if wide:
                rec = self.g.update_node(cid, actor="kernel", attrs={"pending": 1, "retire_at": time.time() + k.grace})
                self.g.log(actor, f"{kind} {name} v1 proposed: {'; '.join(wide)}", cid)
                return rec, f"{kind} {name} v1 PROPOSED (waits for the user's approval: {'; '.join(wide)})"
            rec = self._put(rec, ver, actor)
            self.g.log(actor, f"{kind} {name} v1 added", cid)
            extra = k.report(self, rec, ver)
            return rec, f"{kind} {name} v1 added" + (f"\n{extra}" if extra else "")

    @staticmethod
    def _body(k: Kind, body: str | None) -> str | None:
        if k.has_body and not (body or "").strip():
            raise CapError(f"a {k.name} needs a body")
        if not k.has_body and body:
            raise CapError(f"a {k.name} has no body; put everything in spec")
        return body

    def update(self, kind: str, name: str, *, spec: dict[str, Any] | None = None, body: str | None = None,
               actor: str, note: str = "", replace: bool = False) -> tuple[dict[str, Any], str]:
        """A new version: `spec` merges into the latest version's (a key set to None is removed;
        replace=True takes it whole), `body` replaces the body (None keeps it)."""
        k = self.kind(kind)
        rec = self.get(kind, name)
        self._may(rec, actor)
        last = self.g.db.execute("SELECT max(version) FROM k_cap_versions WHERE cap = ?", (rec["id"],)).fetchone()[0]
        base = self.version(rec, last)
        new = dict(spec or {}) if replace else {**base["spec"], **(spec or {})}
        new = {a: b for a, b in new.items() if b is not None}
        body = base["body"] if body is None else body
        new = k.validate(self, name, new, self._body(k, body))
        if new == base["spec"] and body == base["body"] and last == rec["attrs"].get("version") \
                and rec["state"] == "active":
            return rec, f"{kind} {name} v{last}: unchanged"
        current = self.version(rec) if rec["attrs"].get("version") else None
        with self.g.tx():
            ver = self._store(rec["id"], last + 1, new, body, actor, note)
            self.g.update_node(rec["id"], actor="kernel", content=k.summary(new))
            rec = self.g.node(rec["id"])
            wide = k.widens(self, current["spec"] if current else None, new) if actor == "model" else []
            if wide:
                rec = self.g.update_node(rec["id"], actor="kernel", attrs={"pending": ver["version"]})
                self.g.log(actor, f"{kind} {name} v{ver['version']} proposed: {'; '.join(wide)}", rec["id"])
                keep = f"v{current['version']} stays in force meanwhile" if current else "nothing is in force meanwhile"
                return rec, (f"{kind} {name} v{ver['version']} PROPOSED (waits for the user's approval: "
                             f"{'; '.join(wide)}); {keep}")
            rec = self._put(rec, ver, actor)
            self.g.log(actor, f"{kind} {name} v{ver['version']}" + (f": {note}" if note else ""), rec["id"])
            extra = k.report(self, rec, ver)
            return rec, f"{kind} {name} v{ver['version']} in force" + (f"\n{extra}" if extra else "")

    def approve(self, kind: str, name: str, version: int, *, actor: str) -> str:
        if actor != "user":
            raise Forbidden("only the user approves a grant (the approval page, or the server's terminal)")
        rec = self.get(kind, name)
        if rec["attrs"].get("pending") != version:
            raise CapError(f"{kind} {name}: v{version} is not the version waiting (now "
                           f"{rec['attrs'].get('pending') or 'none'}); review it again")
        with self.g.tx():
            self._put(rec, self.version(rec, version), actor)
            self.g.log(actor, f"{kind} {name} v{version} approved", rec["id"])
        return f"{kind} {name} v{version} approved"

    def reject(self, kind: str, name: str, version: int, *, actor: str) -> str:
        if actor != "user":
            raise Forbidden("only the user rejects a grant")
        rec = self.get(kind, name)
        if rec["attrs"].get("pending") != version:
            raise CapError(f"{kind} {name}: v{version} is not the version waiting")
        with self.g.tx():
            if rec["attrs"].get("version"):
                self.g.update_node(rec["id"], actor="kernel", attrs={"pending": None})
            else:
                self.g.update_node(rec["id"], actor="kernel", state="retired",
                                   attrs={"pending": None, "reason": "rejected by the user", "retired_at": time.time()})
            self.g.log(actor, f"{kind} {name} v{version} rejected", rec["id"])
        return f"{kind} {name} v{version} rejected"

    def deprecate(self, kind: str, name: str, *, actor: str, why: str, replaced_by: str = "") -> str:
        if not why.strip():
            raise CapError("deprecating needs a why")
        rec = self.get(kind, name)
        self._may(rec, actor)
        if rec["state"] != "active":
            raise CapError(f"{kind} {name} is {rec['state']}, not active")
        if replaced_by:
            rk, _, rn = replaced_by.partition(":") if ":" in replaced_by else (kind, "", replaced_by)
            self.get(rk, rn)
        grace = self.kind(kind).grace
        self.g.update_node(rec["id"], actor="kernel", state="deprecated",
                           attrs={"reason": why.strip(), "replaced_by": replaced_by or None,
                                  "retire_at": time.time() + grace})
        self.g.log(actor, f"{kind} {name} deprecated: {why.strip()}" + (f" → {replaced_by}" if replaced_by else ""),
                   rec["id"])
        return f"{kind} {name} deprecated (still works, with a warning; retires in {grace / DAY:g} days)"

    def remove(self, kind: str, name: str, *, actor: str, why: str = "") -> str:
        rec = self.get(kind, name)
        self._may(rec, actor)
        if rec["state"] == "retired":
            return f"{kind} {name} is already retired"
        self._retire(rec, why.strip() or f"removed by the {actor}", actor)
        return f"{kind} {name} retired (its history is kept; restore brings it back)"

    def _retire(self, rec: dict[str, Any], why: str, actor: str) -> None:
        with self.g.tx():
            if rec["attrs"].get("version"):
                self.kind(rec["attrs"]["kind"]).unapply(self, rec)
            self.g.update_node(rec["id"], actor="kernel", state="retired",
                               attrs={"reason": why, "retired_at": time.time(), "pending": None})
            self.g.log(actor, f"{rec['attrs']['kind']} {rec['attrs']['name']} retired: {why}", rec["id"])

    def restore(self, kind: str, name: str, *, actor: str, version: int | None = None) -> tuple[dict[str, Any], str]:
        """Bring a retired or deprecated record back, at its last version or at `version` (as a new
        version with that content: history is never rewritten)."""
        rec = self.get(kind, name)
        self._may(rec, actor)
        last = self.g.db.execute("SELECT max(version) FROM k_cap_versions WHERE cap = ?", (rec["id"],)).fetchone()[0]
        old = self.version(rec, version or rec["attrs"].get("version") or last)
        if rec["state"] == "retired":
            with self.g.tx():
                self.g.update_node(rec["id"], actor="kernel", state="proposed", attrs={"version": 0})
                rec = self.g.node(rec["id"])
        return self.update(kind, name, spec=old["spec"], body=old["body"], actor=actor, replace=True,
                           note=f"restored from v{old['version']}")

    # ── the TTL sweep ────────────────────────────────────────────────────

    def due(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        last = self.g.db.execute("SELECT value FROM k_meta WHERE key = 'cap:swept'").fetchone()
        return last is None or now - float(last[0]) >= SWEEP_EVERY

    def sweep(self, now: float | None = None, force: bool = False) -> list[str]:
        """Review what is due: renew, deprecate, retire, expire, purge. Returns what happened."""
        now = time.time() if now is None else now
        if not force and not self.due(now):
            return []
        events: list[str] = []
        with self.g.tx():
            self.g.db.execute("INSERT OR REPLACE INTO k_meta VALUES ('cap:swept', ?)", (repr(now),))
        for rec in self.list(states=("proposed", "active", "deprecated", "retired")):
            a, kind = rec["attrs"], rec["attrs"]["kind"]
            if kind not in KINDS:
                continue  # a package that is not loaded in this process
            label = f"{kind} {a['name']}"
            try:
                if rec["state"] == "retired":
                    if now - (a.get("retired_at") or now) > RETENTION:
                        with self.g.tx():
                            self.g.db.execute("DELETE FROM k_cap_versions WHERE cap = ?", (rec["id"],))
                            self.g.delete_node(rec["id"], actor="kernel")
                            self.g.log("kernel", f"{label} purged after retention", rec["id"])
                        events.append(f"{label}: purged")
                    continue
                if a.get("retire_at") and now >= a["retire_at"] and (rec["state"] == "deprecated" or not a.get("version")):
                    self._retire(rec, a.get("reason") or "not approved in time", "kernel")
                    events.append(f"{label}: retired ({a.get('reason') or 'not approved in time'})")
                    continue
                if rec["state"] == "active" and a.get("version") and a.get("review_after") and now >= a["review_after"]:
                    events += self._review(rec, now)
            except KernelError as e:  # one record's trouble never stops the sweep
                events.append(f"{label}: sweep error: {e}")
        return events

    def _review(self, rec: dict[str, Any], now: float) -> list[str]:
        k = self.kind(rec["attrs"]["kind"])
        label = f"{k.name} {rec['attrs']['name']}"
        verdict, detail = k.check(self, rec, self.version(rec))
        if verdict == "pending":
            return []
        if verdict == "pass":
            ttl = rec["attrs"].get("ttl", k.ttl)
            self.g.update_node(rec["id"], actor="kernel", attrs={"review_after": now + ttl, "reviewed": now,
                                                                 "checking": None})
            self.g.log("kernel", f"{label} reviewed: renewed" + (f" ({detail})" if detail else ""), rec["id"])
            return [f"{label}: renewed"]
        if rec["author"] == "kernel":
            fix = k.repair(self, rec, self.version(rec), detail)
            if fix is not None:
                self.update(k.name, rec["attrs"]["name"], spec=fix, actor="kernel", replace=True,
                            note=f"repaired after its review: {detail}")
                return [f"{label}: repaired ({detail})"]
        with self.g.tx():
            self.g.update_node(rec["id"], actor="kernel", state="deprecated",
                               attrs={"reason": f"failed its review: {detail}", "retire_at": now + k.grace,
                                      "checking": None, "reviewed": now})
            self.g.log("kernel", f"review signal: {label} failed its check: {detail}", rec["id"])
            n = int((self.g.db.execute("SELECT value FROM k_meta WHERE key = 'cap:signals'").fetchone() or ["0"])[0])
            self.g.db.execute("INSERT OR REPLACE INTO k_meta VALUES ('cap:signals', ?)", (str(n + 1),))
        return [f"{label}: deprecated (failed its review: {detail})"]

    def review_now(self, kind: str, name: str) -> str:
        """Run the record's check at once (the TTL starts over on a pass)."""
        rec = self.get(kind, name)
        if rec["state"] != "active" or not rec["attrs"].get("version"):
            raise CapError(f"{kind} {name} is {rec['state']}: only an active record is reviewed")
        out = self._review(rec, time.time())
        if not out:
            return f"{kind} {name}: its check is running; the next sweep (or review again) reads it"
        return out[0]
