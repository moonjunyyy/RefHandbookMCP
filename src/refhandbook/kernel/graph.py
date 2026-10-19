"""The kernel graph.

Everything above the kernel is a row here: node and edge types, the states a node type may be in
and the classes those states belong to, who may make which transition, the rules that gate scopes,
and a log. The kernel itself fixes only this schema, the rule evaluator, the gate checks and the
authority model:

    authority  kernel   — defined by code; changed by a release
               sealed   — the user's (or a package the user installed); only the user changes it
               proposed — written by the model; usable, but a proposed rule never blocks

    actor      kernel | user | model   — who is making a write. The server decides this: a call that
               arrives as a model tool call is `model`; `user` comes only from a channel the model
               cannot drive (the approval page).
"""

from __future__ import annotations

import itertools
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Iterable

from ..store import HandbookError

ACTORS = ("kernel", "user", "model")
AUTHORITIES = ("kernel", "sealed", "proposed")
KINDS = ("node", "edge", "scope")
PHASES = ("derive", "pre", "obligation", "close", "check")
SEVERITIES = ("block", "warn", "info")
SCOPE_STATES = {"open": ("live",), "closed": ("finished",)}
CONTAINS, CARRY, TOUCHED, MISSING = "contains", "carry", "touched", "missing"

SCHEMA = """
CREATE TABLE IF NOT EXISTS k_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS k_types (
    name        TEXT PRIMARY KEY,
    kind        TEXT NOT NULL CHECK (kind IN ('node', 'edge', 'scope')),
    inverse     TEXT,
    binding     TEXT,
    description TEXT NOT NULL DEFAULT '',
    pkg         TEXT NOT NULL DEFAULT '',
    authority   TEXT NOT NULL DEFAULT 'sealed' CHECK (authority IN ('kernel', 'sealed', 'proposed')),
    origin      TEXT NOT NULL DEFAULT 'kernel'
);
CREATE TABLE IF NOT EXISTS k_type_class (
    type  TEXT NOT NULL REFERENCES k_types(name) ON DELETE CASCADE,
    class TEXT NOT NULL,
    PRIMARY KEY (type, class)
);
CREATE TABLE IF NOT EXISTS k_states (
    type        TEXT NOT NULL REFERENCES k_types(name) ON DELETE CASCADE,
    state       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (type, state)
);
CREATE TABLE IF NOT EXISTS k_state_class (
    type  TEXT NOT NULL,
    state TEXT NOT NULL,
    class TEXT NOT NULL,
    PRIMARY KEY (type, state, class),
    FOREIGN KEY (type, state) REFERENCES k_states(type, state) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS k_transitions (
    type TEXT NOT NULL REFERENCES k_types(name) ON DELETE CASCADE,
    src  TEXT NOT NULL,           -- a state, or '*'
    dst  TEXT NOT NULL,
    who  TEXT NOT NULL CHECK (who IN ('kernel', 'user', 'model', 'any')),
    PRIMARY KEY (type, src, dst, who)
);
CREATE TABLE IF NOT EXISTS k_nodes (
    id      TEXT PRIMARY KEY,
    type    TEXT NOT NULL REFERENCES k_types(name),
    state   TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    attrs   TEXT NOT NULL DEFAULT '{}',
    origin  TEXT NOT NULL DEFAULT 'kernel',
    author  TEXT NOT NULL DEFAULT 'kernel' CHECK (author IN ('kernel', 'user', 'model')),
    version INTEGER NOT NULL DEFAULT 1,
    created INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS k_nodes_type ON k_nodes(type, state);
CREATE TABLE IF NOT EXISTS k_edges (
    src    TEXT NOT NULL REFERENCES k_nodes(id) ON DELETE CASCADE,
    type   TEXT NOT NULL REFERENCES k_types(name),
    dst    TEXT NOT NULL REFERENCES k_nodes(id) ON DELETE CASCADE,
    attrs  TEXT NOT NULL DEFAULT '{}',
    origin TEXT NOT NULL DEFAULT 'kernel',
    clock  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (src, type, dst)
);
CREATE INDEX IF NOT EXISTS k_edges_dst ON k_edges(dst, type);
CREATE INDEX IF NOT EXISTS k_edges_type ON k_edges(type);
CREATE TABLE IF NOT EXISTS k_rules (
    id         TEXT PRIMARY KEY,
    phase      TEXT NOT NULL CHECK (phase IN ('derive', 'pre', 'obligation', 'close', 'check')),
    applies_to TEXT NOT NULL DEFAULT '*',
    severity   TEXT NOT NULL DEFAULT 'block' CHECK (severity IN ('block', 'warn', 'info')),
    body       TEXT NOT NULL,
    message    TEXT NOT NULL DEFAULT '',
    pkg        TEXT NOT NULL DEFAULT '',
    authority  TEXT NOT NULL DEFAULT 'sealed' CHECK (authority IN ('kernel', 'sealed', 'proposed')),
    origin     TEXT NOT NULL DEFAULT 'kernel',
    state      TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'retired')),
    version    INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS k_log (
    seq   INTEGER PRIMARY KEY AUTOINCREMENT,
    clock INTEGER NOT NULL,
    actor TEXT NOT NULL,
    event TEXT NOT NULL,
    ref   TEXT NOT NULL DEFAULT '',
    meta  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS k_log_ref ON k_log(ref, seq);
"""

