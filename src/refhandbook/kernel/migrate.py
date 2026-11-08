"""Legacy store ⇄ kernel graph.

`ledger_to_graph` and `handbook_to_graph` take the JSON the legacy stores export; the matching
`*_from_graph` functions rebuild that JSON from the graph. A round trip must return the export
unchanged (tests/test_kernel_migration.py, and the differential harness in tests/conftest.py).

The legacy cells are kept verbatim as attributes (status text, dep text, evidence), and the
meaning in them becomes graph structure: the status key is the node state, every dep is an edge
typed by its relation, a K row's targets are `on` edges, configuration members, verdict cells,
pending hits and turn marks are edges. A reference to something that does not exist becomes a
`missing` node, so the reference is kept and the rules can report it.

A row's node is named by its nid (research.ensure_nid), which names the node and not its ledger: the
ledger holds it by `contains`, and its ledger-local name lives in the attributes (rid, xref). Only a
reference to a row that is not there keeps the ledger's name (`<ledger>:r:<id>`): it names a
reference, not a node.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .. import research as legacy
from .graph import CONTAINS, MISSING, Graph, KernelError, decode_type, encode_type
from .packages import handbook as hb_pkg
from .packages import research as rs_pkg

ACTOR = "kernel"
DERIVED = "derived_"  # attributes the projection computes (runtime._derive); not part of the export
LOG_ACTOR = "legacy"


def install(g: Graph) -> None:
    rs_pkg.install(g)
    hb_pkg.install(g)


# ── research ledgers ─────────────────────────────────────────────────────

ROW_KEYS = ("num", "status", "evidence", "dep", "grp", "turn_created", "turn_updated")
DOC_KEYS = ("label", "role", "owner", "sha", "sections", "sync_turn", "plan", "plan_turn", "turn", "sync_clock")


# one namespace per kind, so a row, a document, a verdict cell and a configuration that share a
# legacy name never resolve to each other
def _row_id(L: str, ref: str) -> str:
    return f"{L}:r:{ref}"


def _verdict_id(L: str, ref: str) -> str:
    return f"{L}:v:{ref}"


def _doc_id(L: str, ref: str) -> str:
    return f"{L}:d:{ref}"


def _cfg_id(L: str, name: str) -> str:
    return f"{L}:c:{name}"


# what a session marks on the ledger (rl_turnmarks.kind; the table keeps its old name, its `turn`
# column is the session's number): rows it changed or carried, hits it raised, K it runs, plans it made
SESSION_MARKS = ("touched", "carry", "raised", "runs", "planned")


def _session_id(L: str, n: int) -> str:
    return f"{L}:s:{n}"


class _LedgerRefs:
    def __init__(self, g: Graph, L: str):
        self.g, self.L = g, L
        self.rows: dict[str, str] = {}  # rid → the node of this ledger's row (its nid)

    def node(self, ref: str) -> str:
        """The node for a legacy reference (a row, or a verdict cell claim@config), or a placeholder."""
        if ref in self.rows:
            return self.rows[ref]
        nid = (_verdict_id if "@" in ref else _doc_id if re.fullmatch(r"D\d+", ref) else _row_id)(self.L, ref)
        if self.g.get_node(nid) is None:
            self.g.ensure_missing(nid, actor=ACTOR, attrs={"rid": ref})
            self.g.link(self.L, CONTAINS, nid, actor=ACTOR)
        return nid

    def config(self, name: str) -> str:
        nid = _cfg_id(self.L, name)
        if self.g.get_node(nid) is None:
            self.g.ensure_missing(nid, actor=ACTOR, attrs={"rid": name, "name": name})
            self.g.link(self.L, CONTAINS, nid, actor=ACTOR)
        return nid


def _row_ref(refs: "_LedgerRefs", rid: str) -> str:
    """A reference that legacy resolves among rows only (deps, members, claims)."""
    if rid in refs.rows:
        return refs.rows[rid]
    nid = _row_id(refs.L, rid)
    n = refs.g.get_node(nid)
    if n is None:
        refs.g.ensure_missing(nid, actor=ACTOR, attrs={"rid": rid, "xref": f"{refs.L}/{rid}"})
        refs.g.link(refs.L, CONTAINS, nid, actor=ACTOR)
    elif n["type"] == MISSING and not refs.g.edges(src=refs.L, type_=CONTAINS, dst=nid):
        refs.g.link(refs.L, CONTAINS, nid, actor=ACTOR)  # a placeholder another ledger's ref made first
    return nid


def row_node(g: Graph, L: str, rid: str) -> str | None:
    """The node of row `rid` of ledger L, when L's image holds it. Its id is the row's nid, which does
    not name L, so it is found through L's `contains` edges."""
    r = g.db.execute("SELECT n.id FROM k_edges e JOIN k_nodes n ON n.id = e.dst WHERE e.src = ? AND e.type = ?"
                     " AND n.type != ? AND json_extract(n.attrs, '$.sec') IS NOT NULL"
                     " AND json_extract(n.attrs, '$.rid') = ?", (L, CONTAINS, MISSING, rid)).fetchone()
    return r[0] if r else None


