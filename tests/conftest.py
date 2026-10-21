"""Projection harness: after every sealed write to a ledger anywhere in the suite, the kernel graph
must hold that ledger exactly (the export rebuilt from the graph equals the export).

The kernel is the only judge (research.Research asks its rules for check, obligations and end
refusals), so the legacy suites test the kernel's judgments directly. This hook adds the data
side: no write may leave the graph behind or different from the rl_* tables it is projected from.

Set RHB_PROJECTION_CHECK=0 to run the suite without it.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from refhandbook import research
from refhandbook.kernel import Graph, migrate, verify

CHECK = os.environ.get("RHB_PROJECTION_CHECK", "1") != "0"
STATS: dict = {"checked": 0}
_TEMPLATE: list[sqlite3.Connection] = []


def fresh_graph() -> Graph:
    """A graph with the packages installed (copied from a template: installing takes a while)."""
    if not _TEMPLATE:
        db = sqlite3.connect(":memory:", check_same_thread=False)
        migrate.install(Graph(db))
        _TEMPLATE.append(db)
    db = sqlite3.connect(":memory:", check_same_thread=False)
    _TEMPLATE[0].backup(db)
    return Graph(db)


def projected(r: research.Research, ledger: str) -> None:
    if r.k is None or r.k.meta(f"quarantine:{ledger}"):
        return
    if not r.db.execute("SELECT 1 FROM rl_ledgers WHERE id = ?", (ledger,)).fetchone():
        assert r.k.g.get_node(ledger) is None, f"deleted ledger {ledger!r} still has an image"
        return
    diffs = verify.roundtrip(r, r.k.g, ledger)
    assert not diffs, f"projection of {ledger!r} differs from its rows: {diffs}"
    STATS["checked"] += 1


@pytest.fixture(autouse=True)
def projection_check(monkeypatch):
    if CHECK:
        sealed = research.Research._sealed

        def check(self, ledger):
            sealed(self, ledger)
            projected(self, ledger)

        monkeypatch.setattr(research.Research, "_sealed", check)
    yield


def pytest_terminal_summary(terminalreporter):
    if CHECK and STATS["checked"]:
        terminalreporter.write_line(f"projection: {STATS['checked']} sealed ledger states matched their rows")
