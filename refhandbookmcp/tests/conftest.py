<<<<<<< HEAD:refhandbookmcp/tests/conftest.py
"""The tests run as the m00nny site (the realm the fakes use); every other fact derives from it."""
import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("PORTAL_REALM", "M00NNY.KR")

# The repository's site file, copied alone: a host's deploy/site.local.toml must not change the tests.
SITE = Path(tempfile.mkdtemp(prefix="site-")) / "site.toml"
shutil.copy(Path(__file__).parent.parent / "deploy" / "site.toml", SITE)
=======
"""Differential harness: the kernel must reproduce the legacy research ledger exactly.

After every sealed write to a legacy ledger (every research_* call that changes it, begin, end,
import, rename) the ledger is exported, loaded into a fresh kernel graph with the research package,
and compared with the legacy results:

  1. round trip — rebuilding the export from the graph returns it unchanged;
  2. check()    — the package's check rules give the same errors and warnings, word for word;
  3. obligations — the obligation rules name the same (kind, ref, source) items as research_begin;
  4. end        — while a turn is open, closing its turn scope is blocked by the same items that
                  research_end refuses on (with and without an idle reason), check errors included.

Set RHB_KERNEL_DIFF=0 to run the legacy suite without it.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from refhandbook import research
from refhandbook.kernel import Graph, evaluate, findings, migrate

DIFF = os.environ.get("RHB_KERNEL_DIFF", "1") != "0"
STATS: dict = {"compared": 0, "fired": set()}
_TEMPLATE: list[sqlite3.Connection] = []

OBLIGATION_KIND = {"rs_o_pending": "pending", "rs_o_k": "k", "rs_o_directive": "directive", "rs_o_rejudge": "rejudge",
                   "rs_o_stale_verdict": "stale_verdict", "rs_o_doc_plan": "doc_plan", "rs_o_doc_behind": "doc_behind"}
BLOCKER_KIND = {"rs_b_pending": "pending", "rs_b_running": "running", "rs_b_no_continuation": "no_continuation",
                "rs_b_directive": "directive", "rs_b_no_directive": "no_directive", "rs_b_doc_plan": "doc_plan"}
TWO_REFS = {"pending"}  # (hit, src); the others carry one ref or none


def fresh_graph() -> Graph:
    if not _TEMPLATE:
        db = sqlite3.connect(":memory:", check_same_thread=False)
        migrate.install(Graph(db))
        _TEMPLATE.append(db)
    db = sqlite3.connect(":memory:", check_same_thread=False)
    _TEMPLATE[0].backup(db)
    return Graph(db)


def canon(export: dict) -> dict:
    tables = {}
    for t, rows in export["tables"].items():
        rows = [{k: v for k, v in r.items() if not (t == "rl_log" and k == "seq")} for r in rows]
        tables[t] = sorted(rows, key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return {"ledger": export["ledger"], "tables": tables}


def _items(fs, kinds) -> set[tuple]:
    out = set()
    for f in fs:
        if f.rule in kinds:
            k = kinds[f.rule]
            if k in TWO_REFS:
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


def compare(r: research.Research, ledger: str) -> None:
    data = r.export(ledger)
    g = fresh_graph()
    L = migrate.ledger_to_graph(g, data)
    where = f"ledger {ledger!r} at turn {data['ledger']['turn']}"

    back = migrate.ledger_from_graph(g, L)
    assert canon(back) == canon(data), f"round trip changed {where}"

    errors, warnings = r.check(ledger)
    kf = evaluate(g, "check", L, "ledger")
    STATS["fired"] |= {f.rule for f in kf}
    assert sorted({f.message for f in kf if f.severity == "block"}) == sorted(set(errors)), f"check errors differ: {where}"
    assert sorted({f.message for f in kf if f.severity == "warn"}) == sorted(set(warnings)), f"check warnings differ: {where}"

    legacy_ob = {(k, ref, src) for k, ref, src, _ in r.obligation_items(ledger)}
    ko = evaluate(g, "obligation", L, "ledger")
    STATS["fired"] |= {f.rule for f in ko}
    assert _items(ko, OBLIGATION_KIND) == legacy_ob, f"obligations differ: {where}"

    lg = data["ledger"]
    if lg["open"]:
        for idle in ("", "nothing was asked"):
            t = migrate.ensure_turn(g, L, lg["turn"], idle)
            kb = findings(g, t)
            STATS["fired"] |= {f.rule for f in kb}
            kernel_b = _items(kb, BLOCKER_KIND)
            legacy_b = {(k, ref, src) for k, ref, src, _ in r.blockers(ledger, lg["turn"], idle)}
            assert kernel_b == legacy_b, f"end blockers differ (idle={idle!r}): {where}\n kernel {sorted(kernel_b)}\n legacy {sorted(legacy_b)}"
    STATS["compared"] += 1


ENGINE_MODULES = {"test_research", "test_feedback"}


def pytest_generate_tests(metafunc):
    """The legacy research suites run twice: on the legacy engine, and on the engine whose gates the
    kernel decides (kernel.runtime.KernelResearch), so the kernel path meets every legacy expectation."""
    if "engine" in metafunc.fixturenames:
        params = ["legacy", "kernel"] if metafunc.module.__name__ in ENGINE_MODULES else ["legacy"]
        metafunc.parametrize("engine", params, indirect=True)


@pytest.fixture
def engine(request, monkeypatch):
    if request.param == "kernel":
        from refhandbook.kernel import runtime

        class KernelEngine(runtime.KernelResearch):
            def __init__(self, hb):
                super().__init__(hb, runtime.attach(hb))

        monkeypatch.setattr(request.module, "Research", KernelEngine)
    return request.param


@pytest.fixture(autouse=True)
def strict_kernel(monkeypatch):
    monkeypatch.setenv("RHB_KERNEL_STRICT", "1")


@pytest.fixture(autouse=True)
def kernel_differential(monkeypatch, engine):
    if DIFF:
        seal = research.Research._seal

        def sealed(self, ledger):
            token = seal(self, ledger)
            compare(self, ledger)
            return token

        monkeypatch.setattr(research.Research, "_seal", sealed)
    yield


def pytest_terminal_summary(terminalreporter):
    if DIFF and STATS["compared"]:
        from refhandbook.kernel.packages.research import RULES

        gates = {r["id"] for r in RULES if r["phase"] != "derive"}
        idle = sorted(gates - STATS["fired"])
        terminalreporter.write_line(f"kernel differential: {STATS['compared']} ledger states matched the legacy results; "
                                    f"{len(gates) - len(idle)}/{len(gates)} gate rules fired"
                                    + (f" (never: {', '.join(idle)})" if idle else ""))
>>>>>>> 9488cd3 (Add the scope-graph kernel beside the legacy stores):tests/conftest.py
