"""The graph, for the person it belongs to (the site's page /handbook; docs/entry-graph.md): the entry graph as
nodes and links, read-only, as JSON behind the site sign-in.

Three readings, each small enough to draw:

    GET /handbook/api/v1/graph             the overview: every entry (a topic, with the number of rows it routes to
                                           and the ledger it stands for), the cards and the other entries it routes
                                           to, the tags it and its rows carry, and the rows more than one entry
                                           routes to. What joins two topics is there (a route between entries, a
                                           shared row, a tag of both); a row only one entry reaches is not.
    GET /handbook/api/v1/graph/entry?id=   one entry opened: the rows it routes to, the basis links between those
                                           rows, and their tags.
    GET /handbook/api/v1/node?id=          one node: what it is and what it says.

Nothing is written. A person reads their own store only. The routes are installed on the handbook's server
(remote.build), as the board's are."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anyio
from starlette.requests import Request

from portal.api import ApiError, endpoint, unauthorized

from . import entry_api
from .kernel import runtime
from .kernel.graph import Graph
from .kernel.packages.research import DEP_EDGE
from .store import Handbook, HandbookError

PREFIX = "/handbook/api/v1"
CONTENT = 6000  # how much of a node's content one reading carries
HIDDEN_TAGS = "tag:structure:"  # the mark of the structure is on every entry: it joins nothing


def _row_types(g: Graph) -> set[str]:
    return {r[0] for r in g.db.execute("SELECT type FROM k_type_class WHERE class = 'row'")}


def overview(g: Graph) -> dict[str, Any]:
    """Every entry and what joins the entries; a row only one entry routes to is counted, not listed."""
    rows = _row_types(g)
    nodes: dict[str, dict[str, Any]] = {}
    links: dict[tuple[str, str, str], dict[str, Any]] = {}

    def node(i: str, type_: str, **more: Any) -> dict[str, Any]:
        return nodes.setdefault(i, {"id": i, "type": type_, "title": entry_api.title(g, i), **more})

    def link(s: str, t: str, kind: str, n: int = 1) -> None:
        old = links.setdefault((s, t, kind), {"s": s, "t": t, "kind": kind, "n": 0})
        old["n"] += n

    for (i,) in g.db.execute("SELECT id FROM k_nodes WHERE type = 'entry' ORDER BY created, id"):
        node(i, "entry", n=0)
    reached: dict[str, list[str]] = {}  # a row -> the entries that route to it
    for src, dst, type_, state in g.db.execute(
            "SELECT e.src, e.dst, n.type, n.state FROM k_edges e JOIN k_nodes n ON n.id = e.dst"
            " WHERE e.type = 'ref' AND e.src IN (SELECT id FROM k_nodes WHERE type = 'entry') ORDER BY e.clock"):
        if type_ in rows:
            nodes[src]["n"] += 1
            reached.setdefault(dst, []).append(src)
        elif type_ == "ledger":
            nodes[src]["ledger"] = dst
        elif type_ == "entry":
            link(src, dst, "route")
        elif type_ == "card":
            node(dst, "card")
            link(src, dst, "card")
        elif type_ == "tag" and not dst.startswith(HIDDEN_TAGS):
            node(dst, "tag")
            link(src, dst, "tag")
    for row, entries in reached.items():
        if len(entries) > 1:
            n = g.node(row)
            node(row, "row", kind=n["type"], state=n["state"], shared=True)
            for e in entries:
                link(e, row, "shared")
    # a tag an entry carries, or that rows it routes to carry (n: how many of them)
    for src, tag in g.db.execute("SELECT src, dst FROM k_edges WHERE type = 'tagged'"
                                 " AND src IN (SELECT id FROM k_nodes WHERE type = 'entry')"):
        if not tag.startswith(HIDDEN_TAGS):
            node(tag, "tag")
            link(src, tag, "tag")
    for entry, tag, n in g.db.execute(
            "SELECT r.src, t.dst, COUNT(*) FROM k_edges t JOIN k_edges r ON r.dst = t.src AND r.type = 'ref'"
            " WHERE t.type = 'tagged' AND r.src IN (SELECT id FROM k_nodes WHERE type = 'entry')"
            " GROUP BY r.src, t.dst"):
        if entry in nodes and not tag.startswith(HIDDEN_TAGS):
            node(tag, "tag")
            link(entry, tag, "tag", n)
    return {"nodes": list(nodes.values()), "links": list(links.values())}


def opened(g: Graph, entry: str) -> dict[str, Any]:
    """One entry opened: the rows it routes to, the basis links between them, their tags."""
    n = g.get_node(entry)
    if n is None or n["type"] != "entry":
        raise ApiError(404, "not_found", f"no entry {entry!r}")
    rows = _row_types(g)
    nodes: dict[str, dict[str, Any]] = {}
    for dst, attrs, type_, state in g.db.execute(
            "SELECT e.dst, e.attrs, n.type, n.state FROM k_edges e JOIN k_nodes n ON n.id = e.dst"
            " WHERE e.src = ? AND e.type = 'ref' ORDER BY e.clock", (entry,)):
        if type_ in rows:
            a = json.loads(attrs or "{}")
            nodes[dst] = {"id": dst, "type": "row", "kind": type_, "state": state, "label": a.get("label", ""),
                          "title": entry_api.title(g, dst, a.get("label", "")), "mark": bool(a.get("bookmark"))}
    links: list[dict[str, Any]] = []
    ids = list(nodes)
    for at in range(0, len(ids), 400):  # within SQLite's bound on the number of parameters
        part = ids[at:at + 400]
        marks = ", ".join("?" * len(part))
        for src, dst in g.db.execute(f"SELECT src, dst FROM k_edges WHERE type = ? AND src IN ({marks})", (DEP_EDGE, *part)):
            if dst in nodes:
                links.append({"s": src, "t": dst, "kind": "basis"})
        for src, tag in g.db.execute(f"SELECT src, dst FROM k_edges WHERE type = 'tagged' AND src IN ({marks})", part):
            if not tag.startswith(HIDDEN_TAGS):
                nodes.setdefault(tag, {"id": tag, "type": "tag", "title": entry_api.title(g, tag)})
                links.append({"s": src, "t": tag, "kind": "tag"})
    return {"id": entry, "nodes": list(nodes.values()), "links": links}


def node(g: Graph, node_id: str) -> dict[str, Any]:
    """One node: what it is, what it says, and how many links of each type leave and reach it."""
    n = g.get_node(node_id)
    if n is None:
        raise ApiError(404, "not_found", f"no node {node_id!r}")
    count = lambda col: dict(g.db.execute(  # noqa: E731
        f"SELECT type, COUNT(*) FROM k_edges WHERE {col} = ? GROUP BY type ORDER BY type", (node_id,)))
    text = n["content"] or ""
    return {"id": node_id, "type": n["type"], "state": n["state"], "author": n["author"], "title": entry_api.title(g, node_id),
            "name": (n["attrs"] or {}).get("xref", ""), "content": text[:CONTENT], "cut": len(text) > CONTENT,
            "out": count("src"), "in": count("dst")}


def install(m: Any, *, stores: Callable[[str], Handbook], who: Callable[[Request], str | None], public_url: str,
            lock: Any) -> None:
    """Register the graph's routes on the MCP server `m` (remote.build)."""
    from urllib.parse import urlparse

    origin = "{0.scheme}://{0.netloc}".format(urlparse(public_url))
    api = endpoint(origin=origin, user_errors=(HandbookError,))

    def route(path: str) -> Callable[..., Any]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            m.custom_route(PREFIX + path, methods=["GET"])(api(fn))
            return fn
        return deco

    async def read(request: Request, fn: Callable[[Graph], Any]) -> Any:
        uid = who(request)
        if uid is None:
            raise unauthorized()

        def run() -> Any:
            with lock:  # the store is one connection: a reading takes its turn among the tool calls
                return fn(runtime.attach(stores(uid)).g)
        return await anyio.to_thread.run_sync(run)

    @route("/graph")
    async def graph(request: Request) -> Any:
        return await read(request, overview)

    @route("/graph/entry")
    async def graph_entry(request: Request) -> Any:
        return await read(request, lambda g: opened(g, request.query_params.get("id", "")))

    @route("/node")
    async def one_node(request: Request) -> Any:
        return await read(request, lambda g: node(g, request.query_params.get("id", "")))
