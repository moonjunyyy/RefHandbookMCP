"""Legacy ⇄ kernel equivalence, shared by the test harness and the server's migration.

Each function returns the same shape from both sides, so a caller compares sets:
  check      → (errors, warnings), the messages of research.Research.check
  obligations → {(kind, ref, src)} as research.Research.obligation_items
  blockers   → {(kind, ref, src)} as research.Research.blockers (check errors as ("check", msg, ""))
"""

from __future__ import annotations

import json
from typing import Any

from . import migrate
from .graph import Graph
from .rules import Finding, evaluate
from .scopes import findings

OBLIGATION_KIND = {"rs_o_pending": "pending", "rs_o_k": "k", "rs_o_directive": "directive", "rs_o_rejudge": "rejudge",
                   "rs_o_stale_verdict": "stale_verdict", "rs_o_doc_plan": "doc_plan", "rs_o_doc_behind": "doc_behind"}
BLOCKER_KIND = {"rs_b_pending": "pending", "rs_b_running": "running", "rs_b_no_continuation": "no_continuation",
                "rs_b_directive": "directive", "rs_b_no_directive": "no_directive", "rs_b_doc_plan": "doc_plan"}


def items(fs: list[Finding], kinds: dict[str, str]) -> set[tuple[str, str, str]]:
    out = set()
    for f in fs:
        if f.rule in kinds:
            k = kinds[f.rule]
            if k == "pending":
                out.add((k, f.values[0], f.values[1]))
            elif k in ("no_continuation", "no_directive"):
                out.add((k, "", ""))
            else:
                out.add((k, f.values[0], ""))
        elif f.severity == "block" and f.rule.startswith("rs_c_"):
            out.add(("check", f.message, ""))
        elif f.severity == "block":
            out.add(("unexpected", f.rule, f.message))
    return out


def check(g: Graph, L: str) -> tuple[list[str], list[str], list[Finding]]:
    fs = evaluate(g, "check", L, "ledger")
    errors = sorted({f.message for f in fs if f.severity == "block"})
    warnings = sorted({f.message for f in fs if f.severity == "warn"})
    return errors, warnings, fs


def obligations(g: Graph, L: str) -> set[tuple[str, str, str]]:
    return items(evaluate(g, "obligation", L, "ledger"), OBLIGATION_KIND)


def blockers(g: Graph, L: str, turn: int, idle: str = "") -> set[tuple[str, str, str]]:
    return items(findings(g, migrate.ensure_turn(g, L, turn, idle)), BLOCKER_KIND)


def canon(export: dict[str, Any]) -> dict[str, Any]:
    tables = {}
    for t, rows in export["tables"].items():
        rows = [{k: v for k, v in r.items() if not (t == "rl_log" and k == "seq")} for r in rows]
        tables[t] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return {"ledger": export["ledger"], "tables": tables}


def compare(r: Any, g: Graph, L: str, include_log: bool = True) -> list[str]:
    """Differences between the legacy ledger L (research.Research r) and its image in g. Empty
    means equivalent: round trip, check messages, obligations, and (if a turn is open) end blockers."""
    diffs = []
    data = r.export(L, include_log=include_log)
    if canon(migrate.ledger_from_graph(g, L, include_log=include_log)) != canon(data):
        diffs.append("round trip changed the export")
    from ..research import Research

    errors, warnings = r._legacy_check(L)  # the legacy computation, whatever subclass r is
    ke, kw, _ = check(g, L)
    if ke != sorted(set(errors)):
        diffs.append(f"check errors: kernel-only {sorted(set(ke) - set(errors))}, "
                     f"legacy-only {sorted(set(errors) - set(ke))}")
    if kw != sorted(set(warnings)):
        diffs.append(f"check warnings: kernel-only {sorted(set(kw) - set(warnings))}, "
                     f"legacy-only {sorted(set(warnings) - set(kw))}")
    lo = {(k, ref, src) for k, ref, src, _ in Research.obligation_items(r, L)}
    ko = obligations(g, L)
    if ko != lo:
        diffs.append(f"obligations: kernel-only {sorted(ko - lo)}, legacy-only {sorted(lo - ko)}")
    lg = data["ledger"]
    if lg["open"]:
        for idle in ("", "nothing was asked"):
            lb = {(k, ref, src) for k, ref, src, _ in Research.blockers(r, L, lg["turn"], idle)}
            kb = blockers(g, L, lg["turn"], idle)
            if kb != lb:
                diffs.append(f"end blockers (idle={idle!r}): kernel-only {sorted(kb - lb)}, legacy-only {sorted(lb - kb)}")
    return diffs
