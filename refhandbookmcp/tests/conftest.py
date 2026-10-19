<<<<<<< HEAD:refhandbookmcp/tests/conftest.py
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
=======
"""Projection harness: after every sealed write to a ledger anywhere in the suite, the kernel graph
must hold that ledger exactly (the export rebuilt from the graph equals the export).
>>>>>>> 91a05f3 (Make the kernel the only judge):tests/conftest.py

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
<<<<<<< HEAD:refhandbookmcp/tests/conftest.py
    if DIFF and STATS["compared"]:
        from refhandbook.kernel.packages.research import RULES

        gates = {r["id"] for r in RULES if r["phase"] != "derive"}
        idle = sorted(gates - STATS["fired"])
        terminalreporter.write_line(f"kernel differential: {STATS['compared']} ledger states matched the legacy results; "
                                    f"{len(gates) - len(idle)}/{len(gates)} gate rules fired"
                                    + (f" (never: {', '.join(idle)})" if idle else ""))
>>>>>>> 9488cd3 (Add the scope-graph kernel beside the legacy stores):tests/conftest.py
=======
    if CHECK and STATS["checked"]:
        terminalreporter.write_line(f"projection: {STATS['checked']} sealed ledger states matched their rows")
>>>>>>> 91a05f3 (Make the kernel the only judge):tests/conftest.py
