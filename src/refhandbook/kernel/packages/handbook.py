"""The handbook cards as a kernel package: a card node, one step node per card item chained by
`next`, a step's GO TO as a `continues_to` edge, and the relation vocabulary as edge types."""

from __future__ import annotations

import hashlib
import json

from ..graph import Graph

PKG = "handbook"

# (name, kind, define_type keywords): the vocabulary as data, so that its digest is its version
TYPES: list[tuple[str, str, dict[str, str]]] = [
    ("card", "node", {"description": "A handbook card: condition, objective, steps."}),
    ("step", "node", {"description": "One line of a card, in order."}),
    ("has_step", "edge", {"inverse": "step_of", "description": "A card's lines."}),
    ("next", "edge", {"inverse": "previous", "description": "The line that follows."}),
    ("continues_to", "edge", {"inverse": "continued_from",
                              "description": "A step in the source sends the reader to the target."}),
]


def digest() -> str:
    """The package's version: a hash of its vocabulary (runtime.upgrade_packages installs on a change)."""
    return hashlib.sha256(json.dumps([PKG, TYPES], sort_keys=True).encode()).hexdigest()[:16]


def install(g: Graph, actor: str = "kernel") -> None:
    with g.tx():
        for name, kind, kw in TYPES:
            g.define_type(name, kind, actor=actor, pkg=PKG, **kw)
