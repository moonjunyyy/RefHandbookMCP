"""A vocabulary package reaches a store whose research package is already current (handbook-entry-graph,
session 11: the entry package was installed only inside the research upgrade, so the live store answered
"no type 'entry'")."""

import pytest

from refhandbook import Handbook, entry_api, research_api
from refhandbook.kernel.packages import VOCABULARIES, entry as entry_pkg, research as rs_pkg


@pytest.fixture
def api(tmp_path):
    hb = Handbook(tmp_path / "v.db")
    research_api.bind(hb)
    return hb


def _drop_entry_vocabulary(m):
    with m.g.tx():
        m.g.db.execute("DELETE FROM k_types WHERE pkg = 'entry'")
        m.set_meta("package:entry", None)


def test_entry_vocabulary_installs_when_research_is_current(api):
    m = research_api.R().k
    _drop_entry_vocabulary(m)
    assert m.meta("package:research") == rs_pkg.digest()  # the research gate would skip
    with pytest.raises(Exception, match="no type 'entry'"):
        entry_api.entry_node("topic")
    assert m.upgrade_packages() == []
    assert m.meta("package:entry") == entry_pkg.digest()
    assert entry_api.entry_node("topic").startswith("entry n:")


def test_vocabulary_gate_is_idempotent_and_per_package(api):
    m = research_api.R().k
    for pkg in VOCABULARIES:
        assert m.meta(f"package:{pkg.PKG}") == pkg.digest()
    before = m.g.db.execute("SELECT count(*) FROM k_log").fetchone()[0]
    m.upgrade_packages()  # nothing changed: no install, no log
    assert m.g.db.execute("SELECT count(*) FROM k_log").fetchone()[0] == before
