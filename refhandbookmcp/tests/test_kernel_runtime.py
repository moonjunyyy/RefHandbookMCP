"""The kernel in the server: migration on first open, the mirror, the switch, divergence handling."""

import json
import sqlite3

import pytest

from refhandbook import Handbook, research, research_api
from refhandbook.kernel import migrate, runtime, verify
from refhandbook.research import Research

from test_research import tok


def legacy_store(path):
    """A store written by 0.6.0 (no kernel tables): one ledger with a closed turn and a log."""
    hb = Handbook(path)
    research.ensure_cards(hb)
    r = Research(hb)
    r.init("geo", "vector EL")
    t = tok(r.begin("geo", 1))
    out = r.add("geo", t, "U", "derive it", "user", "active")
    t = tok(out)
    t = tok(r.add("geo", t, "A", "flat metric", "user", "on"))
    t = tok(r.push("geo", t, "await the user", "USER", "U1"))
    t = tok(r.set("geo", t, "U1", "status", "answered"))
    r.end("geo", t, 1)
    hb.save_entry(title="Disk full", condition="ENOSPC", items=["free space"])
    hb.close()


def tables(path):
    db = sqlite3.connect(path)
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_first_open_backs_up_migrates_and_verifies(tmp_path):
    path = tmp_path / "u.db"
    legacy_store(path)
    assert "k_meta" not in tables(path)
    hb = Handbook(path)
    m = runtime.attach(hb)
    assert m.status == "active"
    backup = tmp_path / "u.db.pre-kernel"
    assert backup.exists() and "k_meta" not in tables(backup) and "rl_rows" in tables(backup)
    r = Research(hb)
    assert verify.compare(r, m.g, "geo") == []  # the carried log included
    assert m.g.node("card:disk-full")["content"] == "Disk full"
    hb.close()
    hb = Handbook(path)  # the second open does not migrate again or back up again
    assert runtime.attach(hb).status == "active"
    assert sum(1 for e in hb.db.execute("SELECT event FROM k_log WHERE event LIKE 'migration:%'")) == 1


def test_the_mirror_follows_every_write_and_keeps_the_log(tmp_path):
    path = tmp_path / "u.db"
    legacy_store(path)
    hb = Handbook(path)
    r = runtime.research_for(hb)
    t = tok(r.begin("geo", 2))
    t = tok(r.add("geo", t, "U", "go on", "user", "active"))
    t = tok(r.set("geo", t, "U2", "status", "answered"))
    r.end("geo", t, 2)
    assert verify.compare(r, r.k.g, "geo") == []
    events = [e[0] for e in hb.db.execute("SELECT event FROM k_log WHERE ref = 'geo' AND actor = 'legacy' ORDER BY seq")]
    assert events == [e[0] for e in hb.db.execute("SELECT msg FROM rl_log WHERE ledger = 'geo' ORDER BY seq")]
    hb.save_entry(id="disk-full", title="Disk full", condition="ENOSPC or EDQUOT")
    assert r.k.g.node("card:disk-full")["attrs"]["condition"] == "ENOSPC or EDQUOT"


def test_rename_copy_delete_and_a_dry_run_import_reach_the_mirror(tmp_path):
    hb = Handbook(tmp_path / "u.db")
    r = runtime.research_for(hb)
    r.init("a", "q")
    r.copy("a", "b")
    r.rename("a", "c")
    r.delete("b", confirm="b")
    data = r.export("c")
    r.import_(data, as_ledger="d", dry_run=True)
    assert migrate.ledgers_in_graph(r.k.g) == ["c"]  # the dry run's projection rolled back with it
    assert verify.compare(r, r.k.g, "c") == []


def test_a_divergence_at_migration_keeps_the_legacy_gates(tmp_path, monkeypatch):
    path = tmp_path / "u.db"
    legacy_store(path)
    monkeypatch.setattr(verify, "compare", lambda r, g, L, include_log=True: ["synthetic difference"])
    hb = Handbook(path)
    m = runtime.attach(hb)
    assert m.status.startswith("legacy: geo: synthetic difference")
    monkeypatch.setattr(verify, "check", lambda *a: pytest.fail("the kernel must not be consulted"))
    runtime.research_for(hb).check("geo")


def test_the_switch_turns_the_kernel_off(tmp_path, monkeypatch):
    monkeypatch.setenv("RHB_KERNEL", "0")
    path = tmp_path / "u.db"
    legacy_store(path)
    hb = Handbook(path)
    assert runtime.attach(hb) is None and type(runtime.research_for(hb)) is Research
    assert "k_meta" not in tables(path) and not (tmp_path / "u.db.pre-kernel").exists()


def test_a_divergence_in_service_is_logged_and_the_kernel_decides(tmp_path, monkeypatch):
    monkeypatch.delenv("RHB_KERNEL_STRICT")
    hb = Handbook(tmp_path / "u.db")
    r = runtime.research_for(hb)
    r.init("geo", "q")
    legacy_check = Research._legacy_check
    monkeypatch.setattr(Research, "_legacy_check",
                        lambda self, L: (legacy_check(self, L)[0] + ["X1: only legacy says so"], []))
    assert r.check("geo") == ([], [])
    (event,) = [e[0] for e in hb.db.execute("SELECT event FROM k_log WHERE event LIKE 'divergence:%'")]
    assert "X1: only legacy says so" in event


def test_remote_stores_attach_on_open(tmp_path):
    from refhandbook.remote import UserStores

    hb = UserStores(tmp_path)("moonny")
    assert hb._kernel.active()
    assert (tmp_path / "users" / "moonny.db.pre-kernel").exists()


def test_tools_run_on_the_kernel_engine(tmp_path):
    hb = Handbook(tmp_path / "u.db")
    research_api.bind(hb)
    assert isinstance(research_api.R(), runtime.KernelResearch)
    research_api.research_ledgers(action="init", ledger="geo", question="q")
    out = research_api.research_begin("geo", 1)
    assert "OBLIGATIONS THIS TURN" in out
    assert json.loads(research_api.research_ledgers(action="export", ledger="geo"))["ledger"]["id"] == "geo"
