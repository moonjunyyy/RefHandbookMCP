"""Entry nodes and their refs: the write path of the entry-node structure (docs/entry-graph.md §2 and §8,
stage 2, first slice). An entry node is a topic; what belongs to it is what it routes to, one `ref` per
route, labelled with the name the node has there and bookmarked when the entry puts it first. A tag is a node
of its own, attached by a `tagged` edge, so a tag's reverse refs are everything that carries it.

Every write is recorded as its writer's: a tool call is the model's. The ledgers as they are stay
untouched; a ref to one of their rows reaches the row's node (its nid) and survives the ledger being drawn
again. No MCP import here, so the server and its CLI run the same code (as research_api)."""

from __future__ import annotations

import json
import random
import re
import secrets
from typing import Annotated, Any, Literal

from pydantic import Field

from . import research_api
from .kernel.graph import ID_RE, Graph
from .store import HandbookError

ACTOR = "model"  # a tool call is the model's (docs/kernel.md, Authority); the site's own writes will pass "user"


class EntryError(HandbookError):
    """A request the caller can fix. A HandbookError, so the server passes its text on as it is."""


def _g() -> Graph:
    return research_api.R().k.g


def _node(g: Graph, node_id: str) -> dict[str, Any]:
    n = g.get_node(node_id)
    if n is None:
        raise EntryError(f"no node {node_id!r}")
    return n


def _entry(g: Graph, node_id: str) -> dict[str, Any]:
    n = _node(g, node_id)
    if n["type"] != "entry":
        raise EntryError(f"{node_id!r} is a {n['type']}, not an entry node: a ref starts from an entry node")
    return n


def _ref(g: Graph, entry: str, node: str) -> dict[str, Any] | None:
    return next(iter(g.edges(src=entry, type_="ref", dst=node)), None)


def tag_id(name: str) -> str:
    """A tag's node id from its name: one tag per name, case and spacing aside."""
    t = re.sub(r"\s+", "-", name.strip().lower())
    if not t or not ID_RE.match("tag:" + t):
        raise EntryError(f"bad tag {name!r}: letters, digits and . _ : @ # / + - only")
    return "tag:" + t


def entry_node(
    title: Annotated[str, Field(description="The topic, as a reader names it: one line.")],
    id: Annotated[str, Field(description="An entry node to retitle; empty makes a new one.")] = "",
    question: Annotated[str, Field(description="The question the topic answers (a ledger's question); optional.")] = "",
) -> str:
    """Make an entry node (a topic to route from), or retitle one. Returns its id."""
    g = _g()
    with g.tx():
        if id:
            _entry(g, id)
            g.update_node(id, actor=ACTOR, content=title, attrs={"question": question} if question else None)
            return f"entry {id}: {title}"
        nid = "n:" + secrets.token_hex(16)
        g.tick()  # each write is an event of its own: "latest" orders links by when they were made
        g.put_node(nid, "entry", actor=ACTOR, content=title, attrs={"question": question} if question else {})
    return f"entry {nid}: {title}"


def ref(
    entry: Annotated[str, Field(description="The entry node the route starts from.")],
    node: Annotated[str, Field(description="Any node: a ledger row's (its nid), a card's (card:<id>), an entry's, a tag's.")],
    label: Annotated[str, Field(description="The name the node has in this entry (E3, a short title); optional.")] = "",
) -> str:
    """Route an entry to a node: one ref, labelled with the name the node has there. Nothing is copied.
    Making an existing ref again replaces its label and keeps its bookmark and when it was made."""
    g = _g()
    with g.tx():
        _entry(g, entry)
        _node(g, node)
        old = _ref(g, entry, node)
        if old is not None:
            g.set_edge_attrs(entry, "ref", node, actor=ACTOR, attrs={**old["attrs"], "label": label})
            return f"ref {entry} -> {node}: label {label!r}"
        g.tick()
        g.link(entry, "ref", node, actor=ACTOR, attrs={"label": label} if label else {})
    return f"ref {entry} -> {node}" + (f" ({label})" if label else "")


