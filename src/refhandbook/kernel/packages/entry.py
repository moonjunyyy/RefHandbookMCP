"""Entry nodes as a kernel package (docs/entry-graph.md §2): an entry node is a topic, and what belongs
to it is what it routes to — one `ref` edge per route, labelled with the name the node has there. A tag is a
node of its own, attached by a `tagged` edge. Both edges are navigation: they find things, they are never a
basis (the basis checks read `dep_ref` alone). Written by whoever writes them; the package itself is the
kernel's."""

from __future__ import annotations

from ..graph import Graph

PKG = "entry"


def install(g: Graph, actor: str = "kernel") -> None:
    with g.tx():
        g.define_type("entry", "node", actor=actor, pkg=PKG,
                      description="A topic to route from: what belongs to it is what its refs reach.")
        g.define_type("tag", "node", actor=actor, pkg=PKG,
                      description="A keyword: everything carrying it is reached by its reverse refs.")
        g.define_type("ref", "edge", actor=actor, pkg=PKG, inverse="ref_of", classes=["navigation"],
                      description="An entry routes to a node (attrs: label, the node's name there; bookmark).")
        g.define_type("tagged", "edge", actor=actor, pkg=PKG, inverse="tag_of", classes=["navigation"],
                      description="A node carries a tag.")