def _xref_node(g: Graph, L2: str, rid: str) -> str:
    """The node a cross-ledger reference `L2/rid` rests on: the row itself when L2 is in the graph,
    else a placeholder that no ledger contains (so L2's projection takes it over, and dropping the
    referring ledger does not take it away)."""
    found = row_node(g, L2, rid)
    if found is not None:
        return found
    nid = _row_id(L2, rid)
    if g.get_node(nid) is None:
        g.ensure_missing(nid, actor=ACTOR, attrs={"rid": rid, "xref": f"{L2}/{rid}"})
    return nid


DEP_EDGE = encode_type("dep", legacy.REL)


def _dep_target(g: Graph, refs: "_LedgerRefs", target: str) -> str:
    return _xref_node(g, *target.split("/", 1)) if "/" in target else _row_ref(refs, target)


def relink_incoming(g: Graph, db, L: str) -> None:
    """Restore the dep edges other ledgers hold into L (a projection of L recreates L's nodes, and the
    edges into the old ones went with them). `db` is the legacy store the rows are read from."""
    for r in db.execute("SELECT ledger, id, nid, dep FROM rl_rows WHERE ledger != ? AND sec NOT IN ('K', 'U')"
                        " AND dep LIKE ?", (L, f"%{L}/%")):
        src = r["nid"] or _row_id(r["ledger"], r["id"])
        if g.get_node(src) is None:
            continue
        for lg2, d in legacy.xrefs(r["dep"]):
            if lg2 == L:
                g.link(src, DEP_EDGE, _xref_node(g, L, d), actor=ACTOR)


