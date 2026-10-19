"""The research package's judgments, read off the kernel, and the projection's round-trip check.

  check       → (errors, warnings, findings)  the package's check rules on a ledger
  obligations → {(kind, ref, src)}            what a turn starts from (research_begin)
  blockers    → {(kind, ref, src)}            what keeps a turn from closing (research_end), with the
                                             ledger's check errors as ("check", message, "")
  roundtrip   → [differences]                 the ledger's export rebuilt from the graph vs the export
"""

from __future__ import annotations

import json
from typing import Any

from . import migrate
from .graph import Graph
from .rules import Finding, evaluate
from .scopes import findings

OBLIGATION_KIND = {"rs_o_pending": "pending", "rs_o_k": "k", "rs_o_directive": "directive", "rs_o_rejudge": "rejudge",
                   "rs_o_stale_verdict": "stale_verdict", "rs_o_doc_plan": "doc_plan", "rs_o_doc_behind": "doc_behind",
                   "rs_o_review": "review"}
BLOCKER_KIND = {"rs_b_pending": "pending", "rs_b_running": "running", "rs_b_no_continuation": "no_continuation",
                "rs_b_directive": "directive", "rs_b_no_directive": "no_directive", "rs_b_doc_plan": "doc_plan"}
TWO_REFS = {"pending", "review"}  # (ref, src); the others carry one ref or none
NO_REFS = {"no_continuation", "no_directive"}


def items(fs: list[Finding], kinds: dict[str, str]) -> set[tuple[str, str, str]]:
    out = set()
    for f in fs:
        if f.rule in kinds:
            k = kinds[f.rule]
            if k in TWO_REFS:
                out.add((k, str(f.values[0]), str(f.values[1])))
            elif k in NO_REFS:
                out.add((k, "", ""))
            else:
                out.add((k, str(f.values[0]), ""))
        elif f.severity == "block" and f.rule.startswith("rs_c_"):
            out.add(("check", f.message, ""))
        elif f.severity == "block":
            out.add(("other", f.rule, f.message))
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


def roundtrip(r: Any, g: Graph, L: str) -> list[str]:
    """Empty when the graph holds ledger L exactly: the export rebuilt from it equals the export."""
    data = r.export(L, include_log=False)
    back = migrate.ledger_from_graph(g, L, include_log=False)
    a, b = canon(data), canon(back)
    if a == b:
        return []
    diffs = [f"ledger fields differ: {sorted(k for k in set(a['ledger']) | set(b['ledger']) if a['ledger'].get(k) != b['ledger'].get(k))}"] \
        if a["ledger"] != b["ledger"] else []
    for t in sorted(set(a["tables"]) | set(b["tables"])):
        if a["tables"].get(t) != b["tables"].get(t):
            diffs.append(f"table {t} differs ({len(a['tables'].get(t, []))} rows vs {len(b['tables'].get(t, []))})")
    return diffs