def unref(
    entry: Annotated[str, Field(description="The entry node.")],
    node: Annotated[str, Field(description="The node it routes to.")],
) -> str:
    """Take a route out of an entry. The node itself stays."""
    g = _g()
    with g.tx():
        _entry(g, entry)
        if not g.unlink(entry, "ref", node, actor=ACTOR):
            raise EntryError(f"no ref {entry} -> {node}")
    return f"unref {entry} -> {node}"


def tag(
    node: Annotated[str, Field(description="Any node: a row's, a card's, an entry's.")],
    name: Annotated[str, Field(description="The keyword; one tag per name, case and spacing aside.")],
    remove: Annotated[bool, Field(description="Take the tag off instead.")] = False,
) -> str:
    """Attach a keyword to a node, or take it off. The tag is a node: everything carrying it is its reverse refs."""
    g = _g()
    t = tag_id(name)
    with g.tx():
        _node(g, node)
        if remove:
            if not g.unlink(node, "tagged", t, actor=ACTOR):
                raise EntryError(f"{node} does not carry {name!r}")
            return f"untag {node}: {name}"
        if g.get_node(t) is None:
            g.put_node(t, "tag", actor=ACTOR, content=name.strip())
        if g.edges(src=node, type_="tagged", dst=t):
            return f"{node} already carries {name!r}"
        g.tick()
        g.link(node, "tagged", t, actor=ACTOR)
    return f"tag {node}: {name} ({t})"


def bookmark(
    entry: Annotated[str, Field(description="The entry node whose ref to bookmark.")],
    node: Annotated[str, Field(description="The node the ref reaches.")],
    on: Annotated[bool, Field(description="False takes the bookmark off.")] = True,
) -> str:
    """Bookmark a ref of an entry (it comes first when the entry's refs are listed by bookmark), or take the
    bookmark off. Only this entry's ref is marked: the same node may be a bookmark in one entry and not in another."""
    g = _g()
    with g.tx():
        _entry(g, entry)
        old = _ref(g, entry, node)
        if old is None:
            raise EntryError(f"no ref {entry} -> {node}: make the ref first")
        attrs = {k: v for k, v in old["attrs"].items() if k != "bookmark"} | ({"bookmark": True} if on else {})
        g.set_edge_attrs(entry, "ref", node, actor=ACTOR, attrs=attrs)
    return f"{'bookmark' if on else 'unbookmark'} {entry} -> {node}"


# where the nodes delete_node refuses are deleted instead
_DELETED_ELSEWHERE = {
    "card": "a card is deleted with delete_entry",
    "ledger": "a ledger is deleted with research_ledger_delete",
    "memo": "a memo is dropped with memo(action='drop')",
}


def _links(g: Graph, node: str, col: str) -> dict[str, int]:
    return dict(g.db.execute(f"SELECT type, COUNT(*) FROM k_edges WHERE {col} = ? GROUP BY type ORDER BY type", (node,)))


