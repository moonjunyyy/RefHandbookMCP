"""The kernel in the running server: the store's migrations, the projection that keeps the graph
current, and package upgrades.

The kernel is the only judge. research.Research attaches a Mirror to its store (attach) and asks
the kernel's rules for check, obligations and end refusals; there is no second computation to
fall back on or compare with. Writes still land in the rl_* tables, and every seal re-projects the
ledger into the graph inside the same transaction.

Opening a store runs, once each and in order:

  schema 1  legacy → kernel. Back up the file to `<db>.pre-kernel`, load the cards and every
            ledger, and check each ledger's projection by round trip (the export rebuilt from the
            graph must equal the export). A ledger that does not round-trip is quarantined: its
            tools refuse with the reason, the others work. Nothing is lost: its rows stay in rl_*.
  packages  every open compares the installed package rules with the code's. A rule the store
            still has as installed is replaced by the new version; a rule the user has changed
            since is kept, and the conflict is logged (k_log 'package conflict') for the review.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from pathlib import Path

from .. import research as legacy
from ..store import Handbook
from . import migrate, verify
from .graph import Graph

log = logging.getLogger("refhandbook.kernel")
_ATTACH = threading.Lock()
SCHEMA_VERSION = 1
PROJECTION = "sessions-1"  # the projection's shape; changing it re-projects every ledger on open
# log lines that say the rules and the work rubbed (rs_o_review counts them since the last review):
# a refusal of the work, a hit disposed as unaffected, a directive carried, a plan object dropped
# (GLOB: case-sensitive, anchored at the start of the line research.py writes)
REVIEW_SIGNALS = ("refused: *", "dispose * of *: UNAFFECTED*", "carry *: *", "~*: dropped (*")


class Quarantined(legacy.ResearchError):
    pass


class NotLoadable(legacy.ResearchError):
    """A ledger whose data the kernel cannot hold exactly (its round trip differs)."""

    def __init__(self, L: str, diffs: list[str]):
        self.diffs = diffs
        super().__init__(f"REFUSED: ledger {L!r} does not load into the kernel exactly ({'; '.join(diffs)[:300]}); "
                         "nothing was stored. Export the source ledger and report the problem.")


class Mirror:
    """One store's kernel graph and the bookkeeping that keeps it equal to the rl_* tables."""

    def __init__(self, hb: Handbook):
        self.hb = hb
        self.g = Graph(hb.db)

    # ── bookkeeping ──────────────────────────────────────────────────────

    def meta(self, key: str) -> str | None:
        r = self.g.db.execute("SELECT value FROM k_meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key: str, value: str | None) -> None:
        if value is None:
            self.g.db.execute("DELETE FROM k_meta WHERE key = ?", (key,))
        else:
            self.g.db.execute("INSERT OR REPLACE INTO k_meta VALUES (?, ?)", (key, value))

    @staticmethod
    def _fingerprint(r: legacy.Research, L: str) -> str:
        """The ledger's data, and the shape the projection gives it (a new shape re-projects every ledger)."""
        row = r.db.execute("SELECT * FROM rl_ledgers WHERE id = ?", (L,)).fetchone()
        return hashlib.sha1((PROJECTION + r._digest(L) + json.dumps(list(row), default=str)).encode()).hexdigest()

    def _handbook_fingerprint(self) -> str:
        h = hashlib.sha1()
        for sql in ("SELECT id, revision, updated_at FROM entries ORDER BY id",
                    "SELECT * FROM relations ORDER BY src, type, dst",
                    "SELECT * FROM relation_types ORDER BY name"):
            for row in self.hb.db.execute(sql):
                h.update(json.dumps(list(row), default=str).encode())
        return h.hexdigest()

    # ── projection ───────────────────────────────────────────────────────

    def require(self, r: legacy.Research, L: str) -> None:
        """Before the kernel judges ledger L: refuse a quarantined one, project a changed one."""
        why = self.meta(f"quarantine:{L}")
        if why:
            raise Quarantined(f"REFUSED: ledger {L!r} could not be loaded into the kernel ({why}). Its rows are "
                              "intact: export it (research_ledgers action=export) and report the problem.")
        self.sync_ledger(r, L)

    def sync_ledger(self, r: legacy.Research, L: str, force: bool = False) -> None:
        """Re-project ledger L if it changed since the last projection, or drop it if it is gone.

        A quarantine belongs to the data, not the name: deleting the ledger lifts it, and every
        first projection of an id (an import, a copy, a rename, the migration) is admitted only by
        round trip, so quarantined data cannot come back under another name. A first projection
        that does not round-trip refuses the write that made it."""
        with self.g.tx():
            if not r.db.execute("SELECT 1 FROM rl_ledgers WHERE id = ?", (L,)).fetchone():
                if self.g.get_node(L) is not None:
                    migrate.drop_ledger(self.g, L)
                for k in (f"sync:{L}", f"logseq:{L}", f"quarantine:{L}"):
                    self.set_meta(k, None)
                return
            if self.meta(f"quarantine:{L}"):
                return
            first = self.g.get_node(L) is None
            fp = self._fingerprint(r, L)
            if not force and self.meta(f"sync:{L}") == fp and self.g.get_node(L) is not None:
                if self._log_behind(r, L):  # only the log moved (a refusal, say): its facts, not the rows
                    self._append_log(r, L)
                    self._derive(r, L)
                return
            data = r.export(L, include_log=False)
            if self.g.get_node(L) is not None:
                migrate.drop_ledger(self.g, L, keep_log=True)
            migrate.ledger_to_graph(self.g, data)
            if first:
                diffs = verify.roundtrip(r, self.g, L)
                if diffs:
                    raise NotLoadable(L, diffs)
            self._append_log(r, L)
            self._derive(r, L)
            self.set_meta(f"sync:{L}", fp)

    def _derive(self, r: legacy.Research, L: str) -> None:
        """Facts the rules need that are counts over the log (the rule language has no aggregates)."""
        turn, seq = r.db.execute("SELECT max(turn), max(seq) FROM rl_log WHERE ledger = ? AND msg GLOB 'review: *'",
                                 (L,)).fetchone()
        signals = r.db.execute(
            "SELECT count(*) FROM rl_log WHERE ledger = ? AND seq > ? AND (" + " OR ".join(
                "msg GLOB ?" for _ in REVIEW_SIGNALS) + ")", (L, seq or 0, *REVIEW_SIGNALS)).fetchone()[0]
        self.g.update_node(L, actor="kernel", validate=False,
                           attrs={"derived_last_review": turn or 0, "derived_signals": signals})

    def _log_behind(self, r: legacy.Research, L: str) -> bool:
        last = r.db.execute("SELECT max(seq) FROM rl_log WHERE ledger = ?", (L,)).fetchone()[0] or 0
        return last > int(self.meta(f"logseq:{L}") or 0)

    def _append_log(self, r: legacy.Research, L: str) -> None:
        """The log is append-only: carry over the rows past the last one carried."""
        last = int(self.meta(f"logseq:{L}") or 0)
        rows = r.db.execute("SELECT seq, turn, ts, msg FROM rl_log WHERE ledger = ? AND seq > ? ORDER BY seq",
                            (L, last)).fetchall()
        for seq, turn, ts, msg in rows:
            self.g.db.execute("INSERT INTO k_log (clock, actor, event, ref, meta) VALUES (?, ?, ?, ?, ?)",
                              (self.g.clock(), migrate.LOG_ACTOR, msg, L, json.dumps({"turn": turn, "ts": ts})))
        if rows:
            self.set_meta(f"logseq:{L}", str(rows[-1][0]))

    def reconcile(self, r: legacy.Research) -> None:
        live = set(r._column("SELECT id FROM rl_ledgers"))
        for L in set(migrate.ledgers_in_graph(self.g)) - live:
            self.sync_ledger(r, L)
        for L in sorted(live):
            try:
                self.sync_ledger(r, L)
            except NotLoadable as e:
                with self.g.tx():
                    self.set_meta(f"quarantine:{L}", "; ".join(e.diffs)[:500])
                log.warning("ledger %s in %s quarantined at open: %s", L, self.hb.path, e.diffs)

    def sync_handbook(self) -> None:
        fp = self._handbook_fingerprint()
        if self.meta("sync:handbook") == fp:
            return
        with self.g.tx():
            migrate.drop_handbook(self.g)
            migrate.handbook_to_graph(self.g, self.hb.export())
            self.set_meta("sync:handbook", fp)

    # ── migrations ───────────────────────────────────────────────────────

    def schema(self) -> int:
        v = self.meta("schema")
        if v is None and self.meta("kernel_status") == "active":
            return 1  # stores migrated by 0.7.0 recorded only their status
        return int(v or 0)

    def migrate_v1(self, r: legacy.Research) -> list[str]:
        """legacy → kernel, ledger by ledger; returns the quarantined ledgers."""
        self.upgrade_packages()
        self.sync_handbook()
        bad = []
        for L in sorted(r._column("SELECT id FROM rl_ledgers")):
            try:
                self.sync_ledger(r, L, force=True)  # a first projection: admitted by round trip
                continue
            except NotLoadable as e:
                diffs = e.diffs
            except Exception as e:  # noqa: BLE001 — any failure quarantines this ledger, not the store
                diffs = [f"{type(e).__name__}: {e}"]
            with self.g.tx():
                self.set_meta(f"quarantine:{L}", "; ".join(diffs)[:500])
            bad.append(L)
            log.warning("kernel migration of %s: ledger %s quarantined: %s", self.hb.path, L, diffs)
        with self.g.tx():
            self.set_meta("schema", "1")
            self.set_meta("kernel_status", "active")
            self.g.log("kernel", f"migration v1: {len(bad)} ledger(s) quarantined", "store")
        log.info("kernel migration of %s: schema 1, %d quarantined", self.hb.path, len(bad))
        return bad

    def upgrade_packages(self) -> list[str]:
        """Bring the installed package rules to this code's version, without ever making the store
        unopenable. Returns the rules kept against a new package version.

        A package rule the user changed or retired (its origin is no longer the kernel) is kept, and
        if the package changed it too the conflict is logged. A rule unchanged since install is
        replaced. A rule the package dropped is retired, unless another rule still uses it. If the
        new rules cannot stand beside the store's other rules, the model's proposals are retired
        first (they are advice, and say so in the log); if the user's own rules are what conflicts,
        the upgrade is deferred and logged, and the store keeps its installed version."""
        from .packages import research as rs_pkg

        digest = rs_pkg.digest()
        if self.meta("package:research") == digest:
            return []
        try:
            with self.g.tx():
                return self._upgrade(digest)
        except legacy.HandbookError as first:
            proposals = [r["id"] for r in self.g.active_rules() if r["authority"] == "proposed"]
            try:
                if not proposals:
                    raise
                with self.g.tx():
                    for rid in proposals:
                        self.g.db.execute("UPDATE k_rules SET state = 'retired', origin = 'kernel' WHERE id = ?", (rid,))
                        self.g.log("kernel", f"proposal {rid} retired: the package upgrade conflicts with the "
                                             f"proposals ({first}); re-propose against the new package", rid)
                    self.g._bump_rules()
                    return self._upgrade(digest)
            except legacy.HandbookError as e:
                with self.g.tx():
                    self.g.log("kernel", f"package upgrade deferred: {e}", "package:research")
                log.error("package research upgrade deferred in %s: %s", self.hb.path, e)
                return []

    def _upgrade(self, digest: str) -> list[str]:
        from .graph import rule_sha
        from .packages import handbook as hb_pkg
        from .packages import research as rs_pkg

        installed = {r["id"]: dict(r) for r in self.g.db.execute("SELECT * FROM k_rules WHERE pkg = ?", (rs_pkg.PKG,))}
        keep = {rid for rid, row in installed.items() if row["origin"] != "kernel"}  # the user's decision stands
        new = {r["id"]: r for r in rs_pkg.RULES}
        for rid in sorted(set(installed) - set(new) - keep):
            if installed[rid]["state"] == "retired":
                continue
            try:
                self.g.retire_rule(rid, actor="kernel")
                self.set_meta(f"pkgbase:{rid}", None)
            except legacy.HandbookError as e:  # another rule still uses it: it stays, as a rule of the store
                self.g.log("kernel", f"package dropped rule {rid}, kept: {e}", rid)
        rs_pkg.install(self.g, skip=keep)
        hb_pkg.install(self.g)
        conflicts = []
        for rid, spec in new.items():
            if rid in keep:
                if self.meta(f"pkgbase:{rid}") != rule_sha(spec) and rule_sha(installed[rid]) != rule_sha(spec):
                    conflicts.append(rid)  # both changed it: the user's stands, the package's is reported
                continue
            self.set_meta(f"pkgbase:{rid}", rule_sha(spec))
        for rid in conflicts:
            self.g.log("kernel", f"package conflict: rule {rid} kept as the user changed or retired it; the package "
                                 "has a new version", rid)
        self.set_meta("package:research", digest)
        if conflicts:
            log.warning("package research upgraded in %s with %d conflict(s): %s", self.hb.path, len(conflicts), conflicts)
        return sorted(conflicts)


def _backup(hb: Handbook, tag: str) -> None:
    if hb.path == ":memory:":
        return
    dest = Path(f"{hb.path}.{tag}")
    if dest.exists():
        return
    target = sqlite3.connect(dest)
    try:
        hb.db.backup(target)
    finally:
        target.close()
    log.info("backed up %s to %s", hb.path, dest)


def attach(hb: Handbook) -> Mirror:
    """The store's mirror: created on first use, with the store migrated and its packages current."""
    m = getattr(hb, "_kernel", None)
    if m is not None:
        return m
    with _ATTACH:
        m = getattr(hb, "_kernel", None)
        if m is not None:
            return m
        fresh = not hb.db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'k_meta'").fetchone()
        if not fresh:  # before anything writes to it: a newer store is left exactly as it is
            row = hb.db.execute("SELECT value FROM k_meta WHERE key = 'schema'").fetchone()
            if row and int(row[0]) > SCHEMA_VERSION:
                raise RuntimeError(f"{hb.path} has kernel schema {row[0]}, newer than this code "
                                   f"({SCHEMA_VERSION}); upgrade the server instead of opening it")
        if fresh:
            _backup(hb, "pre-kernel")
        legacy.ensure_cards(hb)
        m = Mirror(hb)
        r = legacy.Research(hb, kernel=False)
        if m.schema() < 1:
            m.migrate_v1(r)
        else:
            m.upgrade_packages()
            m.reconcile(r)
            m.sync_handbook()
        m.g.prune_blobs()
        if hb.db.in_transaction:  # opening is a boundary: what it decided is durable before any tool runs
            hb.db.commit()
        hb.on_change(m.sync_handbook)
        hb._kernel = m  # type: ignore[attr-defined]
        return m
