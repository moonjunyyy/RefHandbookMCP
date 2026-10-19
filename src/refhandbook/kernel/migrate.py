"""Legacy store ⇄ kernel graph.

`ledger_to_graph` and `handbook_to_graph` take the JSON the legacy stores export; the matching
`*_from_graph` functions rebuild that JSON from the graph. A round trip must return the export
unchanged (tests/test_kernel_migration.py, and the differential harness in tests/conftest.py).

The legacy cells are kept verbatim as attributes (status text, dep text, evidence), and the
meaning in them becomes graph structure: the status key is the node state, every dep is an edge
typed by its relation, a K row's targets are `on` edges, configuration members, verdict cells,
pending hits and turn marks are edges. A reference to something that does not exist becomes a
`missing` node, so the reference is kept and the rules can report it.
"""

from __future__ import annotations

import json
from typing import Any

from .. import research as legacy
from .graph import CONTAINS, MISSING, Graph, KernelError, decode_type, encode_type
from .packages import handbook as hb_pkg
from .packages import research as rs_pkg

ACTOR = "kernel"
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


def _turn_id(L: str, n: int) -> str:
    return f"{L}:t:{n}"


class _LedgerRefs:
    def __init__(self, g: Graph, L: str):
        self.g, self.L = g, L

    def node(self, ref: str) -> str:
        """The node for a legacy reference (a row, or a verdict cell claim@config), or a placeholder."""
        nid = (_verdict_id if "@" in ref else _row_id)(self.L, ref)
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
    nid = _row_id(refs.L, rid)
    if refs.g.get_node(nid) is None:
        refs.g.ensure_missing(nid, actor=ACTOR, attrs={"rid": rid})
        refs.g.link(refs.L, CONTAINS, nid, actor=ACTOR)
    return nid


def _edge_type(g: Graph, rel: str) -> str:
    """The edge type of a dep relation. Legacy accepts any `word:` prefix; each gets its own type in
    the dep namespace, so `on:A1` or `member:A1` stays a dep and never becomes structure."""
    name = encode_type("dep", rel)
    if g.get_type(name) is None:
        g.define_type(name, "edge", actor=ACTOR, pkg=rs_pkg.PKG, classes=["dep"],
                      description=f"dep relation {rel!r} found in imported data")
    return name


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
            nid = _row_id(L, r["id"])
            attrs = {"rid": r["id"], "sec": sec, **{k: r[k] for k in ROW_KEYS}, "clock": r["clock_updated"]}
            g.put_node(nid, rs_pkg.SEC_TYPE[sec], actor=ACTOR, state=legacy.key(r["status"]), content=r["content"],
                       attrs=attrs, origin=r["origin"], validate=False)
            g.link(L, CONTAINS, nid, actor=ACTOR)
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
        for n in sorted({m["turn"] for m in marks} | {lg["turn"]}):
            nid = _turn_id(L, n)
            g.put_node(nid, "turn", actor=ACTOR, state="open" if lg["open"] and n == lg["turn"] else "closed",
                       attrs={"n": n})
            g.link(L, CONTAINS, nid, actor=ACTOR)
        # structure: the meaning held in the cells
        for r in rows:
            nid = _row_id(L, r["id"])
            if r["sec"] == "K":
                for d in legacy.ID_RE.findall(r["dep"] or ""):
                    g.link(nid, "on", _row_ref(refs, d), actor=ACTOR)
                continue
            for rel, d in legacy.edges(r["dep"]):
                g.link(nid, _edge_type(g, rel), _row_ref(refs, d), actor=ACTOR)
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
            if m["kind"] not in ("touched", "carry"):
                raise KernelError(f"turn mark kind {m['kind']!r} is not known")
            g.link(_turn_id(L, m["turn"]), m["kind"], refs.node(m["ref"]), actor=ACTOR, attrs={"note": m["note"]})
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


def ledger_from_graph(g: Graph, L: str, include_log: bool = True) -> dict[str, Any]:
    """Rebuild the legacy export of one ledger."""
    lg = g.node(L)
    if lg["type"] != "ledger":
        raise KernelError(f"{L} is not a ledger")
    ledger = {"id": L, "question": lg["content"], **lg["attrs"]}
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
                                      "clock_updated": a["clock"]})
        elif t == "config" and not a.get("synthetic"):
            tables["rl_configs"].append({"ledger": L, "name": a["name"], "members": a["members"], "spec": a["spec"],
                                         "purpose": a["purpose"], "turn": a["turn"]})
        elif t == "verdict":
            tables["rl_verdicts"].append({"ledger": L, "claim": a["claim"], "config": a["config"], "verdict": n["state"],
                                          "evidence": a["evidence"], "turn": a["turn"], "clock": a["clock"]})
        elif t == "document":
            tables["rl_docs"].append({"ledger": L, "id": a["rid"], **{k: a[k] for k in DOC_KEYS}})
        elif t == "turn":
            turns[n["id"]] = a["n"]
    for e in g.db.execute("SELECT e.src, e.dst FROM k_edges e JOIN k_edges c ON c.dst = e.src"
                          " WHERE c.src = ? AND c.type = ? AND e.type = 'pending_hit'", (L, CONTAINS)):
        tables["rl_pending"].append({"ledger": L, "src": rid[e[0]], "hit": rid[e[1]]})
    for tid, n in turns.items():
        for e in g.edges(src=tid):
            if e["type"] in ("touched", "carry"):
                tables["rl_turnmarks"].append({"ledger": L, "turn": n, "kind": e["type"], "ref": rid[e["dst"]],
                                               "note": e["attrs"].get("note", "")})
    if include_log:
        for r in g.db.execute("SELECT event, meta FROM k_log WHERE ref = ? AND actor = ? ORDER BY seq", (L, LOG_ACTOR)):
            m = json.loads(r["meta"])
            tables["rl_log"].append({"ledger": L, "turn": m["turn"], "ts": m["ts"], "msg": r["event"]})
    else:
        del tables["rl_log"]
    return {"ledger": ledger, "tables": tables}


def ensure_turn(g: Graph, L: str, n: int, idle: str = "") -> str:
    """The turn scope node for turn n (created closed-or-open from the ledger's state), with the
    `idle` reason research_end was given, so the close rules can be evaluated for it."""
    nid = _turn_id(L, n)
    lg = g.node(L)["attrs"]
    with g.tx():
        if g.get_node(nid) is None:
            g.put_node(nid, "turn", actor=ACTOR, state="open" if lg["open"] and n == lg["turn"] else "closed",
                       attrs={"n": n})
            g.link(L, CONTAINS, nid, actor=ACTOR)
        g.update_node(nid, actor=ACTOR, attrs={"idle": idle or None}, validate=False)
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
            g.define_type(encode_type("rel", rt["name"]), "edge", actor=ACTOR, pkg=hb_pkg.PKG,
                          inverse=encode_type("rel", rt["inverse"]) if rt["inverse"] else None,
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


__all__ = ["MISSING", "ensure_turn", "handbook_from_graph", "handbook_to_graph", "install", "ledger_from_graph",
           "ledger_to_graph"]
