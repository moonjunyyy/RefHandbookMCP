"""The handbook cards as a kernel package: a card node, one step node per card item chained by
`next`, a step's GO TO as a `continues_to` edge, and the relation vocabulary as edge types."""

from __future__ import annotations

from ..graph import Graph

PKG = "handbook"


def install(g: Graph, actor: str = "kernel") -> None:
    with g.tx():
        g.define_type("card", "node", actor=actor, pkg=PKG, description="A handbook card: condition, objective, steps.")
        g.define_type("step", "node", actor=actor, pkg=PKG, description="One line of a card, in order.")
        g.define_type("has_step", "edge", actor=actor, pkg=PKG, inverse="step_of", description="A card's lines.")
        g.define_type("next", "edge", actor=actor, pkg=PKG, inverse="previous", description="The line that follows.")
        g.define_type("continues_to", "edge", actor=actor, pkg=PKG, inverse="continued_from",
                      description="A step in the source sends the reader to the target.")
