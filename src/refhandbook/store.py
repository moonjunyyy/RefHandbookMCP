"""Relational store for the handbook.

Entries are QRH-style cards. Everything a paper QRH fixes at print time (tabs,
index, cross-references) is a row here, so it can change at runtime:

    entries ──< items      ordered memory / action / deferred lines
            ──< triggers   alerting cues the entry is looked up by
            ──< tags       dynamic "tabs"
    relations(src, type, dst)   typed edges; types live in relation_types
    edges                       view: relations + every step-level GO TO
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PHASES = ("memory", "action", "deferred")
ITEM_KINDS = ("step", "caution", "note")
ITEM_FIELDS = {"phase", "kind", "text", "response", "when", "goto", "ends"}
STEP_LINK = "continues_to"  # derived from items.goto, never stored in relations

DEFAULT_RELATION_TYPES = [
    (STEP_LINK, "continued_from", "A step in the source sends the reader to the target (derived)."),
    ("see_also", "see_also", "Loosely related; symmetric."),
    ("escalates_to", "escalated_from", "Use the target when the source did not resolve the situation."),
    ("precedes", "follows", "The source is normally completed before the target."),
    ("requires", "required_by", "The source assumes the target has been done or is understood."),
    ("supersedes", "superseded_by", "The source replaces the target; the target is kept for history."),
    ("part_of", "contains", "The source is one section of the target."),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'checklist',
    title      TEXT NOT NULL,
    condition  TEXT NOT NULL DEFAULT '',
    objective  TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL DEFAULT '',
    revision   INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS triggers (
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    phrase   TEXT NOT NULL,
    PRIMARY KEY (entry_id, phrase)
);
CREATE TABLE IF NOT EXISTS tags (
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (entry_id, tag)
);
CREATE TABLE IF NOT EXISTS items (
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    phase    TEXT NOT NULL CHECK (phase IN ('memory', 'action', 'deferred')),
    kind     TEXT NOT NULL CHECK (kind IN ('step', 'caution', 'note')),
    text     TEXT NOT NULL,
    response TEXT,
    when_    TEXT,
    goto     TEXT,
    ends     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entry_id, position)
);
CREATE TABLE IF NOT EXISTS relation_types (
    name        TEXT PRIMARY KEY,
    inverse     TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS relations (
    src  TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    type TEXT NOT NULL REFERENCES relation_types(name),
    dst  TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (src, type, dst)
);
CREATE INDEX IF NOT EXISTS relations_dst ON relations(dst);
CREATE INDEX IF NOT EXISTS items_goto ON items(goto);
CREATE VIEW IF NOT EXISTS edges AS
    SELECT src, type, dst, note FROM relations
    UNION
    SELECT entry_id, 'continues_to', goto, '' FROM items WHERE goto IS NOT NULL;
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
    entry_id UNINDEXED, title, triggers, condition, body,
    tokenize = 'porter unicode61'
);
"""

# bm25 weights, one per search column: a hit on an alerting cue outranks a hit in the steps.
SEARCH_WEIGHTS = "0.0, 5.0, 8.0, 3.0, 1.0"

STOPWORDS = frozenset(
    "a an and are as at be but by do does for from how i if in is it its my no not of on or "
    "so than that the then there this to was we what when which why will with you".split()
)


class HandbookError(ValueError):
    """A request the caller can fix: unknown id, bad item, reserved name."""


