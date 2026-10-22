"""The scope-graph kernel: typed nodes and edges, state classes, authority, rules and scopes.

See docs/kernel.md for the design. The legacy handbook and research ledger keep working on their
own tables; `migrate` maps them onto this graph.
"""

from .graph import Conflict, Forbidden, Graph, KernelError
from .rules import Finding, Program, evaluate, parse
from .scopes import ScopeRefused, carry, close, detach, findings, open_scope, touch

__all__ = [
    "Conflict", "Finding", "Forbidden", "Graph", "KernelError", "Program", "ScopeRefused",
    "carry", "close", "detach", "evaluate", "findings", "open_scope", "parse", "touch",
]
