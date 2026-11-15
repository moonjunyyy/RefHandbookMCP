"""Entry nodes as a kernel package (docs/entry-graph.md §2): an entry node is a topic, and what belongs
to it is what it routes to — one `ref` edge per route, labelled with the name the node has there. A tag is a
node of its own, attached by a `tagged` edge. Both edges are navigation: they find things, they are never a
basis (the basis checks read `dep_ref` alone). Written by whoever writes them; the package itself is the
kernel's."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..graph import Graph

PKG = "entry"

# (name, kind, define_type keywords): the vocabulary as data, so that its digest is its version
TYPES: list[tuple[str, str, dict[str, Any]]] = [
    ("entry", "node", {"description": "A topic to route from: what belongs to it is what its refs reach."}),
    ("tag", "node", {"description": "A keyword: everything carrying it is reached by its reverse refs."}),
    ("ref", "edge", {"inverse": "ref_of", "classes": ["navigation"],
                     "description": "An entry routes to a node (attrs: label, the node's name there; bookmark)."}),
    ("tagged", "edge", {"inverse": "tag_of", "classes": ["navigation"], "description": "A node carries a tag."}),
]


def digest() -> str:
    """The package's version: a hash of its vocabulary (runtime.upgrade_packages installs on a change)."""
    return hashlib.sha256(json.dumps([PKG, TYPES], sort_keys=True).encode()).hexdigest()[:16]


def install(g: Graph, actor: str = "kernel") -> None:
    with g.tx():
        for name, kind, kw in TYPES:
            g.define_type(name, kind, actor=actor, pkg=PKG, **kw)
