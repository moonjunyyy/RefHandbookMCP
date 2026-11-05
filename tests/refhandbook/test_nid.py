"""Rows carry node ids (schema 2; stage P0a of the entry-node migration).

A row's node in the graph is named by its nid, not by its ledger, so it keeps its identity through
re-projection and rename; a copy is a node of its own; an import keeps a nid the store does not use;
a reference to a row that is not there keeps the ledger's name, and the row's own node takes it over
when the row comes back."""

import copy
import sqlite3

from refhandbook import Handbook, research
from refhandbook.kernel import migrate, runtime, verify
from refhandbook.research import Research

from .test_kernel_runtime import legacy_store
from .test_research import Turn, rs  # noqa: F401 (rs is a fixture)


def nid(r, L, rid):
    return r._row(L, rid)["nid"]


def test_a_row_is_named_by_its_nid_through_projection_and_rename(rs):
    t = Turn(rs)
    t.begin(1)
    t.add("U", "derive it", "user", "active")
    t.add("E", "the object", "user", "established", evidence="followed")  # E1
    g, n = rs.k.g, nid(rs, "geo", "E1")
    assert n.startswith("n:") and "geo" not in n and migrate.row_node(g, "geo", "E1") == n
    t.add("E", "another object re-projects geo", "user", "established", evidence="followed")
    assert migrate.row_node(g, "geo", "E1") == n
    t.end(idle="test")
    rs.rename("geo", "geo2")
    assert nid(rs, "geo2", "E1") == n and migrate.row_node(g, "geo2", "E1") == n
    assert g.node(n)["attrs"]["xref"] == "geo2/E1"


def test_a_copy_is_a_node_of_its_own_and_an_import_keeps_a_free_nid(rs):
    t = Turn(rs)
    t.begin(1)
    t.add("E", "the object", "user", "established", evidence="followed")
    t.end(idle="test")
    n = nid(rs, "geo", "E1")
    rs.copy("geo", "geo-copy")
    assert nid(rs, "geo-copy", "E1") not in (None, n)
    data = rs.export("geo")
    hb2 = Handbook(":memory:")
    research.ensure_cards(hb2)
    r2 = Research(hb2)
    r2.import_(data)
    assert nid(r2, "geo", "E1") == n  # moved to another store: the same node
    old = copy.deepcopy(data)
    for row in old["tables"]["rl_rows"]:
        del row["nid"]  # an export made before schema 2
    r2.import_(old, as_ledger="old")
    assert nid(r2, "old", "E1").startswith("n:") and nid(r2, "old", "E1") != n


def test_a_citation_lands_on_the_row_and_survives_its_ledger_going_and_coming_back(rs):
    rs.init("kernel", "what the ledgers share")
    k = Turn(rs, "kernel")
    k.begin(1)
    k.add("E", "the log chart theorem", "user", "established", evidence="followed")  # kernel E1
    k.end(idle="test")
    t = Turn(rs)
    t.begin(1)
    t.add("H", "rests on the kernel's theorem", "user", "open", dep="ref:kernel/E1")  # geo H1
    t.end(idle="test")
    g, E1, H1 = rs.k.g, nid(rs, "kernel", "E1"), nid(rs, "geo", "H1")
    assert [e["dst"] for e in g.edges(src=H1, type_="dep_ref")] == [E1]
    rs.rename("kernel", "kernel2")  # the cell still says kernel/E1, which now names nothing
    assert [e["dst"] for e in g.edges(src=H1, type_="dep_ref")] == ["kernel:r:E1"]  # a reference keeps the name
    assert g.node("kernel:r:E1")["type"] == "missing"
    rs.rename("kernel2", "kernel")  # back: the row's own node takes the placeholder over
    assert [e["dst"] for e in g.edges(src=H1, type_="dep_ref")] == [E1]
    assert g.get_node("kernel:r:E1") is None


def _strip_nids(path):
    """Make the store as it was before schema 2: no nid column, every ledger sealed without it."""
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    for stmt in ("DROP TRIGGER rl_rows_nid_ins", "DROP INDEX rl_rows_nid_idx", "ALTER TABLE rl_rows DROP COLUMN nid"):
        db.execute(stmt)

    class Store:  # just enough of Research for its digest
        def __init__(self):
            self.db = db

        def _ledger(self, L):
            return dict(db.execute("SELECT * FROM rl_ledgers WHERE id = ?", (L,)).fetchone())

    for (L,) in db.execute("SELECT id FROM rl_ledgers").fetchall():
        db.execute("UPDATE rl_ledgers SET token = ? WHERE id = ?", (Research._digest(Store(), L), L))
    db.commit()
    db.close()


def test_a_store_from_before_node_ids_is_backed_up_filled_and_marked(tmp_path):
    path = tmp_path / "u.db"
    legacy_store(path)
    _strip_nids(path)
    columns = lambda p: {c[1] for c in sqlite3.connect(p).execute("PRAGMA table_info(rl_rows)")}  # noqa: E731
    assert "nid" not in columns(path)
    hb = Handbook(path)
    r = Research(hb)
    assert "nid" not in columns(tmp_path / "u.db.pre-nid") and "nid" in columns(path)
    nids = [x for (x,) in hb.db.execute("SELECT nid FROM rl_rows WHERE ledger = 'geo'")]
    assert nids and all(x.startswith("n:") for x in nids) and len(set(nids)) == len(nids)
    assert r.k.schema() == runtime.SCHEMA_VERSION == 2
    rids = ("U1", "A1", "K1")
    assert [migrate.row_node(r.k.g, "geo", x) for x in rids] == [nid(r, "geo", x) for x in rids]
    assert verify.roundtrip(r, r.k.g, "geo") == []
    assert "outside the device" not in r.begin("geo", "")  # the fill is not an edit outside the device