def default_db_path() -> Path:
    return Path(os.environ.get("REFHANDBOOK_DB") or Path.home() / ".refhandbook" / "handbook.db")


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w]+", "-", text.lower()).strip("-")
    if not slug:
        raise HandbookError(f"cannot derive an id from {text!r}")
    return slug[:64].rstrip("-")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Handbook:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path) if path is not None else str(default_db_path())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._hooks: list[Callable[[], None]] = []
        self._quiet = 0
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        with self.db:
            self.db.executemany(
                "INSERT OR IGNORE INTO relation_types VALUES (?, ?, ?)", DEFAULT_RELATION_TYPES
            )

    def close(self) -> None:
        self.db.close()

    # ── change notification: a mirror (the kernel graph) follows the cards ──

    def on_change(self, fn: "Callable[[], None]") -> None:
        self._hooks.append(fn)

    def changed(self) -> None:
        if not self._quiet:
            for fn in self._hooks:
                fn()

    @contextmanager
    def quiet(self) -> "Iterator[None]":
        """Batch many writes into one change notification, sent at the end."""
        self._quiet += 1
        try:
            yield
        finally:
            self._quiet -= 1
        self.changed()

    # ── entries ──────────────────────────────────────────────────────────

    def exists(self, entry_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM entries WHERE id = ?", (entry_id,)).fetchone() is not None

    def _require(self, entry_id: str) -> None:
        if not self.exists(entry_id):
            raise HandbookError(f"no entry with id {entry_id!r}")

    def save_entry(
        self,
        *,
        id: str | None = None,
        title: str | None = None,
        kind: str | None = None,
        condition: str | None = None,
        objective: str | None = None,
        body: str | None = None,
        triggers: list[str] | None = None,
        tags: list[str] | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create an entry, or update one. On update, arguments left as None keep
        their stored value; a list argument replaces the stored list whole."""
        if id is None:
            if not title:
                raise HandbookError("a new entry needs a title")
            id = slugify(title)
        else:
            id = slugify(id)
        clean_items = None if items is None else [_clean_item(i, n) for n, i in enumerate(items, 1)]

        with self.db:
            row = self.db.execute("SELECT * FROM entries WHERE id = ?", (id,)).fetchone()
            if row is None:
                if not title:
                    raise HandbookError(f"no entry {id!r} to update; pass a title to create it")
                self.db.execute(
                    "INSERT INTO entries (id, kind, title, condition, objective, body, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (id, kind or "checklist", title, condition or "", objective or "", body or "", _now()),
                )
            else:
                keep = lambda new, col: row[col] if new is None else new
                self.db.execute(
                    "UPDATE entries SET kind = ?, title = ?, condition = ?, objective = ?, body = ?,"
                    " revision = revision + 1, updated_at = ? WHERE id = ?",
                    (
                        keep(kind, "kind"),
                        keep(title, "title"),
                        keep(condition, "condition"),
                        keep(objective, "objective"),
                        keep(body, "body"),
                        _now(),
                        id,
                    ),
                )
            for table, column, values in (("triggers", "phrase", triggers), ("tags", "tag", tags)):
                if values is not None:
                    self.db.execute(f"DELETE FROM {table} WHERE entry_id = ?", (id,))
                    self.db.executemany(
                        f"INSERT OR IGNORE INTO {table} (entry_id, {column}) VALUES (?, ?)",
                        [(id, v.strip()) for v in values if v.strip()],
                    )
            if clean_items is not None:
                self.db.execute("DELETE FROM items WHERE entry_id = ?", (id,))
                self.db.executemany(
                    "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (id, n, i["phase"], i["kind"], i["text"], i["response"], i["when"], i["goto"], i["ends"])
                        for n, i in enumerate(clean_items)
                    ],
                )
            self._reindex(id)
        self.changed()
        return self.get_entry(id)

    def _reindex(self, entry_id: str) -> None:
        entry = self.get_entry(entry_id)
        lines = [entry["objective"], entry["body"], " ".join(entry["tags"])]
        for item in entry["items"]:
            lines += [item["text"], item["when"] or "", item["response"] or ""]
        self.db.execute("DELETE FROM search WHERE entry_id = ?", (entry_id,))
        self.db.execute(
            "INSERT INTO search VALUES (?, ?, ?, ?, ?)",
            (entry_id, entry["title"], "\n".join(entry["triggers"]), entry["condition"], "\n".join(lines)),
        )

    def get_entry(self, entry_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise HandbookError(f"no entry with id {entry_id!r}")
        entry = dict(row)
        entry["triggers"] = self._column("SELECT phrase FROM triggers WHERE entry_id = ? ORDER BY phrase", entry_id)
        entry["tags"] = self._column("SELECT tag FROM tags WHERE entry_id = ? ORDER BY tag", entry_id)
        entry["items"] = [
            {
                "phase": r["phase"],
                "kind": r["kind"],
                "text": r["text"],
                "response": r["response"],
                "when": r["when_"],
                "goto": r["goto"],
                "goto_title": r["goto_title"],
                "ends": bool(r["ends"]),
            }
            for r in self.db.execute(
                "SELECT i.*, e.title AS goto_title FROM items i LEFT JOIN entries e ON e.id = i.goto"
                " WHERE i.entry_id = ? ORDER BY i.position",
                (entry_id,),
            )
        ]
        return entry

    def _column(self, sql: str, *params: Any) -> list[Any]:
        return [r[0] for r in self.db.execute(sql, params)]

    def delete_entry(self, entry_id: str) -> None:
        self._require(entry_id)
        with self.db:
            self.db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            self.db.execute("DELETE FROM search WHERE entry_id = ?", (entry_id,))
        self.changed()

    # ── finding the right entry ──────────────────────────────────────────

    def lookup(self, situation: str, limit: int = 5, scope: str = "all") -> list[dict[str, Any]]:
        """scope: all | handbook (without the managed research cards, id rs-*) | research (only those)."""
        if scope not in ("all", "handbook", "research"):
            raise HandbookError("scope must be 'handbook', 'research' or 'all'")
        terms = [t for t in re.findall(r"\w+", situation.lower()) if len(t) > 1 and t not in STOPWORDS]
        if not terms:
            return []
        query = " OR ".join(f'"{t}"*' for t in dict.fromkeys(terms))
        where = {"all": "", "handbook": " AND e.id NOT LIKE 'rs-%'", "research": " AND e.id LIKE 'rs-%'"}[scope]
        rows = self.db.execute(
            f"SELECT e.id, e.kind, e.title, e.condition, e.objective,"
            f"       bm25(search, {SEARCH_WEIGHTS}) AS score,"
            f"       (SELECT group_concat(src, ', ') FROM relations"
            f"         WHERE type = 'supersedes' AND dst = e.id) AS superseded_by,"
            f"       (SELECT group_concat(tag, ' ') FROM tags WHERE entry_id = e.id AND tag LIKE 'device:%') AS device"
            f"  FROM search JOIN entries e ON e.id = search.entry_id"
            f" WHERE search MATCH ?{where}"
            # A superseded entry is still findable, but never ahead of a current one.
            f" ORDER BY superseded_by IS NOT NULL, score LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def index(self, group_by: str = "tag") -> dict[str, list[dict[str, Any]]]:
        if group_by == "tag":
            sql = "SELECT COALESCE(t.tag, '(untagged)') AS grp, e.* FROM entries e LEFT JOIN tags t ON t.entry_id = e.id"
        elif group_by == "kind":
            sql = "SELECT e.kind AS grp, e.* FROM entries e"
        elif group_by == "alpha":
            sql = "SELECT upper(substr(e.title, 1, 1)) AS grp, e.* FROM entries e"
        else:
            raise HandbookError("group_by must be 'tag', 'kind' or 'alpha'")
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in self.db.execute(sql + " ORDER BY grp = '(untagged)', grp, e.title COLLATE NOCASE"):
            groups.setdefault(r["grp"], []).append(dict(r))
        return groups

    # ── relations ────────────────────────────────────────────────────────

    def relation_types(self) -> list[dict[str, str]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM relation_types ORDER BY name")]

    def define_relation_type(self, name: str, inverse: str | None = None, description: str = "") -> dict[str, str]:
        name, inverse = slugify(name).replace("-", "_"), slugify(inverse or name).replace("-", "_")
        for row in self.relation_types():
            taken = {row["name"], row["inverse"]}
            if row["name"] != name and taken & {name, inverse}:
                raise HandbookError(f"{name!r}/{inverse!r} collides with existing type {row['name']!r}/{row['inverse']!r}")
        if name == STEP_LINK:
            raise HandbookError(f"{STEP_LINK!r} is built in")
        with self.db:
            self.db.execute(
                "INSERT INTO relation_types VALUES (?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET inverse = excluded.inverse, description = excluded.description",
                (name, inverse, description),
            )
        self.changed()
        return {"name": name, "inverse": inverse, "description": description}

    def _orient(self, src: str, type: str, dst: str) -> tuple[str, str, str]:
        """Accept a type under either of its names; return the stored direction."""
        row = self.db.execute("SELECT name, inverse FROM relation_types WHERE ? IN (name, inverse)", (type,)).fetchone()
        if row is None:
            known = ", ".join(sorted({n for r in self.relation_types() for n in (r["name"], r["inverse"])}))
            raise HandbookError(f"unknown relation type {type!r}; define it first. Known: {known}")
        if row["name"] == STEP_LINK:
            raise HandbookError(f"{type!r} is derived from a step's goto; edit the entry's items instead")
        if row["name"] == type:
            return src, row["name"], dst
        return dst, row["name"], src

    def relate(self, src: str, type: str, dst: str, note: str = "") -> tuple[str, str, str]:
        self._require(src)
        self._require(dst)
        if src == dst:
            raise HandbookError("an entry cannot be related to itself")
        edge = self._orient(src, type, dst)
        with self.db:
            self.db.execute(
                "INSERT INTO relations VALUES (?, ?, ?, ?)"
                " ON CONFLICT(src, type, dst) DO UPDATE SET note = excluded.note",
                (*edge, note),
            )
        self.changed()
        return edge

    def unrelate(self, src: str, type: str, dst: str) -> bool:
        s, t, d = self._orient(src, type, dst)
        with self.db:
            cur = self.db.execute(
                "DELETE FROM relations WHERE type = ? AND ((src = ? AND dst = ?)"
                " OR (src = ? AND dst = ? AND type IN (SELECT name FROM relation_types WHERE name = inverse)))",
                (t, s, d, d, s),
            )
        self.changed()
        return cur.rowcount > 0

    def neighbors(self, entry_id: str) -> list[dict[str, Any]]:
        """Every edge touching the entry, read from the entry's side: an incoming
        edge is reported under the type's inverse name."""
        rows = self.db.execute(
            "SELECT e.type AS label, e.dst AS other, e.note FROM edges e WHERE e.src = :id"
            " UNION"
            " SELECT rt.inverse, e.src, e.note FROM edges e JOIN relation_types rt ON rt.name = e.type"
            "  WHERE e.dst = :id"
            " ORDER BY 1, 2",
            {"id": entry_id},
        ).fetchall()
        out = []
        for r in rows:
            title = self.db.execute("SELECT title FROM entries WHERE id = ?", (r["other"],)).fetchone()
            out.append({"label": r["label"], "id": r["other"], "title": title[0] if title else None, "note": r["note"]})
        return out

    def traverse(self, start: str, types: list[str] | None = None, depth: int = 2) -> list[dict[str, Any]]:
        """Breadth-first walk over edges in both directions. Each hop is reported
        once, the first time its far end is reached."""
        self._require(start)
        wanted = set(types) if types else None
        seen, hops, queue = {start}, [], deque([(start, 0)])
        while queue:
            node, d = queue.popleft()
            if d >= depth:
                continue
            for n in self.neighbors(node):
                if n["title"] is None or n["id"] in seen or (wanted and n["label"] not in wanted):
                    continue
                seen.add(n["id"])
                hops.append({"depth": d + 1, "from": node, **n})
                queue.append((n["id"], d + 1))
        return hops

    # ── audit ────────────────────────────────────────────────────────────

    def audit(self) -> list[dict[str, str]]:
        """Checks adapted from the CAP 676 Checklist Assessment Tool (paragraph
        numbers in brackets refer to CAP 676 Chapter 7)."""
        findings: list[dict[str, str]] = []

        def add(entry_id: str, level: str, message: str) -> None:
            findings.append({"entry": entry_id, "level": level, "message": message})

        linked = set(self._column("SELECT src FROM edges UNION SELECT dst FROM edges"))
        titles: dict[str, list[str]] = {}
        for entry_id in self._column("SELECT id FROM entries ORDER BY id"):
            e = self.get_entry(entry_id)
            titles.setdefault(e["title"].casefold(), []).append(entry_id)
            steps = [i for i in e["items"] if i["kind"] == "step"]
            memory = [i for i in steps if i["phase"] == "memory"]
            if not e["condition"]:
                add(entry_id, "error", "no condition: the reader cannot confirm this is the right entry [2.4]")
            if not e["triggers"]:
                add(entry_id, "warning", "no triggers: only findable by title and body text [1.10]")
            if e["kind"] == "checklist":
                if not e["objective"]:
                    add(entry_id, "warning", "no objective: the expected outcome is not stated [2.5]")
                if not steps:
                    add(entry_id, "error", "checklist has no steps")
                if len(memory) > 6:
                    add(entry_id, "error", f"{len(memory)} memory items; keep to six, preferably four [2.6]")
                elif len(memory) > 4:
                    add(entry_id, "warning", f"{len(memory)} memory items; four or fewer is preferred [2.6]")
            elif not e["body"] and not e["items"]:
                add(entry_id, "error", "entry has no content")
            for n, i in enumerate(steps, 1):
                if i["goto"] and i["goto_title"] is None:
                    add(entry_id, "error", f"step {n} goes to {i['goto']!r}, which does not exist [3.5]")
                if i["goto"] and i["ends"]:
                    add(entry_id, "error", f"step {n} both ends the entry and goes elsewhere [3.2]")
            if entry_id not in linked and not e["tags"]:
                add(entry_id, "warning", "orphan: no tags and no relations, so it appears in no index group")
            for src in self._column("SELECT src FROM relations WHERE type = 'supersedes' AND dst = ?", entry_id):
                for user in self._column(
                    "SELECT src FROM edges WHERE dst = ? AND type != 'supersedes' AND src != ?", entry_id, src
                ):
                    add(user, "warning", f"links to {entry_id!r}, which is superseded by {src!r}")
        for ids in titles.values():
            if len(ids) > 1:
                add(ids[0], "error", f"title shared with {', '.join(ids[1:])}: titles must be unambiguous [2.3]")
        return findings

    # ── import / export ──────────────────────────────────────────────────

    def export(self) -> dict[str, Any]:
        entries = []
        for entry_id in self._column("SELECT id FROM entries ORDER BY id"):
            e = self.get_entry(entry_id)
            for item in e["items"]:
                del item["goto_title"]
            entries.append(e)
        return {
            "relation_types": [r for r in self.relation_types() if r["name"] != STEP_LINK],
            "entries": entries,
            "relations": [dict(r) for r in self.db.execute("SELECT * FROM relations ORDER BY src, type, dst")],
        }

    def load(self, data: dict[str, Any]) -> int:
        with self.quiet():
            return self._load(data)

    def _load(self, data: dict[str, Any]) -> int:
        for rt in data.get("relation_types", []):
            if not self.db.execute("SELECT 1 FROM relation_types WHERE name = ?", (rt["name"],)).fetchone():
                self.define_relation_type(rt["name"], rt.get("inverse"), rt.get("description", ""))
        fields = ("id", "title", "kind", "condition", "objective", "body", "triggers", "tags", "items")
        for e in data.get("entries", []):
            self.save_entry(**{k: e[k] for k in fields if k in e})
        for r in data.get("relations", []):
            self.relate(r["src"], r["type"], r["dst"], r.get("note", ""))
        return len(data.get("entries", []))


def _clean_item(raw: Any, n: int) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        raise HandbookError(f"item {n} must be an object or a string")
    unknown = set(raw) - ITEM_FIELDS
    if unknown:
        raise HandbookError(f"item {n} has unknown field(s) {sorted(unknown)}; allowed: {sorted(ITEM_FIELDS)}")
    item = {
        "phase": raw.get("phase") or "action",
        "kind": raw.get("kind") or "step",
        "text": (raw.get("text") or "").strip(),
        "response": raw.get("response") or None,
        "when": raw.get("when") or None,
        "goto": slugify(raw["goto"]) if raw.get("goto") else None,
        "ends": bool(raw.get("ends")),
    }
    if item["phase"] not in PHASES:
        raise HandbookError(f"item {n}: phase must be one of {PHASES}")
    if item["kind"] not in ITEM_KINDS:
        raise HandbookError(f"item {n}: kind must be one of {ITEM_KINDS}")
    if not item["text"] and not (item["goto"] or item["ends"]):
        raise HandbookError(f"item {n} has no text")
    if item["kind"] != "step" and (item["goto"] or item["ends"] or item["response"]):
        raise HandbookError(f"item {n}: only a step can have a response, a goto or end the entry")
    return item