def ledger_to_graph(g: Graph, data: dict[str, Any]) -> str:
    """Load one exported ledger. Returns the ledger's node id (its legacy id)."""
    lg = dict(data["ledger"])
    tables = data["tables"]
    L = lg.pop("id")
    if g.get_node(L) is not None:
        raise KernelError(f"ledger {L!r} is already in the graph")
    with g.tx():
        g.tick()
        g.put_node(L, "ledger", actor=ACTOR, state="open", content=lg.pop("question"), attrs=lg, origin="user")
        refs = _LedgerRefs(g, L)
        rows = tables.get("rl_rows", [])
        for r in rows:
            sec = r["sec"]
            if sec not in rs_pkg.SEC_TYPE:
                raise KernelError(f"row {r['id']}: unknown section {sec!r}")
            ph = _row_id(L, r["id"])  # the name a reference to this row has while the row is not here
            nid = r.get("nid") or ph  # the row's node id (an export from before schema 2 has none)
            attrs = {"rid": r["id"], "sec": sec, "xref": f"{L}/{r['id']}", **{k: r[k] for k in ROW_KEYS},
                     "clock": r["clock_updated"], **({"nid": r["nid"]} if "nid" in r else {})}
            old = g.get_node(ph)
            if old is not None and old["type"] == MISSING:  # a placeholder a cross-ledger ref made
                g.delete_node(ph, actor=ACTOR)  # (its incoming edges come back with relink_incoming)
            g.put_node(nid, rs_pkg.SEC_TYPE[sec], actor=ACTOR, state=legacy.key(r["status"]), content=r["content"],
                       attrs=attrs, origin=r["origin"], validate=False)
            g.link(L, CONTAINS, nid, actor=ACTOR)
            refs.rows[r["id"]] = nid
        # `main` is the user's line (A/T rows that are on) unless a stored configuration named main
        # replaces it, as research._configs lets an imported one do
        if not any(c["name"] == "main" for c in tables.get("rl_configs", [])):
            g.put_node(_cfg_id(L, "main"), "config", actor=ACTOR,
                       attrs={"rid": "main", "name": "main", "synthetic": True})
            g.link(L, CONTAINS, _cfg_id(L, "main"), actor=ACTOR)
        for c in tables.get("rl_configs", []):
            nid = _cfg_id(L, c["name"])
            g.put_node(nid, "config", actor=ACTOR, attrs={"rid": c["name"], "name": c["name"], "members": c["members"],
                                                          "spec": c["spec"], "purpose": c["purpose"], "turn": c["turn"]})
            g.link(L, CONTAINS, nid, actor=ACTOR)
        for v in tables.get("rl_verdicts", []):
            ref = f"{v['claim']}@{v['config']}"
            nid = _verdict_id(L, ref)
            g.put_node(nid, "verdict", actor=ACTOR, state=v["verdict"], validate=False,
                       attrs={"rid": ref, "claim": v["claim"], "config": v["config"], "evidence": v["evidence"],
                              "turn": v["turn"], "clock": v["clock"]})
            g.link(L, CONTAINS, nid, actor=ACTOR)
        for d in tables.get("rl_docs", []):
            nid = _doc_id(L, d["id"])
            g.put_node(nid, "document", actor=ACTOR, state=d["role"], validate=False,
                       attrs={"rid": d["id"], **{k: d[k] for k in DOC_KEYS}})
            g.link(L, CONTAINS, nid, actor=ACTOR)
        marks = tables.get("rl_turnmarks", [])
        live = {r[0]: r[1] for r in g.db.execute("SELECT seq, role FROM k_sessions WHERE scope = ? AND closed IS NULL", (L,))}
        known = live or g.db.execute("SELECT 1 FROM k_sessions WHERE scope = ? LIMIT 1", (L,)).fetchone()
        for n in sorted({m["turn"] for m in marks} | {lg["turn"]} | set(live)):
            nid = _session_id(L, n)
            is_open = n in live if known else bool(lg["open"]) and n == lg["turn"]  # before sessions: one open turn
            g.put_node(nid, "session", actor=ACTOR, state="open" if is_open else "closed",
                       attrs={"n": n, "role": live.get(n, "chat")})
            g.link(L, CONTAINS, nid, actor=ACTOR)
        # structure: the meaning held in the cells
        for r in rows:
            nid = refs.rows[r["id"]]
            if r["sec"] in ("K", "U"):  # a plan or a directive: its dep says where it works, not what it rests on
                for d in legacy.basis(r["dep"]):
                    g.link(nid, "on", _row_ref(refs, d), actor=ACTOR)
                continue
            for _, target in legacy.edges(r["dep"]):
                g.link(nid, DEP_EDGE, _dep_target(g, refs, target), actor=ACTOR)
        for c in tables.get("rl_configs", []):
            for m in c["members"].split():
                g.link(_cfg_id(L, c["name"]), "member", _row_ref(refs, m), actor=ACTOR)
        for v in tables.get("rl_verdicts", []):
            nid = _verdict_id(L, f"{v['claim']}@{v['config']}")
            g.link(nid, "of", _row_ref(refs, v["claim"]), actor=ACTOR)
            g.link(nid, "under", refs.config(v["config"]), actor=ACTOR)
        for p in tables.get("rl_pending", []):
            g.link(refs.node(p["src"]), "pending_hit", refs.node(p["hit"]), actor=ACTOR)
        for m in marks:
            if m["kind"] not in SESSION_MARKS:
                raise KernelError(f"session mark kind {m['kind']!r} is not known")
            g.link(_session_id(L, m["turn"]), m["kind"], refs.node(m["ref"]), actor=ACTOR, attrs={"note": m["note"]})
        for e in tables.get("rl_log", []):
            g.db.execute("INSERT INTO k_log (clock, actor, event, ref, meta) VALUES (?, ?, ?, ?, ?)",
                         (g.clock(), LOG_ACTOR, e["msg"], L, json.dumps({"turn": e["turn"], "ts": e["ts"]})))
    return L


