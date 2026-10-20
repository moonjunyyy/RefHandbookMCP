"""The kernel in the server: migration on first open, quarantine, the projection, package upgrades."""

import json
import sqlite3
from pathlib import Path

import pytest

from refhandbook import Handbook, research, research_api
from refhandbook.kernel import migrate, runtime, verify
from refhandbook.kernel.packages import research as rs_pkg
from refhandbook.research import Research, ResearchError

from test_research import tok


def legacy_store(path, ledgers=("geo",)):
    """A store as 0.6.x left it: rl_* tables only, no kernel tables (made with the kernel, which
    judges the turns, then stripped of it)."""
    hb = Handbook(path)
    research.ensure_cards(hb)
    r = Research(hb)
    for L in ledgers:
        r.init(L, "vector EL")
        t = tok(r.begin(L))
        r.add(L, t, "U", "derive it", "user", "active")
        r.add(L, t, "A", "flat metric", "user", "on")
        r.push(L, t, "await the user", "USER", "U1")
        r.set(L, t, "U1", "status", "answered")
        r.end(L, t)
    hb.save_entry(title="Disk full", condition="ENOSPC", items=["free space"])
    hb.db.commit()
    hb.db.execute("PRAGMA foreign_keys = OFF")
    for (name,) in hb.db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'k\\_%' ESCAPE '\\'")\
            .fetchall():
        hb.db.execute(f"DROP TABLE {name}")
    hb.db.commit()
    hb.close()
    backup = Path(f"{path}.pre-kernel")
    if backup.exists():
        backup.unlink()


