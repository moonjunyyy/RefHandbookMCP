"""The kernel in the running server: migration on first open, a mirror kept current, and the
research gates decided by the kernel's rules.

attach(hb) is called wherever a store is opened (remote.UserStores, research_api.bind/R, the
local server). The first time a store is opened with this code:

  1. a file store is copied to `<db>.pre-kernel` (SQLite backup), before any kernel table exists;
  2. the cards and every research ledger are loaded into the kernel graph (k_* tables, same file);
  3. each ledger is verified (kernel/verify.compare: export round trip, check messages, begin
     obligations, end blockers). The store is marked `kernel_status = active`, or `legacy: <why>`
     if any ledger differs, and a mismatch is written to the server log.

After that, every write that seals a ledger re-projects it into the graph inside the same
transaction, and every card change re-projects the cards. While `active`, the research gates are
the kernel's: research_check and research_end's CHECK lines come from the package's check rules,
research_begin's obligations and research_end's refusals from its obligation and close rules. The
legacy computation still runs beside them as a cross-check; a disagreement is logged (k_log and the
server log) and the kernel's answer stands.

RHB_KERNEL=0 turns all of this off (the plain legacy engine, nothing written to k_* tables).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .. import research as legacy
from ..store import Handbook
from . import migrate, verify
from .graph import Graph

log = logging.getLogger("refhandbook.kernel")
_ATTACH = threading.Lock()


def enabled() -> bool:
    return os.environ.get("RHB_KERNEL", "1") != "0"


class Mirror:
    """One store's kernel graph and the bookkeeping that keeps it equal to the legacy tables."""

    def __init__(self, hb: Handbook):
        self.hb = hb
        self.g = Graph(hb.db)
        self.status = self._meta("kernel_status") or "new"

    # ── bookkeeping ──────────────────────────────────────────────────────

    def _meta(self, key: str) -> str | None:
        r = self.g.db.execute("SELECT value FROM k_meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else None

    def _set_meta(self, key: str, value: str) -> None:
        self.g.db.execute("INSERT OR REPLACE INTO k_meta VALUES (?, ?)", (key, value))

    def active(self) -> bool:
        return self.status == "active"

    @staticmethod
    def _fingerprint(r: legacy.Research, L: str) -> str:
        row = r.db.execute("SELECT * FROM rl_ledgers WHERE id = ?", (L,)).fetchone()
        return hashlib.sha1((r._digest(L) + json.dumps(list(row), default=str)).encode()).hexdigest()

    def _handbook_fingerprint(self) -> str:
        h = hashlib.sha1()
        for sql in ("SELECT id, revision, updated_at FROM entries ORDER BY id",
                    "SELECT * FROM relations ORDER BY src, type, dst",
                    "SELECT * FROM relation_types ORDER BY name"):
            for row in self.hb.db.execute(sql):
                h.update(json.dumps(list(row), default=str).encode())
        return h.hexdigest()

    # ── projection ───────────────────────────────────────────────────────

    def sync_ledger(self, r: legacy.Research, L: str, force: bool = False) -> None:
        """Re-project ledger L if it changed since the last projection (or it is gone: drop it)."""
        with self.g.tx():
            exists = r.db.execute("SELECT 1 FROM rl_ledgers WHERE id = ?", (L,)).fetchone()
            if not exists:
                if self.g.get_node(L) is not None:
                    migrate.drop_ledger(self.g, L)
                self.g.db.execute("DELETE FROM k_meta WHERE key IN (?, ?)", (f"sync:{L}", f"logseq:{L}"))
                return
            fp = self._fingerprint(r, L)
            if not force and self._meta(f"sync:{L}") == fp and self.g.get_node(L) is not None:
                return
            data = r.export(L, include_log=False)
            if self.g.get_node(L) is not None:
                migrate.drop_ledger(self.g, L, keep_log=True)
            migrate.ledger_to_graph(self.g, data)
            self._append_log(r, L)
            self._set_meta(f"sync:{L}", fp)

    def _append_log(self, r: legacy.Research, L: str) -> None:
        """The log is append-only: carry over the rows past the last one carried (a re-projection
        does not re-copy a long history)."""
        last = int(self._meta(f"logseq:{L}") or 0)
        rows = r.db.execute("SELECT seq, turn, ts, msg FROM rl_log WHERE ledger = ? AND seq > ? ORDER BY seq",
                            (L, last)).fetchall()
        for seq, turn, ts, msg in rows:
            self.g.db.execute("INSERT INTO k_log (clock, actor, event, ref, meta) VALUES (?, ?, ?, ?, ?)",
                              (self.g.clock(), migrate.LOG_ACTOR, msg, L, json.dumps({"turn": turn, "ts": ts})))
        if rows:
            self._set_meta(f"logseq:{L}", str(rows[-1][0]))

    def reconcile(self, r: legacy.Research) -> None:
        """Drop images of ledgers that no longer exist (renamed or deleted), project the rest."""
        live = set(r._column("SELECT id FROM rl_ledgers"))
        for L in set(migrate.ledgers_in_graph(self.g)) - live:
            self.sync_ledger(r, L)
        for L in sorted(live):
            self.sync_ledger(r, L)

    def sync_handbook(self) -> None:
        fp = self._handbook_fingerprint()
        if self._meta("sync:handbook") == fp:
            return
        with self.g.tx():
            migrate.drop_handbook(self.g)
            migrate.handbook_to_graph(self.g, self.hb.export())
            self._set_meta("sync:handbook", fp)

    # ── migration ────────────────────────────────────────────────────────

    def migrate(self, r: legacy.Research) -> str:
        """Load everything, verify every ledger, and record the outcome. Idempotent."""
        with self.g.tx():
            migrate.install(self.g)
        self.sync_handbook()
        diffs: list[str] = []
        for L in sorted(r._column("SELECT id FROM rl_ledgers")):
            self.sync_ledger(r, L, force=True)
            diffs += [f"{L}: {d}" for d in verify.compare(r, self.g, L, include_log=False)]
            migrate.drop_ledger(self.g, L, keep_log=True)  # verification wrote a turn node: project clean
            self.sync_ledger(r, L, force=True)
        status = "active" if not diffs else "legacy: " + "; ".join(diffs)[:2000]
        with self.g.tx():
            self._set_meta("kernel_status", status)
            self.g.log("kernel", f"migration: {status[:200]}", "store")
        self.status = status
        if diffs:
            log.warning("kernel migration of %s kept the legacy gates: %s", self.hb.path, status)
        else:
            log.info("kernel migration of %s: active", self.hb.path)
        return status


def _backup(hb: Handbook) -> None:
    if hb.path == ":memory:":
        return
    has_kernel = hb.db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'k_meta'").fetchone()
    if has_kernel:
        return
    dest = Path(f"{hb.path}.pre-kernel")
    if dest.exists():
        return
    target = sqlite3.connect(dest)
    try:
        hb.db.backup(target)
    finally:
        target.close()
    log.info("backed up %s to %s before the kernel migration", hb.path, dest)


def attach(hb: Handbook) -> "Mirror | None":
    """The store's mirror, created (and the store migrated) on first use."""
    if not enabled():
        return None
    m = getattr(hb, "_kernel", None)
    if m is not None:
        return m
    with _ATTACH:
        m = getattr(hb, "_kernel", None)
        if m is not None:
            return m
        _backup(hb)
        legacy.ensure_cards(hb)
        m = Mirror(hb)
        r = legacy.Research(hb)
        if not m.status.startswith(("active", "legacy")):
            m.migrate(r)
        else:
            m.reconcile(r)
            m.sync_handbook()
        hb.on_change(m.sync_handbook)
        hb._kernel = m  # type: ignore[attr-defined]
        return m


class KernelResearch(legacy.Research):
    """The legacy engine with its gates decided by the kernel rules."""

    def __init__(self, hb: Handbook, mirror: Mirror):
        super().__init__(hb)
        self.k = mirror

    def _sealed(self, ledger: str) -> None:
        self.k.sync_ledger(self, ledger)

    def rename(self, ledger: str, to: str) -> str:
        out = super().rename(ledger, to)
        self.k.sync_ledger(self, ledger)  # gone: its image is dropped (the new id synced on its seal)
        return out

    def delete(self, ledger: str, confirm: str) -> str:
        out = super().delete(ledger, confirm)
        self.k.sync_ledger(self, ledger)
        return out

    def _diverged(self, what: str, ledger: str, kernel_only: Any, legacy_only: Any) -> None:
        msg = f"{what} of {ledger} differ: kernel-only {sorted(kernel_only)}, legacy-only {sorted(legacy_only)}"
        if os.environ.get("RHB_KERNEL_STRICT") == "1":  # tests: a divergence is a failure
            raise AssertionError(f"kernel divergence: {msg}")
        log.warning("kernel divergence in %s: %s", self.hb.path, msg)
        with self.k.g.tx():
            self.k.g.log("kernel", f"divergence: {msg}"[:2000], ledger)

    def check(self, ledger: str) -> tuple[list[str], list[str]]:
        errors, warnings = self._legacy_check(ledger)
        if not self.k.active():
            return errors, warnings
        self.k.sync_ledger(self, ledger)
        ke, kw, _ = verify.check(self.k.g, ledger)
        if set(ke) != set(errors):
            self._diverged("check errors", ledger, set(ke) - set(errors), set(errors) - set(ke))
        if set(kw) != set(warnings):
            self._diverged("check warnings", ledger, set(kw) - set(warnings), set(warnings) - set(kw))
        return _ordered(ke, errors), _ordered(kw, warnings)

    def obligation_items(self, ledger: str) -> list[tuple[str, str, str, str]]:
        rows = super().obligation_items(ledger)
        if not self.k.active():
            return rows
        self.k.sync_ledger(self, ledger)
        return self._decide("obligations", ledger, rows, verify.obligations(self.k.g, ledger),
                            lambda k, ref, src: f"  {k.upper():9} {ref}" + (f" (from {src})" if src else ""))

    def blockers(self, ledger: str, turn: int, idle: str = "") -> list[tuple[str, str, str, str]]:
        rows = super().blockers(ledger, turn, idle)
        if not self.k.active():
            return rows
        self.k.sync_ledger(self, ledger)
        kernel = verify.blockers(self.k.g, ledger, turn, idle)
        return self._decide("end blockers", ledger, rows, kernel,
                            lambda k, ref, src: f"CHECK {ref}" if k == "check" else
                            f"{k.upper()} {ref}" + (f" (from {src})" if src else ""))

    def _decide(self, what: str, ledger: str, rows: list[tuple[str, str, str, str]],
                kernel: set[tuple[str, str, str]], text: Any) -> list[tuple[str, str, str, str]]:
        """The kernel's set, in the legacy order and wording where the legacy side has the item."""
        legacy_keys = {(k, ref, src) for k, ref, src, _ in rows}
        if kernel != legacy_keys:
            self._diverged(what, ledger, kernel - legacy_keys, legacy_keys - kernel)
        out = [row for row in rows if (row[0], row[1], row[2]) in kernel]
        out += [(k, ref, src, text(k, ref, src)) for k, ref, src in sorted(kernel - legacy_keys)]
        return out


def _ordered(kernel: list[str], legacy_order: list[str]) -> list[str]:
    """The kernel's messages, in the order (and with the repeats) the legacy engine prints them."""
    keep = set(kernel)
    out = [m for m in legacy_order if m in keep]
    out += [m for m in kernel if m not in set(legacy_order)]
    return out


def research_for(hb: Handbook) -> legacy.Research:
    """The engine a tool call should use on this store."""
    m = attach(hb)
    return KernelResearch(hb, m) if m is not None else legacy.Research(hb)