def _contained(g: Graph, L: str) -> list[dict[str, Any]]:
    out = []
    for r in g.db.execute("SELECT n.* FROM k_edges e JOIN k_nodes n ON n.id = e.dst WHERE e.src = ? AND e.type = ?"
                          " ORDER BY n.id", (L, CONTAINS)):
        d = dict(r)
        d["attrs"] = json.loads(d["attrs"])
        out.append(d)
    return out


# The packages whose nodes and edges a projection rebuilds; an edge of any other package (an entry's ref, a
# tag) is someone's own writing that happens to touch the image, and is kept across the rebuild.
PROJECTED_PKGS = ("research", "handbook", "kernel", "")


def ledger_image(L: str) -> tuple[str, tuple]:
    """The ids a ledger's image holds: its node and what it contains (a SELECT and its arguments)."""
    return "SELECT ? UNION SELECT dst FROM k_edges WHERE src = ? AND type = ?", (L, L, CONTAINS)


HANDBOOK_IMAGE = ("SELECT id FROM k_nodes WHERE type IN ('card', 'step') OR (type = 'missing' AND id LIKE 'card:%')", ())


def foreign_edges(g: Graph, image: tuple[str, tuple]) -> list[tuple]:
    """The edges no projection makes that touch an image about to be rebuilt. Their ends keep their ids
    across the rebuild (a row's node is its nid, a card's node its id), so `restore_edges` puts them back."""
    nodes, args = image
    marks = ",".join("?" * len(PROJECTED_PKGS))
    return [tuple(r) for r in g.db.execute(
        f"SELECT e.src, e.type, e.dst, e.attrs, e.origin, e.clock FROM k_edges e JOIN k_types t ON t.name = e.type"
        f" WHERE t.pkg NOT IN ({marks}) AND (e.src IN ({nodes}) OR e.dst IN ({nodes}))",
        (*PROJECTED_PKGS, *args, *args))]


def restore_edges(g: Graph, kept: list[tuple]) -> int:
    """Put back what `foreign_edges` kept, with its writer and its clock, where both ends exist again (an
    edge to a row that is gone goes with it)."""
    n = 0
    for src, type_, dst, attrs, origin, clock in kept:
        if g.db.execute("SELECT COUNT(*) FROM k_nodes WHERE id IN (?, ?)", (src, dst)).fetchone()[0] == len({src, dst}):
            n += g.db.execute("INSERT INTO k_edges (src, type, dst, attrs, origin, clock) VALUES (?, ?, ?, ?, ?, ?)"
                              " ON CONFLICT(src, type, dst) DO NOTHING", (src, type_, dst, attrs, origin, clock)).rowcount
    return n


def _image(g: Graph, L: str) -> tuple[dict[str, dict], dict[tuple, dict]]:
    """A ledger's image as it stands: its nodes, and the edges a projection makes that touch them."""
    nodes_sql, args = ledger_image(L)
    nodes = {r["id"]: dict(r) for r in g.db.execute(f"SELECT * FROM k_nodes WHERE id IN ({nodes_sql})", args)}
    marks = ",".join("?" * len(PROJECTED_PKGS))
    edges = {(r["src"], r["type"], r["dst"]): dict(r) for r in g.db.execute(
        f"SELECT e.* FROM k_edges e JOIN k_types t ON t.name = e.type WHERE t.pkg IN ({marks})"
        f" AND (e.src IN ({nodes_sql}) OR e.dst IN ({nodes_sql}))", (*PROJECTED_PKGS, *args, *args))}
    return nodes, edges


def _target(g: Graph, L: str, data: dict[str, Any], db) -> tuple[dict[str, dict], dict[tuple, dict]]:  # noqa: ANN001
    """The image a redraw of L from `data` would make — drawn inside a savepoint and rolled back, so the
    projection's own code says what the image is and nothing of the drawing stays."""
    g.db.execute("SAVEPOINT k_target")
    try:
        drop_ledger(g, L, keep_log=True)
        ledger_to_graph(g, data)
        relink_incoming(g, db, L)
        return _image(g, L)
    finally:
        g.db.execute("ROLLBACK TO k_target")
        g.db.execute("RELEASE k_target")