def tables(path):
    return {r[0] for r in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_first_open_backs_up_migrates_and_round_trips(tmp_path):
    path = tmp_path / "u.db"
    legacy_store(path)
    assert "k_meta" not in tables(path)
    hb = Handbook(path)
    r = Research(hb)
    assert r.k.schema() == 1 and r.k.meta("quarantine:geo") is None
    backup = tmp_path / "u.db.pre-kernel"
    assert backup.exists() and "k_meta" not in tables(backup) and "rl_rows" in tables(backup)
    assert verify.roundtrip(r, r.k.g, "geo") == []
    assert r.k.g.node("card:disk-full")["content"] == "Disk full"
    hb.close()
    hb = Handbook(path)  # a second open migrates nothing again
    Research(hb)
    assert sum(1 for _ in hb.db.execute("SELECT 1 FROM k_log WHERE event LIKE 'migration v1:%'")) == 1


def test_stores_from_0_7_0_are_recognised_as_schema_1(tmp_path):
    path = tmp_path / "u.db"
    legacy_store(path)
    hb = Handbook(path)
    m = runtime.attach(hb)
    with m.g.tx():
        m.set_meta("schema", None)  # 0.7.0 recorded only kernel_status
    hb._kernel = None
    del hb._kernel
    assert runtime.attach(hb).schema() == 1


def test_a_ledger_that_does_not_round_trip_is_quarantined_alone(tmp_path, monkeypatch):
    path = tmp_path / "u.db"
    legacy_store(path, ("geo", "bad"))
    real = verify.roundtrip
    monkeypatch.setattr(verify, "roundtrip", lambda r, g, L: ["synthetic difference"] if L == "bad" else real(r, g, L))
    hb = Handbook(path)
    r = Research(hb)
    assert "synthetic difference" in r.k.meta("quarantine:bad")
    with pytest.raises(ResearchError, match="could not be loaded into the kernel"):
        r.check("bad")
    assert r.check("geo") == ([], [])  # the rest of the store works
    assert r.export("bad")["tables"]["rl_rows"]  # and the quarantined rows are intact


def test_a_migration_decision_is_durable_before_any_tool_runs(tmp_path, monkeypatch):
    path = tmp_path / "u.db"
    legacy_store(path, ("geo", "bad"))
    real = verify.roundtrip
    monkeypatch.setattr(verify, "roundtrip", lambda r, g, L: ["synthetic difference"] if L == "bad" else real(r, g, L))
    hb = Handbook(path)
    r = Research(hb)
    assert not hb.db.in_transaction
    with pytest.raises(ResearchError):
        r.begin("geo", "S9-none")  # a refusal rolls back its own transaction, and nothing of the migration
    assert r.k.meta("quarantine:bad") and r.k.schema() == 1
    assert sqlite3.connect(path).execute("SELECT value FROM k_meta WHERE key = 'schema'").fetchone() == ("1",)


def test_a_quarantine_follows_the_data_not_the_name(tmp_path, monkeypatch):
    path = tmp_path / "u.db"
    legacy_store(path, ("geo", "bad"))
    real = verify.roundtrip
    monkeypatch.setattr(verify, "roundtrip", lambda r, g, L: ["synthetic difference"]
                        if L.startswith("bad") else real(r, g, L))
    r = Research(Handbook(path))
    data = r.export("bad")
    with pytest.raises(ResearchError, match="does not load into the kernel exactly"):
        r.copy("bad", "bad2")
    with pytest.raises(ResearchError, match="does not load into the kernel exactly"):
        r.rename("bad", "bad3")
    assert r._ledger("bad") and not r.db.execute("SELECT 1 FROM rl_ledgers WHERE id IN ('bad2', 'bad3')").fetchone()
    r.delete("bad", confirm="bad")
    assert r.k.meta("quarantine:bad") is None
    monkeypatch.setattr(verify, "roundtrip", real)  # fixed: the same data loads under the same name
    assert "imported ledger 'bad'" in r.import_(data)
    assert r.check("bad") == ([], [])


def test_a_newer_store_is_left_exactly_as_it_is(tmp_path):
    path = tmp_path / "u.db"
    legacy_store(path)
    hb = Handbook(path)
    m = runtime.attach(hb)
    with m.g.tx():
        m.set_meta("schema", "99")
    hb.db.execute("UPDATE rl_meta SET value = 'from-a-newer-server' WHERE key = 'cards'")
    hb.db.commit()
    hb.close()
    with pytest.raises(RuntimeError, match="newer than this code"):
        Research(Handbook(path))
    assert sqlite3.connect(path).execute("SELECT value FROM rl_meta WHERE key = 'cards'").fetchone() == \
        ("from-a-newer-server",)


def test_the_projection_follows_every_write_and_keeps_the_log(tmp_path):
    path = tmp_path / "u.db"
    legacy_store(path)
    hb = Handbook(path)
    r = Research(hb)
    t = tok(r.begin("geo"))
    r.add("geo", t, "U", "go on", "user", "active")
    r.set("geo", t, "U2", "status", "answered")
    r.end("geo", t)
    assert verify.roundtrip(r, r.k.g, "geo") == []
    events = [e[0] for e in hb.db.execute("SELECT event FROM k_log WHERE ref = 'geo' AND actor = 'legacy' ORDER BY seq")]
    assert events == [e[0] for e in hb.db.execute("SELECT msg FROM rl_log WHERE ledger = 'geo' ORDER BY seq")]
    hb.save_entry(id="disk-full", title="Disk full", condition="ENOSPC or EDQUOT")
    assert r.k.g.node("card:disk-full")["attrs"]["condition"] == "ENOSPC or EDQUOT"


def test_rename_copy_delete_and_a_dry_run_import_reach_the_projection(tmp_path):
    hb = Handbook(tmp_path / "u.db")
    r = Research(hb)
    r.init("a", "q")
    r.copy("a", "b")
    r.rename("a", "c")
    r.delete("b", confirm="b")
    r.import_(r.export("c"), as_ledger="d", dry_run=True)
    assert migrate.ledgers_in_graph(r.k.g) == ["c"]  # the dry run's projection rolled back with it


def test_a_package_upgrade_replaces_installed_rules_and_keeps_the_users(tmp_path, monkeypatch):
    path = tmp_path / "u.db"
    legacy_store(path)
    hb = Handbook(path)
    m = runtime.attach(hb)
    with m.g.tx():  # the user tightens one rule after install
        m.g.define_rule("rs_w_unknown", "check", next(r for r in rs_pkg.RULES if r["id"] == "rs_w_unknown")["body"],
                        actor="user", applies_to="ledger", severity="block", message="{R}: uses unknown {D}")
    new_rules = [dict(r, message=r["message"] + " (v2)") if r["id"] in ("rs_w_unknown", "rs_c_recall") else r
                 for r in rs_pkg.RULES]
    monkeypatch.setattr(rs_pkg, "RULES", new_rules)
    assert m.upgrade_packages() == ["rs_w_unknown"]
    assert m.g.get_rule("rs_c_recall")["message"].endswith("(v2)")  # untouched since install: upgraded
    kept = m.g.get_rule("rs_w_unknown")
    assert (kept["severity"], kept["message"]) == ("block", "{R}: uses unknown {D}")  # the user's version stands
    assert any("package conflict: rule rs_w_unknown" in e[0] for e in hb.db.execute("SELECT event FROM k_log"))
    assert m.upgrade_packages() == []  # recorded as current


def test_a_newer_schema_is_refused(tmp_path):
    path = tmp_path / "u.db"
    legacy_store(path)
    hb = Handbook(path)
    m = runtime.attach(hb)
    with m.g.tx():
        m.set_meta("schema", "99")
    hb.close()
    with pytest.raises(RuntimeError, match="newer than this code"):
        Research(Handbook(path))


def test_remote_stores_attach_on_open(tmp_path):
    from refhandbook.remote import UserStores

    hb = UserStores(tmp_path)("moonny")
    assert hb._kernel.schema() == 1
    assert (tmp_path / "users" / "moonny.db.pre-kernel").exists()


def test_tools_run_on_the_kernel(tmp_path):
    hb = Handbook(tmp_path / "u.db")
    research_api.bind(hb)
    assert research_api.R().k is hb._kernel
    research_api.research_ledgers(action="init", ledger="geo", question="q")
    assert "OBLIGATIONS" in research_api.research_begin("geo")
    assert json.loads(research_api.research_ledgers(action="export", ledger="geo"))["ledger"]["id"] == "geo"