ID_RE = re.compile(r"^[\w.:@#/+-]{1,200}$")
NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def encode_type(prefix: str, raw: str) -> str:
    """A legacy relation name as an edge type name in its own namespace, reversibly: `<prefix>_name`
    when the name is plain lowercase, else `<prefix>x_<hex of its UTF-8>`."""
    plain = f"{prefix}_{raw}"
    return plain if NAME_RE.match(plain) and not raw.startswith("x_") else f"{prefix}x_{raw.encode().hex()}"


def decode_type(prefix: str, name: str) -> str:
    if name.startswith(f"{prefix}x_"):
        return bytes.fromhex(name[len(prefix) + 2:]).decode()
    return name[len(prefix) + 1:]


class KernelError(HandbookError):
    """A request the caller can fix. Its text says what to do."""


class Conflict(KernelError):
    """A compare-and-swap failed: the node changed since the caller read it."""


class Forbidden(KernelError):
    """The actor may not make this change (authority or transition)."""


def _regexp(pattern: str, value: Any) -> int:
    if value is None:
        return 0
    return 1 if _compiled(pattern).search(str(value)) else 0


_PATTERNS: dict[str, re.Pattern[str]] = {}


def _compiled(pattern: str) -> re.Pattern[str]:
    p = _PATTERNS.get(pattern)
    if p is None:
        p = _PATTERNS[pattern] = re.compile(pattern)
    return p


def _check_actor(actor: str) -> None:
    if actor not in ACTORS:
        raise KernelError(f"actor must be one of {ACTORS}, not {actor!r}")


def authority_for(actor: str, requested: str | None = None) -> str:
    """The authority a new definition gets. The model can only propose."""
    _check_actor(actor)
    if actor == "model":
        return "proposed"
    if actor == "user":
        return "sealed" if requested in (None, "sealed", "kernel") else requested
    return requested or "sealed"


def may_change(actor: str, authority: str) -> bool:
    """Whether an actor may change or remove a definition with this authority."""
    if actor == "kernel":
        return True
    if authority == "kernel":
        return False
    if authority == "sealed":
        return actor == "user"
    return True  # proposed: the model may revise or withdraw its own proposals