def delete_node(
    node: Annotated[str, Field(description="An entry node's id, or a tag's (tag:<name>).")],
    force: Annotated[bool, Field(description="Delete it together with the links it still has; what they reach stays.")] = False,
) -> str:
    """Delete an entry node, or a tag. One that still has links (an entry's routes and tags, another entry's
    route to it, the nodes carrying a tag) is refused with their counts: take them off first (unref, tag with
    remove=True), or pass force=True to delete it with them. The nodes it reached stay as they are. Only your
    own nodes; a ledger row, a card or a ledger is deleted where it lives, not here. It cannot be undone."""
    g = _g()
    with g.tx():
        n = _node(g, node)
        if n["type"] not in ("entry", "tag"):
            row = g.db.execute("SELECT 1 FROM k_type_class WHERE type = ? AND class = 'row'", (n["type"],)).fetchone()
            where = _DELETED_ELSEWHERE.get(n["type"]) or (
                "a ledger row is closed in its ledger, by its status" if row else "it is removed by what made it")
            raise EntryError(f"REFUSED: {node!r} is a {n['type']}, not an entry node or a tag: {where}. Nothing was deleted.")
        out, inn = _links(g, node, "src"), _links(g, node, "dst")
        if (out or inn) and not force:
            said = "; ".join(f"{way}: " + ", ".join(f"{t} {c}" for t, c in links.items())
                             for way, links in (("out", out), ("in", inn)) if links)
            raise EntryError(f"REFUSED: {n['type']} {node} still has links ({said}). Take them off (unref, tag with "
                             "remove=True), or delete_node(node, force=True) deletes it with them; what they reach "
                             "stays. Nothing was deleted.")
        name = title(g, node)
        ledgers = [e["dst"] for e in g.edges(src=node, type_="ref")
                   if (m := g.get_node(e["dst"])) is not None and m["type"] == "ledger"]
        g.tick()
        g.delete_node(node, actor=ACTOR)  # the kernel's rule: the model deletes only its own nodes; edges go with it
        g.log(ACTOR, "node.delete", node, type=n["type"], title=name, links_out=out, links_in=inn)
    gone = sum(out.values()) + sum(inn.values())
    return (f"deleted {n['type']} {node}: {name}" + (f" (with {gone} link{'' if gone == 1 else 's'})" if gone else "")
            + "".join(f"\nledger {led} is no longer routed to by this entry" for led in ledgers))


def card_entries(g: Graph, card: str) -> list[tuple[str, list[str]]]:
    """The entries that route to a card, each with the ledgers it stands for: (title, [ledger ids]).
    Read from the entries' refs, so a card says where the work it describes is entered without a link
    of its own; a card no entry routes to has none."""
    out = []
    for (src,) in g.db.execute("SELECT src FROM k_edges WHERE dst = ? AND type = 'ref' ORDER BY clock",
                               (f"card:{card}",)).fetchall():
        n = g.get_node(src)
        if n is None or n["type"] != "entry":
            continue
        ledgers = [d for (d,) in g.db.execute("SELECT dst FROM k_edges WHERE src = ? AND type = 'ref' ORDER BY clock",
                                              (src,)).fetchall()
                   if (m := g.get_node(d)) is not None and m["type"] == "ledger"]
        out.append((title(g, src), ledgers))
    return out


# ── reading (stage 2, second slice): the same two calls for every node — a card's, a ledger row's, an entry's ──

HEAD = 60  # how much of a node's content its title shows


def title(g: Graph, node_id: str, label: str = "") -> str:
    """What a node is called in a list: a card by its title, a ledger row by its name there (the ref's label, else
    ledger/id) and the first words of its content, an entry or a tag by its own words. Derived, never stored."""
    n = g.get_node(node_id)
    if n is None:
        return "(gone)"
    a = n["attrs"] or {}
    if n["type"] == "missing":
        return f"missing: {a.get('xref', node_id)}"
    text = (n["content"] or "").strip()
    head = text.splitlines()[0][:HEAD] if text else ""
    name = label or a.get("xref") or ""
    return f"{name} · {head}" if name and head else head or name or f"{n['type']} {node_id}"


def _type_names(g: Graph, types: list[str]) -> set[str]:
    """Edge type names for what was asked: a type's name, or its inverse's (ref_of finds ref)."""
    asked = set(types)
    inv = {r[0] for r in g.db.execute(
        f"SELECT name FROM k_types WHERE kind = 'edge' AND inverse IN ({','.join('?' * len(asked))})", tuple(asked))}
    return asked | inv