NODE_FIELDS = ("type", "state", "content", "attrs", "origin")


def apply_ledger(g: Graph, L: str, data: dict[str, Any], db, actor: str = "kernel") -> dict[str, int]:  # noqa: ANN001
    """Bring L's image to what `data` says in place: only nodes and edges that differ from a redraw change.
    A node that stays keeps its version, its author and when it was made; a new one is `actor`'s; a removed one
    goes, with its edges. Edges no projection makes (an entry's refs, tags) are not compared and stay."""
    with g.tx():
        target_nodes, target_edges = _target(g, L, data, db)
        nodes, edges = _image(g, L)
        c = g.tick()
        derived = {k: v for k, v in json.loads(nodes.get(L, {}).get("attrs") or "{}").items() if k.startswith("derived_")}
        if L in target_nodes and derived:  # facts the runtime derives onto the ledger node after each sync
            target_nodes[L]["attrs"] = json.dumps({**json.loads(target_nodes[L]["attrs"]), **derived}, ensure_ascii=False)
        n = {"added": 0, "changed": 0, "removed": 0, "edges": 0}
        same = lambda a, b: all((json.loads(a[f]) == json.loads(b[f])) if f == "attrs" else a[f] == b[f]  # noqa: E731
                                for f in NODE_FIELDS)
        for nid, t in target_nodes.items():
            cur = nodes.get(nid)
            if cur is None:
                if g.db.execute("SELECT 1 FROM k_nodes WHERE id = ?", (nid,)).fetchone():  # outside L's image: adopt
                    g.db.execute("UPDATE k_nodes SET type = ?, state = ?, content = ?, attrs = ?, origin = ?,"
                                 " version = version + 1, updated = ? WHERE id = ?",
                                 (*(t[f] for f in NODE_FIELDS), c, nid))
                else:
                    g.db.execute("INSERT INTO k_nodes (id, type, state, content, attrs, origin, author, version, created,"
                                 " updated) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                                 (nid, *(t[f] for f in NODE_FIELDS), actor, c, c))
                n["added"] += 1
            elif not same(cur, t):
                g.db.execute("UPDATE k_nodes SET type = ?, state = ?, content = ?, attrs = ?, origin = ?,"
                             " version = version + 1, updated = ? WHERE id = ?", (*(t[f] for f in NODE_FIELDS), c, nid))
                n["changed"] += 1
        for key in edges.keys() - target_edges.keys():
            g.db.execute("DELETE FROM k_edges WHERE src = ? AND type = ? AND dst = ?", key)
            n["edges"] += 1
        for key, t in target_edges.items():
            cur = edges.get(key)
            if cur is None:
                g.db.execute("INSERT INTO k_edges (src, type, dst, attrs, origin, clock) VALUES (?, ?, ?, ?, ?, ?)"
                             " ON CONFLICT(src, type, dst) DO UPDATE SET attrs = excluded.attrs, origin = excluded.origin",
                             (*key, t["attrs"], t["origin"], c))
                n["edges"] += 1
            elif json.loads(cur["attrs"]) != json.loads(t["attrs"]) or cur["origin"] != t["origin"]:
                g.db.execute("UPDATE k_edges SET attrs = ?, origin = ? WHERE src = ? AND type = ? AND dst = ?",
                             (t["attrs"], t["origin"], *key))
                n["edges"] += 1
        for nid in nodes.keys() - target_nodes.keys():
            g.db.execute("DELETE FROM k_nodes WHERE id = ?", (nid,))
            n["removed"] += 1
    return n


def drop_ledger(g: Graph, L: str, keep_log: bool = False) -> None:
    """Remove a ledger's image: its node and everything it contains, and (unless keep_log, for a
    re-projection) its carried-over log."""
    with g.tx():
        g.db.execute("DELETE FROM k_nodes WHERE id IN (SELECT dst FROM k_edges WHERE src = ? AND type = ?)",
                     (L, CONTAINS))
        g.db.execute("DELETE FROM k_nodes WHERE id = ?", (L,))
        if not keep_log:
            g.db.execute("DELETE FROM k_log WHERE ref = ? AND actor = ?", (L, LOG_ACTOR))


def ledgers_in_graph(g: Graph) -> list[str]:
    return [r[0] for r in g.db.execute("SELECT id FROM k_nodes WHERE type = 'ledger' ORDER BY id")]


def ledger_from_graph(g: Graph, L: str, include_log: bool = True) -> dict[str, Any]:
    """Rebuild the legacy export of one ledger."""
    lg = g.node(L)
    if lg["type"] != "ledger":
        raise KernelError(f"{L} is not a ledger")
    ledger = {"id": L, "question": lg["content"],
              **{k: v for k, v in lg["attrs"].items() if not k.startswith(DERIVED)}}
    rid = {n["id"]: n["attrs"].get("rid") for n in _contained(g, L)}
    tables: dict[str, list[dict[str, Any]]] = {t: [] for t in legacy.Research.CHILD_TABLES}
    turns = {}
    for n in _contained(g, L):
        a, t = n["attrs"], n["type"]
        if t in rs_pkg.TYPE_SEC:
            tables["rl_rows"].append({"ledger": L, "id": a["rid"], "sec": a["sec"], "num": a["num"],
                                      "content": n["content"], "origin": n["origin"], "status": a["status"],
                                      "evidence": a["evidence"], "dep": a["dep"], "grp": a["grp"],
                                      "turn_created": a["turn_created"], "turn_updated": a["turn_updated"],
                                      "clock_updated": a["clock"], **({"nid": a["nid"]} if "nid" in a else {})})
        elif t == "config" and not a.get("synthetic"):
            tables["rl_configs"].append({"ledger": L, "name": a["name"], "members": a["members"], "spec": a["spec"],
                                         "purpose": a["purpose"], "turn": a["turn"]})
        elif t == "verdict":
            tables["rl_verdicts"].append({"ledger": L, "claim": a["claim"], "config": a["config"], "verdict": n["state"],
                                          "evidence": a["evidence"], "turn": a["turn"], "clock": a["clock"]})
        elif t == "document":
            tables["rl_docs"].append({"ledger": L, "id": a["rid"], **{k: a[k] for k in DOC_KEYS}})
        elif t == "session":
            turns[n["id"]] = a["n"]
    for e in g.db.execute("SELECT e.src, e.dst FROM k_edges e JOIN k_edges c ON c.dst = e.src"
                          " WHERE c.src = ? AND c.type = ? AND e.type = 'pending_hit'", (L, CONTAINS)):
        tables["rl_pending"].append({"ledger": L, "src": rid[e[0]], "hit": rid[e[1]]})
    for tid, n in turns.items():
        for e in g.edges(src=tid):
            if e["type"] in SESSION_MARKS:
                tables["rl_turnmarks"].append({"ledger": L, "turn": n, "kind": e["type"], "ref": rid[e["dst"]],
                                               "note": e["attrs"].get("note", "")})
    if include_log:
        for r in g.db.execute("SELECT event, meta FROM k_log WHERE ref = ? AND actor = ? ORDER BY seq", (L, LOG_ACTOR)):
            m = json.loads(r["meta"])
            tables["rl_log"].append({"ledger": L, "turn": m["turn"], "ts": m["ts"], "msg": r["event"]})
    else:
        del tables["rl_log"]
    return {"ledger": ledger, "tables": tables}


def ensure_session(g: Graph, L: str, n: int, idle: str = "", role: str = "chat") -> str:
    """The scope node of session n of ledger L, with its role and the `idle` reason research_end was
    given, so the close rules can be evaluated for it."""
    nid = _session_id(L, n)
    with g.tx():
        if g.get_node(nid) is None:
            g.put_node(nid, "session", actor=ACTOR, state="open", attrs={"n": n})
            g.link(L, CONTAINS, nid, actor=ACTOR)
        g.update_node(nid, actor=ACTOR, attrs={"idle": idle or None, "role": role}, validate=False)
    return nid


# ── handbook ─────────────────────────────────────────────────────────────

ENTRY_KEYS = ("kind", "title", "condition", "objective", "body", "revision", "updated_at", "triggers", "tags")
ITEM_KEYS = ("phase", "kind", "text", "response", "when", "ends")


def _card(i: str) -> str:
    return f"card:{i}"


def handbook_to_graph(g: Graph, data: dict[str, Any]) -> int:
    """Load a handbook export (Handbook.export()). Returns the number of cards."""
    with g.tx():
        g.tick()
        for rt in data.get("relation_types", []):
            # the relation vocabulary lives in its own namespace (rel_…): a relation named like a
            # structural edge (next, member, contains) can never collide with it
            name = encode_type("rel", rt["name"])
            inverse = encode_type("rel", rt["inverse"]) if rt["inverse"] else name
            old = g.get_type(name)
            if old is None or (old["inverse"], old["description"]) != (inverse, rt.get("description", "")):
                g.define_type(name, "edge", actor=ACTOR, pkg=hb_pkg.PKG, inverse=inverse,
                              description=rt.get("description", ""))
        entries = data.get("entries", [])
        for e in entries:
            g.put_node(_card(e["id"]), "card", actor=ACTOR, content=e["title"], attrs={k: e[k] for k in ENTRY_KEYS})
        for e in entries:
            prev = None
            for pos, it in enumerate(e["items"]):
                sid = f"{_card(e['id'])}#{pos}"
                g.put_node(sid, "step", actor=ACTOR, content=it["text"],
                           attrs={"pos": pos, **{k: it[k] for k in ITEM_KEYS}})
                g.link(_card(e["id"]), "has_step", sid, actor=ACTOR, attrs={"pos": pos})
                if prev:
                    g.link(prev, "next", sid, actor=ACTOR)
                if it.get("goto"):
                    target = _card(it["goto"])
                    if g.get_node(target) is None:
                        g.ensure_missing(target, actor=ACTOR, attrs={"rid": it["goto"]})
                    g.link(sid, "continues_to", target, actor=ACTOR)
                prev = sid
        for r in data.get("relations", []):
            g.link(_card(r["src"]), encode_type("rel", r["type"]), _card(r["dst"]), actor=ACTOR,
                   attrs={"note": r["note"]})
    return len(entries)


def drop_handbook(g: Graph) -> None:
    """Remove the cards' image (cards, steps, and placeholders for cards a GO TO named)."""
    with g.tx():
        g.db.execute("DELETE FROM k_nodes WHERE type IN ('card', 'step') OR (type = ? AND id LIKE 'card:%')",
                     (MISSING,))


def handbook_from_graph(g: Graph) -> dict[str, Any]:
    types = [{"name": decode_type("rel", r["name"]),
              "inverse": decode_type("rel", r["inverse"]) if r["inverse"] else r["inverse"],
              "description": r["description"]}
             for r in g.db.execute("SELECT name, inverse, description FROM k_types WHERE kind = 'edge' AND pkg = ?"
                                   " AND (name LIKE 'rel\\_%' ESCAPE '\\' OR name LIKE 'relx\\_%' ESCAPE '\\')"
                                   " ORDER BY name", (hb_pkg.PKG,))]
    entries = []
    for r in g.db.execute("SELECT id FROM k_nodes WHERE type = 'card' ORDER BY id"):
        n = g.node(r[0])
        e = {"id": n["id"][len("card:"):], **{k: n["attrs"][k] for k in ENTRY_KEYS}, "items": []}
        for s in g.db.execute("SELECT dst FROM k_edges WHERE src = ? AND type = 'has_step'", (n["id"],)):
            st = g.node(s[0])
            goto = g.edges(src=st["id"], type_="continues_to")
            item = {k: st["attrs"][k] for k in ITEM_KEYS}
            item["goto"] = goto[0]["dst"][len("card:"):] if goto else None
            e["items"].append((st["attrs"]["pos"], item))
        e["items"] = [it for _, it in sorted(e["items"], key=lambda p: p[0])]
        entries.append(e)
    names = {encode_type("rel", t["name"]) for t in types}
    relations = [{"src": e["src"][len("card:"):], "type": decode_type("rel", e["type"]), "dst": e["dst"][len("card:"):],
                  "note": e["attrs"].get("note", "")}
                 for e in g.edges() if e["type"] in names]
    return {"relation_types": types, "entries": entries, "relations": relations}


__all__ = ["MISSING", "drop_handbook", "drop_ledger", "ensure_session", "ledgers_in_graph", "handbook_from_graph", "handbook_to_graph", "install", "ledger_from_graph",
           "ledger_to_graph", "relink_incoming"]