class Graph:
    """One user's kernel graph on an SQLite connection. Not thread-safe by itself: the server
    holds one lock per store, so one call at a time touches this connection."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        # one statement at a time: executescript would first COMMIT a caller's open transaction
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                self.db.execute(stmt)
        self.db.create_function("rhb_regexp", 2, _regexp, deterministic=True)
        self.db.create_function("rhb_lower", 1, lambda v: v.lower() if isinstance(v, str) else v, deterministic=True)
        self._program_cache: tuple[Any, Any] | None = None
        with self.tx():
            self.db.execute("INSERT OR IGNORE INTO k_meta VALUES ('clock', '0')")
            self.db.execute("INSERT OR IGNORE INTO k_meta VALUES ('rules_rev', '0')")
            for name, inverse, desc in (
                (CONTAINS, "contained_in", "The source scope holds the target (a member, or an attached child scope)."),
                (CARRY, "carried_by", "The source scope defers the target, with a reason, instead of settling it."),
                (TOUCHED, "touched_by", "The source scope changed or addressed the target."),
            ):
                self.db.execute(
                    "INSERT OR IGNORE INTO k_types (name, kind, inverse, description, pkg, authority, origin)"
                    " VALUES (?, 'edge', ?, ?, 'kernel', 'kernel', 'kernel')", (name, inverse, desc))
            self.db.execute(
                "INSERT OR IGNORE INTO k_types (name, kind, description, pkg, authority, origin) VALUES"
                " (?, 'node', 'A reference to something that does not exist; kept so the reference is not lost.',"
                " 'kernel', 'kernel', 'kernel')", (MISSING,))

    # ── transactions ─────────────────────────────────────────────────────

    _savepoints = itertools.count(1)

    @contextmanager
    def tx(self) -> Iterator[None]:
        """One atomic unit of kernel work.

        Inside an open transaction it is a savepoint: its work commits or rolls back with the
        caller's transaction, and an error rolls back only this unit. With no transaction open it
        is the transaction (BEGIN … COMMIT). A caller that wants several kernel calls, or kernel
        and other writes, to be one transaction opens it first: `with g.transaction(): …`.
        (Python's sqlite3 opens its implicit transaction only at the first INSERT/UPDATE/DELETE,
        so `with db:` alone does not count as open until then.)"""
        if self.db.in_transaction:
            name = f"k_sp{next(self._savepoints)}"
            self.db.execute(f"SAVEPOINT {name}")
            try:
                yield
            except BaseException:
                self._undo(f"ROLLBACK TO {name}", f"RELEASE {name}")
                raise
            self.db.execute(f"RELEASE {name}")
        else:
            with self.transaction():
                yield

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """An outermost transaction (BEGIN … COMMIT, ROLLBACK on an error)."""
        if self.db.in_transaction:
            raise KernelError("a transaction is already open on this connection; use tx() inside it")
        self.db.execute("BEGIN")
        try:
            yield
        except BaseException:
            self._undo("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    @contextmanager
    def scratch(self) -> Iterator[None]:
        """Work that must leave nothing behind (rule evaluation's temp tables): always undone."""
        if self.db.in_transaction:
            name = f"k_sc{next(self._savepoints)}"
            self.db.execute(f"SAVEPOINT {name}")
            try:
                yield
            finally:
                self._undo(f"ROLLBACK TO {name}", f"RELEASE {name}")
        else:
            self.db.execute("BEGIN")
            try:
                yield
            finally:
                self._undo("ROLLBACK")

    def _undo(self, *stmts: str) -> None:
        """Roll back without masking the error that caused it: if SQLite already aborted the
        transaction, the savepoint is gone and there is nothing left to undo."""
        for st in stmts:
            try:
                self.db.execute(st)
            except sqlite3.OperationalError:
                if self.db.in_transaction:
                    raise
                return

    # ── clock and log ────────────────────────────────────────────────────

    def clock(self) -> int:
        return int(self.db.execute("SELECT value FROM k_meta WHERE key = 'clock'").fetchone()[0])

    def tick(self) -> int:
        self.db.execute("UPDATE k_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'clock'")
        return self.clock()

    def log(self, actor: str, event: str, ref: str = "", **meta: Any) -> None:
        self.db.execute("INSERT INTO k_log (clock, actor, event, ref, meta) VALUES (?, ?, ?, ?, ?)",
                        (self.clock(), actor, event, ref, json.dumps(meta, ensure_ascii=False)))

    def rules_rev(self) -> int:
        return int(self.db.execute("SELECT value FROM k_meta WHERE key = 'rules_rev'").fetchone()[0])

    def _bump_rules(self) -> None:
        self.db.execute("UPDATE k_meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'rules_rev'")

    # ── types ────────────────────────────────────────────────────────────

    def get_type(self, name: str) -> dict[str, Any] | None:
        r = self.db.execute("SELECT * FROM k_types WHERE name = ?", (name,)).fetchone()
        return dict(r) if r else None

    def define_type(
        self,
        name: str,
        kind: str,
        *,
        actor: str,
        inverse: str | None = None,
        binding: str | None = None,
        description: str = "",
        classes: Iterable[str] = (),
        states: dict[str, Iterable[str]] | None = None,
        transitions: Iterable[tuple[str, str, str]] = (),
        pkg: str = "",
        authority: str | None = None,
    ) -> dict[str, Any]:
        """Create or redefine a type. `states` maps each state to its classes; `transitions` lists
        (from, to, who) with from='*' for any state and who in kernel|user|model|any. A type with no
        transitions lets any actor move its nodes between declared states. Redefining replaces the
        type's classes, states and transitions whole."""
        _check_actor(actor)
        if not NAME_RE.match(name):
            raise KernelError(f"type name {name!r}: lowercase letters, digits and _ only")
        if kind not in KINDS:
            raise KernelError(f"kind must be one of {KINDS}")
        if kind == "edge" and states:
            raise KernelError("edge types have no states")
        old = self.get_type(name)
        if old:
            if old["kind"] != kind:
                raise KernelError(f"type {name!r} exists as {old['kind']}; a type never changes kind")
            if not may_change(actor, old["authority"]):
                raise Forbidden(f"type {name!r} is {old['authority']}: only "
                                f"{'a release' if old['authority'] == 'kernel' else 'the user'} can change it")
        auth = authority_for(actor, authority)
        st = dict(states or {})
        if kind == "scope":
            for s, cls in SCOPE_STATES.items():
                st.setdefault(s, cls)
        with self.tx():
            self.db.execute(
                "INSERT INTO k_types (name, kind, inverse, binding, description, pkg, authority, origin)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET inverse = excluded.inverse,"
                " binding = excluded.binding, description = excluded.description, pkg = excluded.pkg,"
                " authority = excluded.authority, origin = excluded.origin",
                (name, kind, inverse or (name if kind == "edge" else None), binding, description, pkg, auth, actor))
            self.db.execute("DELETE FROM k_type_class WHERE type = ?", (name,))
            self.db.executemany("INSERT INTO k_type_class VALUES (?, ?)", [(name, c) for c in dict.fromkeys(classes)])
            self.db.execute("DELETE FROM k_states WHERE type = ?", (name,))
            for s, cls in st.items():
                self.db.execute("INSERT INTO k_states (type, state) VALUES (?, ?)", (name, s))
                self.db.executemany("INSERT INTO k_state_class VALUES (?, ?, ?)",
                                    [(name, s, c) for c in dict.fromkeys(cls)])
            self.db.execute("DELETE FROM k_transitions WHERE type = ?", (name,))
            for src, dst, who in transitions:
                if who not in ACTORS + ("any",):
                    raise KernelError(f"transition who must be one of {ACTORS + ('any',)}")
                for s in (src, dst):
                    if s != "*" and s not in st:
                        raise KernelError(f"transition {src}->{dst}: {s!r} is not a state of {name!r}")
                self.db.execute("INSERT INTO k_transitions VALUES (?, ?, ?, ?)", (name, src, dst, who))
            self.log(actor, f"type {name} {'redefined' if old else 'defined'} ({auth})", name)
            self._bump_rules()  # rules read classes and states
        return self.get_type(name)  # type: ignore[return-value]

    def states(self, type_: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for r in self.db.execute("SELECT state FROM k_states WHERE type = ? ORDER BY state", (type_,)):
            out[r[0]] = []
        for r in self.db.execute("SELECT state, class FROM k_state_class WHERE type = ? ORDER BY class", (type_,)):
            out[r[0]].append(r[1])
        return out

    def _require_type(self, name: str, kinds: tuple[str, ...]) -> dict[str, Any]:
        t = self.get_type(name)
        if t is None:
            raise KernelError(f"no type {name!r}; define it first")
        if t["kind"] not in kinds:
            raise KernelError(f"type {name!r} is a {t['kind']} type, not {' or '.join(kinds)}")
        return t

    def _check_transition(self, type_: str, old: str | None, new: str, actor: str) -> None:
        if old == new:
            return
        rows = self.db.execute("SELECT src, dst, who FROM k_transitions WHERE type = ?", (type_,)).fetchall()
        if not rows or actor == "kernel":
            return
        for r in rows:
            if r["dst"] == new and r["src"] in ("*", old) and r["who"] in ("any", actor):
                return
        allowed = sorted({f"{r['src']}->{r['dst']} ({r['who']})" for r in rows if r["src"] in ("*", old)})
        raise Forbidden(f"{actor} may not move a {type_!r} from {old!r} to {new!r}; "
                        f"allowed from here: {', '.join(allowed) or 'none'}")

    @staticmethod
    def _check_write(actor: str, validate: bool, origin: str | None) -> None:
        """`origin` is the provenance a row claims (the model transcribes the user's words as
        origin 'user'); it cannot be verified over a tool call. `author`, set by the kernel from the
        actor, is what actually wrote the node, and rules can read it with author(Id, A)."""
        if not validate and actor != "kernel":
            raise Forbidden("only the kernel stores unvalidated data (an import)")

    # ── nodes ────────────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        r = self.db.execute("SELECT * FROM k_nodes WHERE id = ?", (node_id,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["attrs"] = json.loads(d["attrs"])
        return d

    def node(self, node_id: str) -> dict[str, Any]:
        n = self.get_node(node_id)
        if n is None:
            raise KernelError(f"no node {node_id!r}")
        return n

    def _put_node(
        self,
        node_id: str,
        type_: str,
        *,
        actor: str,
        state: str = "",
        content: str = "",
        attrs: dict[str, Any] | None = None,
        origin: str | None = None,
        validate: bool = True,
    ) -> dict[str, Any]:
        """Create a node. `validate=False` stores a state the type does not declare (an import keeps
        what it found; the rules then report it): the kernel's alone."""
        _check_actor(actor)
        self._check_write(actor, validate, origin)
        if not ID_RE.match(node_id):
            raise KernelError(f"bad node id {node_id!r}")
        t = self._require_type(type_, ("node", "scope"))
        if validate:
            declared = self.states(type_)
            if declared and state not in declared:
                raise KernelError(f"{state!r} is not a state of {type_!r}; one of {sorted(declared)}")
        if self.db.execute("SELECT 1 FROM k_nodes WHERE id = ?", (node_id,)).fetchone():
            raise KernelError(f"node {node_id!r} exists; update it instead")
        c = self.clock()
        if t["kind"] == "scope" and actor != "kernel":
            raise Forbidden("a scope is created with open_scope(), which applies its gates")
        self.db.execute(
            "INSERT INTO k_nodes (id, type, state, content, attrs, origin, author, version, created, updated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (node_id, t["name"], state, content, json.dumps(attrs or {}, ensure_ascii=False),
             origin if origin is not None else actor, actor, c, c))
        return self.node(node_id)

    def _update_node(
        self,
        node_id: str,
        *,
        actor: str,
        expect: int | None = None,
        state: str | None = None,
        content: str | None = None,
        attrs: dict[str, Any] | None = None,
        replace_attrs: bool = False,
        origin: str | None = None,
        validate: bool = True,
    ) -> dict[str, Any]:
        """Change a node. `expect` is the version the caller read: if the node moved on since, the
        write is refused (compare-and-swap). `attrs` merges into the stored attributes unless
        `replace_attrs`; a key set to None is removed."""
        _check_actor(actor)
        self._check_write(actor, validate, origin)
        n = self.node(node_id)
        if expect is not None and n["version"] != expect:
            raise Conflict(f"{node_id} is at version {n['version']}, not {expect}: re-read it, then write")
        new_state = n["state"] if state is None else state
        if state is not None and new_state != n["state"] and actor != "kernel" \
                and self._require_type(n["type"], ("node", "scope"))["kind"] == "scope":
            raise Forbidden(f"{node_id} is a scope: it opens and closes through its gates (close()), "
                            "not by a state write")
        if state is not None and validate:
            declared = self.states(n["type"])
            if declared and new_state not in declared:
                raise KernelError(f"{new_state!r} is not a state of {n['type']!r}; one of {sorted(declared)}")
            self._check_transition(n["type"], n["state"], new_state, actor)
        if replace_attrs:
            merged = dict(attrs or {})
        else:
            merged = dict(n["attrs"])
            for k, v in (attrs or {}).items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
        cur = self.db.execute(
            "UPDATE k_nodes SET state = ?, content = ?, attrs = ?, origin = ?, version = version + 1, updated = ?"
            " WHERE id = ? AND version = ?",  # the version read above: the write is a compare-and-swap
            (new_state, n["content"] if content is None else content, json.dumps(merged, ensure_ascii=False),
             n["origin"] if origin is None else origin, self.clock(), node_id, n["version"]))
        if cur.rowcount != 1:
            raise Conflict(f"{node_id} changed while it was being written (another session): re-read it, then write")
        return self.node(node_id)

    def _delete_node(self, node_id: str, *, actor: str, expect: int | None = None) -> None:
        _check_actor(actor)
        n = self.node(node_id)
        if expect is not None and n["version"] != expect:
            raise Conflict(f"{node_id} is at version {n['version']}, not {expect}")
        if actor != "kernel":
            if self._require_type(n["type"], ("node", "scope"))["kind"] == "scope":
                raise Forbidden(f"{node_id} is a scope: deleting it would drop what it holds open")
            if actor == "model" and n["author"] != "model":
                raise Forbidden(f"{node_id} was written by {n['author']}: the model deletes only its own nodes")
        cur = self.db.execute("DELETE FROM k_nodes WHERE id = ? AND version = ?", (node_id, n["version"]))
        if cur.rowcount != 1:
            raise Conflict(f"{node_id} changed while it was being deleted: re-read it")

    def _ensure_missing(self, node_id: str, *, actor: str, attrs: dict[str, Any]) -> str:
        """A placeholder for a reference to nothing, so the reference survives as an edge."""
        if not self.db.execute("SELECT 1 FROM k_nodes WHERE id = ?", (node_id,)).fetchone():
            self.put_node(node_id, MISSING, actor=actor, attrs=attrs, validate=False)
        return node_id

    # ── edges ────────────────────────────────────────────────────────────

    def _link(self, src: str, type_: str, dst: str, *, actor: str, attrs: dict[str, Any] | None = None,
             origin: str | None = None) -> None:
        _check_actor(actor)
        self._check_edge_actor(type_, actor)
        for n in (src, dst):
            if not self.db.execute("SELECT 1 FROM k_nodes WHERE id = ?", (n,)).fetchone():
                raise KernelError(f"no node {n!r}")
        self.db.execute(
            "INSERT INTO k_edges (src, type, dst, attrs, origin, clock) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(src, type, dst) DO UPDATE SET attrs = excluded.attrs, clock = excluded.clock",
            (src, type_, dst, json.dumps(attrs or {}, ensure_ascii=False),
             origin if origin is not None else actor, self.clock()))

    def _unlink(self, src: str, type_: str, dst: str, *, actor: str) -> bool:
        _check_actor(actor)
        self._check_edge_actor(type_, actor)
        return self.db.execute("DELETE FROM k_edges WHERE src = ? AND type = ? AND dst = ?",
                               (src, type_, dst)).rowcount > 0

    def _check_edge_actor(self, type_: str, actor: str) -> None:
        t = self._require_type(type_, ("edge",))
        if t["authority"] == "kernel" and actor != "kernel":
            raise Forbidden(f"{type_!r} edges are the scope machinery's: use open_scope, carry, touch or detach")

    # Every write is one atomic unit: alone it commits, inside a caller's transaction it is a
    # savepoint (so no write ever leaves Python's implicit transaction open behind it).
    def put_node(self, *a: Any, **k: Any) -> dict[str, Any]:
        with self.tx():
            return self._put_node(*a, **k)

    def update_node(self, *a: Any, **k: Any) -> dict[str, Any]:
        with self.tx():
            return self._update_node(*a, **k)

    def delete_node(self, *a: Any, **k: Any) -> None:
        with self.tx():
            self._delete_node(*a, **k)

    def ensure_missing(self, *a: Any, **k: Any) -> str:
        with self.tx():
            return self._ensure_missing(*a, **k)

    def link(self, *a: Any, **k: Any) -> None:
        with self.tx():
            self._link(*a, **k)

    def unlink(self, *a: Any, **k: Any) -> bool:
        with self.tx():
            return self._unlink(*a, **k)

    def edges(self, src: str | None = None, type_: str | None = None, dst: str | None = None) -> list[dict[str, Any]]:
        where, args = [], []
        for col, v in (("src", src), ("type", type_), ("dst", dst)):
            if v is not None:
                where.append(f"{col} = ?")
                args.append(v)
        sql = "SELECT * FROM k_edges" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY src, type, dst"
        out = []
        for r in self.db.execute(sql, args):
            d = dict(r)
            d["attrs"] = json.loads(d["attrs"])
            out.append(d)
        return out

    # ── rules ────────────────────────────────────────────────────────────

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        r = self.db.execute("SELECT * FROM k_rules WHERE id = ?", (rule_id,)).fetchone()
        return dict(r) if r else None

    def define_rule(
        self,
        rule_id: str,
        phase: str,
        body: str,
        *,
        actor: str,
        applies_to: str = "*",
        severity: str = "block",
        message: str = "",
        pkg: str = "",
        authority: str | None = None,
    ) -> dict[str, Any]:
        """Create or revise a rule. `body` holds the clauses that define the predicate named
        `rule_id`; for a gate rule each derived tuple is one finding, and `message` formats it with
        the head's variable names ({R}, {S!r}). The whole program is checked before it is stored."""
        self.define_rules([dict(id=rule_id, phase=phase, body=body, applies_to=applies_to, severity=severity,
                                message=message, pkg=pkg, authority=authority)], actor=actor)
        return self.get_rule(rule_id)  # type: ignore[return-value]

    def define_rules(self, specs: list[dict[str, Any]], *, actor: str) -> None:
        """Define several rules at once (they may refer to each other); the program they make with
        the active rules is checked as a whole, and nothing is stored if any of it is refused."""
        from . import rules  # the rule language depends on this module, not the other way round

        _check_actor(actor)
        prepared = []
        for spec in specs:
            rid, phase = spec["id"], spec["phase"]
            severity, applies_to = spec.get("severity") or "block", spec.get("applies_to") or "*"
            body, message = spec["body"], spec.get("message") or ""
            if not NAME_RE.match(rid):
                raise KernelError(f"rule id {rid!r}: lowercase letters, digits and _ only (it names the predicate)")
            if phase not in PHASES:
                raise KernelError(f"rule {rid}: phase must be one of {PHASES}")
            if severity not in SEVERITIES:
                raise KernelError(f"rule {rid}: severity must be one of {SEVERITIES}")
            if applies_to != "*":
                self._require_type(applies_to, ("scope",))
            old = self.get_rule(rid)
            if old and not may_change(actor, old["authority"]):
                raise Forbidden(f"rule {rid!r} is {old['authority']}: only "
                                f"{'a release' if old['authority'] == 'kernel' else 'the user'} can change it")
            clauses = rules.parse(body)
            heads = {c.head.pred for c in clauses}
            if heads != {rid}:
                raise KernelError(f"rule {rid!r} must define exactly the predicate {rid!r}; its clauses define "
                                  f"{', '.join(sorted(heads))}")
            if phase != "derive":  # a message names head positions, so they must agree across clauses
                rules.check_message(message, rules.head_names(clauses))
            pkg = spec.get("pkg") or (old["pkg"] if old else "")  # an edited package rule stays the package's
            prepared.append((rid, phase, applies_to, severity, body, message, pkg,
                             authority_for(actor, spec.get("authority")), bool(old)))
        new_ids = {p[0] for p in prepared}
        others = [r for r in self.active_rules() if r["id"] not in new_ids]
        program = rules.Program.from_rules(others + [{"id": p[0], "body": p[4]} for p in prepared])
        authority = {r["id"]: r["authority"] for r in others} | {p[0]: p[7] for p in prepared}
        for p in prepared:
            if p[7] != "proposed":
                self._sealed_closure(program, p[0], authority)
        with self.tx():
            for rid, phase, applies_to, severity, body, message, pkg, auth, existed in prepared:
                self.db.execute(
                    "INSERT INTO k_rules (id, phase, applies_to, severity, body, message, pkg, authority, origin, state)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active') ON CONFLICT(id) DO UPDATE SET phase = excluded.phase,"
                    " applies_to = excluded.applies_to, severity = excluded.severity, body = excluded.body,"
                    " message = excluded.message, pkg = excluded.pkg, authority = excluded.authority,"
                    " origin = excluded.origin, state = 'active', version = k_rules.version + 1",
                    (rid, phase, applies_to, severity, body, message, pkg, auth, actor))
                self.log(actor, f"rule {rid} {'revised' if existed else 'defined'} ({auth})", rid)
            self._bump_rules()

    @staticmethod
    def _sealed_closure(program: Any, rule_id: str, authority: dict[str, str]) -> None:
        """A sealed rule means what the user approved: it may not rest on a predicate the model can
        still rewrite."""
        weak = sorted(q for q in program.needed({rule_id}) if q != rule_id and authority.get(q) == "proposed")
        if weak:
            raise Forbidden(f"rule {rule_id!r} would rest on proposed rule(s) {', '.join(weak)}, which the model "
                            "can rewrite; approve those first")

    def retire_rule(self, rule_id: str, *, actor: str) -> None:
        _check_actor(actor)
        r = self.get_rule(rule_id)
        if r is None:
            raise KernelError(f"no rule {rule_id!r}")
        if not may_change(actor, r["authority"]):
            raise Forbidden(f"rule {rule_id!r} is {r['authority']}: only the user can retire it")
        dependents = [o["id"] for o in self.active_rules() if o["id"] != rule_id
                      and re.search(rf"\b{re.escape(rule_id)}\s*\(", o["body"])]
        if dependents:
            raise KernelError(f"rule {rule_id!r} is used by {', '.join(dependents)}; retire those first")
        with self.tx():
            self.db.execute("UPDATE k_rules SET state = 'retired', version = version + 1 WHERE id = ?", (rule_id,))
            self.log(actor, f"rule {rule_id} retired", rule_id)
            self._bump_rules()

    def approve(self, what: str, name: str, *, actor: str) -> None:
        """Promote a proposed rule or type to sealed. Only the user approves."""
        _check_actor(actor)
        if actor != "user":
            raise Forbidden("only the user approves a proposal (through the approval page, not a tool call)")
        table = {"rule": "k_rules", "type": "k_types"}.get(what)
        if table is None:
            raise KernelError("approve what: rule or type")
        key = "id" if what == "rule" else "name"
        r = self.db.execute(f"SELECT authority FROM {table} WHERE {key} = ?", (name,)).fetchone()
        if r is None:
            raise KernelError(f"no {what} {name!r}")
        if r[0] != "proposed":
            raise KernelError(f"{what} {name!r} is {r[0]}, not proposed")
        if what == "rule":
            from . import rules

            active = self.active_rules()
            self._sealed_closure(rules.Program.from_rules(active), name,
                                 {x["id"]: x["authority"] for x in active})
        with self.tx():
            self.db.execute(f"UPDATE {table} SET authority = 'sealed' WHERE {key} = ?", (name,))
            self.log(actor, f"{what} {name} approved", name)
            self._bump_rules()

    def active_rules(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM k_rules WHERE state = 'active' ORDER BY id")]