def refs(
    node: Annotated[str, Field(description="Any node id: an entry's, a ledger row's (its nid), a card's (card:<id>), a tag's.")],
    direction: Annotated[Literal["out", "in"], Field(description="out: its refs; in: its reverse refs (what reaches it).")] = "out",
    order: Annotated[Literal["latest", "random", "bookmarked"], Field(
        description="latest: when each link was made, newest first; random: shuffled by a seed (returned, pass it "
                    "back to repeat); bookmarked: the entry's bookmarked refs first, then latest.")] = "latest",
    k: Annotated[int, Field(ge=1, le=200, description="How many to list.")] = 10,
    cursor: Annotated[str, Field(description="Where to go on from: the 'next' a previous call printed.")] = "",
    types: Annotated[list[str] | None, Field(description="Only these link types (ref, tagged, dep_ref, contains, a card relation …); inverse names work too.")] = None,
    entry: Annotated[str, Field(description="The entry whose bookmarks and labels apply (default: the node itself when it is an entry).")] = "",
    seed: Annotated[int, Field(description="For order=random: 0 draws one; the same seed lists the same order.")] = 0,
) -> str:
    """List a node's refs (or reverse refs) as (id, title) pairs, grouped by link type, k at a time. Reading
    only: nothing in the graph changes. Open one with open_node, or list its refs in turn."""
    g = _g()
    n = _node(g, node)
    near, far = ("src", "dst") if direction == "out" else ("dst", "src")
    rows = [(r[0], r[1], json.loads(r[2] or "{}"), r[3]) for r in g.db.execute(
        f"SELECT {far}, type, attrs, clock FROM k_edges WHERE {near} = ?", (node,))]
    if types:
        names = _type_names(g, types)
        rows = [r for r in rows if r[1] in names]
    ctx = entry or (node if n["type"] == "entry" else "")
    if ctx:
        _entry(g, ctx)
    labels = {e["dst"]: e["attrs"] for e in g.edges(src=ctx, type_="ref")} if ctx else {}
    latest = sorted(rows, key=lambda r: (-r[3], r[0], r[1]))
    if order == "random":
        seed = seed or secrets.randbelow(2 ** 31 - 1) + 1
        random.Random(f"{node}|{direction}|{seed}").shuffle(latest)
    elif order == "bookmarked":
        latest.sort(key=lambda r: not labels.get(r[0], {}).get("bookmark"))  # stable: latest within each part
    start = int(cursor[2:]) if cursor.startswith("o:") and cursor[2:].isdigit() else 0
    page = latest[start:start + k]
    head = f"refs {node} {direction} · {order}" + (f" · seed {seed}" if order == "random" else "")
    head += f" · {start + 1}-{start + len(page)} of {len(latest)}" if page else f" · none of {len(latest)}"
    groups: dict[str, list[str]] = {}
    for other, typ, attrs, _clock in page:
        label = (attrs.get("label") if typ == "ref" and direction == "out" else "") or labels.get(other, {}).get("label", "")
        mark = " *" if labels.get(other, {}).get("bookmark") else ""
        groups.setdefault(typ, []).append(f"  {other}  {title(g, other, label)}{mark}")
    out = [head] + [line for typ, items in groups.items() for line in (f"{typ} ({len(items)})", *items)]
    if start + k < len(latest):
        out.append(f"next: cursor o:{start + k}" + (f" with seed {seed}" if order == "random" else ""))
    return "\n".join(out)


def open_node(
    node: Annotated[str, Field(description="Any node id.")],
) -> str:
    """Open one node: what it is, who wrote it, its content, and how many links of each type leave and reach it
    (list them with refs). Reading only."""
    g = _g()
    n = _node(g, node)
    a = n["attrs"] or {}
    count = lambda col: ", ".join(f"{t} {c}" for t, c in g.db.execute(  # noqa: E731
        f"SELECT type, COUNT(*) FROM k_edges WHERE {col} = ? GROUP BY type ORDER BY type", (node,))) or "none"
    lines = [f"{n['type']} {node}" + (f" · {n['state']}" if n.get("state") else "") + f" · written by {n['author']}",
             title(g, node)]
    text = (n["content"] or "").strip()
    if text and text != title(g, node).split(" · ", 1)[-1]:
        lines += ["", text]
    shown = {k: v for k, v in a.items() if v not in (None, "", [], {})}
    if shown:
        lines += ["", "attrs: " + json.dumps(shown, ensure_ascii=False)[:600]]
    lines += ["", f"refs out: {count('src')}", f"refs in: {count('dst')}"]
    return "\n".join(lines)


READ_TOOLS = [refs, open_node]
WRITE_TOOLS = [entry_node, ref, unref, tag, bookmark]
DELETE_TOOLS = [delete_node]
