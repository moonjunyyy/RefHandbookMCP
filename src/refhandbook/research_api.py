"""The research tools as plain functions.

The MCP server registers these functions as tools, and the CLI calls the same functions with
JSON arguments, so the fallback path (a session without the MCP server) runs the same code.
This module imports nothing from `mcp`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal

from . import research as rs
from .store import Handbook

_hb: Handbook | None = None
_rs: rs.Research | None = None


def bind(hb: Handbook) -> None:
    """Use this handbook (tests, the CLI's --db). Loads the research cards into it."""
    global _hb, _rs
    _hb = hb
    rs.ensure_cards(hb)
    _rs = rs.Research(hb)


_resolver: Callable[[], Handbook] | None = None
_per_store: dict[int, rs.Research] = {}


def use_resolver(fn: Callable[[], Handbook] | None) -> None:
    """Remote mode: pick the handbook per call (the signed-in user's), instead of one bound store."""
    global _resolver
    _resolver = fn
    _per_store.clear()


def R() -> rs.Research:
    if _resolver is not None:
        hb = _resolver()
        r = _per_store.get(id(hb))
        if r is None or r.hb is not hb:
            rs.ensure_cards(hb)
            r = _per_store[id(hb)] = rs.Research(hb)
        return r
    if _rs is None:
        bind(Handbook())
    return _rs  # type: ignore[return-value]


N1_LINE = ("N1: BEGIN ✓ → REGISTER (the message as U/C/A/S/R; user files as source docs; unresolved refs → RF) "
           "→ DISPATCH (new U from the U; the K awaiting the user stands) → LOOP (research_next · run the card · push the exit's objects · "
           "research_done) → PROPAGATE (dispose PENDING) → SETTLE (U set or carried; doc plans synced) → "
           "END (research_end) → SHOW (transcript, RECEIPT, changed rows, Δ, NEXT last). Full card: open_entry('rs-n1').")


# ── ledgers and turns ────────────────────────────────────────────────────

def research_ledgers(action: Literal["list", "init", "status", "export", "import", "copy", "rename"] = "list",
                     ledger: str | None = None, question: str | None = None, data: str | None = None,
                     to: str | None = None, include_log: bool = True, dry_run: bool = False) -> str:
    """Manage research ledgers. list: every ledger with its turn. init: create one (ledger, question).
    status: machine state of one ledger. export: one ledger as JSON (include_log=false drops the
    per-turn change log, the bulk of a long ledger). import: load an exported JSON string (data),
    under its own id or, with `to`, under another (a sandbox copy to inspect first); dry_run=true
    checks it and stores nothing. copy: duplicate `ledger` as `to` (a sandbox). rename: `ledger` → `to`.
    Deleting is research_ledger_delete. A large import goes through the CLI: research research_ledgers @args.json"""
    r = R()
    if action == "list":
        return r.ledgers()
    if action == "init":
        if not ledger or not question:
            raise rs.ResearchError("init needs ledger and question")
        return r.init(ledger, question)
    if action == "status":
        return json.dumps(r.status(ledger or ""), ensure_ascii=False)
    if action == "export":
        return json.dumps(r.export(ledger or "", include_log=include_log), ensure_ascii=False, default=str)
    if action == "import":
        if not data:
            raise rs.ResearchError("import needs data: the JSON that export returned")
        try:
            parsed = json.loads(data) if isinstance(data, str) else data
        except json.JSONDecodeError as e:
            raise rs.ResearchError(f"import data is not JSON: {e}") from e
        return r.import_(parsed, as_ledger=to, dry_run=dry_run)
    if action in ("copy", "rename"):
        if not ledger or not to:
            raise rs.ResearchError(f"{action} needs ledger and to")
        return r.copy(ledger, to) if action == "copy" else r.rename(ledger, to)
    raise rs.ResearchError(f"unknown action {action!r}")


def research_ledger_delete(ledger: str, confirm: str) -> str:
    """Delete a ledger and everything in it, permanently. confirm must repeat the ledger id.
    Export or copy it first if it may be needed again."""
    return R().delete(ledger, confirm)


def research_begin(ledger: str, turn: int, view: Literal["recent", "brief", "full"] = "recent", recent: int = 3) -> str:
    """Open (or re-read) a turn. Prints the TOKEN on the first line, the ledger view, and the
    OBLIGATIONS this turn must work. view: recent (rows changed in the last `recent` turns plus every
    live row the obligations name; the default), brief (TOKEN and OBLIGATIONS only), full (every row).
    Read more with research_show. Call it first, every turn; never truncate its output."""
    return R().begin(ledger, turn, view, recent) + "\n\n" + N1_LINE


def research_show(ledger: str, open_only: bool = False, ids: str = "", recent: int = 0) -> str:
    """Read the ledger without opening a turn. open_only: only rows that are not yet terminal.
    ids: only these rows (space-separated, e.g. "E3 H2 A1"). recent: only rows changed in the last N turns."""
    r = R()
    only = set(ids.split()) if ids.strip() else None
    if recent:
        only = (only or set()) | r.recent_ids(ledger, recent)
    return r.render(ledger, open_only, only=only)


def research_end(ledger: str, turn: int, token: str, idle: str = "") -> str:
    """Close the turn. Refuses while a PENDING hit, a running plan object, no continuation, an
    unaddressed directive, an unsynced document plan, or a check error remains. Prints the
    RECEIPT, the rows changed this turn, the turn's changes (Δ) and, last, the NEXT line."""
    return R().end(ledger, token, turn, idle)


# ── rows ─────────────────────────────────────────────────────────────────

def research_add(ledger: str, token: str, sec: str, content: str, origin: str, status: str,
                 evidence: str = "", dep: str = "", grp: str = "") -> str:
    """Add a row. sec: U C R S A Z T E H X P (plan objects K come from research_push).
    origin: user | entailed(<step>) | model. status: see card rs-ref-ledger. dep: '[rel:]ID' tokens
    (rel: req der sup eq iso spec int con). grp: alternative group for an assumption."""
    return R().add(ledger, token, sec, content, origin, status, evidence, dep, grp)


def research_set(ledger: str, token: str, id: str, field: str, value: str) -> str:
    """Replace one cell of one row (content, origin, status, evidence, dep, grp), or the whole
    map with id='M', field='content'. Replace, never append: the log keeps the history.
    An invalidating change prints PENDING hits that must be disposed."""
    return R().set(ledger, token, id, field, value)


def research_dispose(ledger: str, token: str, hit: str, of: str,
                     disposition: Literal["VALID", "RECHECK", "INVALID", "UNAFFECTED"], why: str = "") -> str:
    """Dispose one PENDING hit (a row id, or a verdict cell 'H1@config') opened by a change of `of`.
    VALID: re-derived this turn. RECHECK: mark stale (opens the next layer). INVALID: already set
    false/superseded/refuted. UNAFFECTED: history only (why required)."""
    return R().dispose(ledger, token, hit, of, disposition, why)


def research_carry(ledger: str, token: str, uid: str, why: str) -> str:
    """Keep an active directive or question (U) open past this turn, with the reason."""
    return R().carry(ledger, token, uid, why)


# ── plan objects ─────────────────────────────────────────────────────────

def research_push(ledger: str, token: str, do: str, page: str, frm: str, on: str = "", exit: str = "") -> str:
    """Push a plan object K: `do` on the `on` rows, to be run on card `page` (N1 N2 N3 N3b N4 RF EX
    X1-X9 QM DV FM VF IM DOM-*, any handbook card id, or USER to wait for the user). frm: the K or U
    it comes from; exit: the exit of frm that returns it."""
    return R().push(ledger, token, do, page, frm, on, exit)


def research_next(ledger: str, token: str, kid: str = "") -> str:
    """Take the oldest queued K (or the given one, also one awaiting the user), mark it running,
    and print its card."""
    return R().next(ledger, token, kid)


def research_done(ledger: str, token: str, kid: str, exit: str) -> str:
    """Finish the running K through an exit. Refused unless that exit already pushed at least one
    object (a terminal exit pushes page USER)."""
    return R().done(ledger, token, kid, exit)


def research_drop(ledger: str, token: str, kid: str, why: str) -> str:
    """Drop a queued or waiting K, with the reason."""
    return R().drop(ledger, token, kid, why)


# ── exploration and documents ────────────────────────────────────────────

def research_explore(ledger: str, action: Literal["config", "verdict", "matrix"], token: str | None = None,
                     name: str | None = None, spec: str | None = None, purpose: str = "",
                     claim: str | None = None, config: str | None = None, verdict: str | None = None,
                     evidence: str = "", claims: list[str] | None = None) -> str:
    """Explore how verdicts depend on assumptions (card rs-ex).
    config: define a named configuration (name, spec, purpose); spec edits 'main' with +A5, -A2,
    A3>A7, or lists members. 'main' is the user's line and cannot be redefined.
    verdict: record claim × config (true needs evidence, false needs 'cex:', undecided 'tried:').
    matrix: the verdict table and the boundary (which single change flips a verdict)."""
    r = R()
    if action == "matrix":
        return r.matrix(ledger, claims)
    if action == "config":
        if not name or spec is None:
            raise rs.ResearchError("config needs name and spec")
        return r.config(ledger, token, name, spec, purpose)
    if action == "verdict":
        if not claim or not config or not verdict:
            raise rs.ResearchError("verdict needs claim, config and verdict")
        return r.verdict(ledger, token, claim, config, verdict, evidence)
    raise rs.ResearchError(f"unknown action {action!r}")


def research_doc(ledger: str, action: Literal["register", "plan", "sync", "check"], token: str | None = None,
                 doc: str | None = None, text: str = "", label: str = "document",
                 role: Literal["source", "deliverable", "working"] | None = None,
                 items: list[dict[str, Any]] | None = None) -> str:
    """Documents (card rs-n4). register: label, role (source = the user's original, read-only;
    deliverable = written for the user; working = the model's own), text. plan: without items, a
    draft change list for doc from its current text; with items (and token), commit it.
    sync: the rewritten text, checked against the committed plan and the reader lint.
    check: a source against its registered original, or a deliverable against the lint."""
    r = R()
    if action == "register":
        if not role:
            raise rs.ResearchError("register needs role")
        return r.doc_register(ledger, token, label, role, text)
    if not doc:
        raise rs.ResearchError(f"{action} needs doc (the D# id)")
    if action == "plan":
        return r.doc_plan(ledger, token if items else None, doc, text, items)
    if action == "sync":
        return r.doc_sync(ledger, token, doc, text)
    if action == "check":
        return r.doc_check(ledger, doc, text)
    raise rs.ResearchError(f"unknown action {action!r}")


def research_check(ledger: str, closure_of: list[str] | None = None) -> str:
    """Consistency check of the ledger, or, with closure_of, everything that depends on those ids."""
    r = R()
    if closure_of:
        return r.closure(ledger, closure_of)
    errors, warnings = r.check(ledger)
    return "\n".join([f"check: {len(errors)} error(s), {len(warnings)} warning(s)"]
                     + [f"ERROR {e}" for e in errors] + [f"WARN  {w}" for w in warnings])


READ_TOOLS = [research_show, research_check]
DELETE_TOOLS = [research_ledger_delete]
WRITE_TOOLS = [research_ledgers, research_begin, research_add, research_set, research_dispose, research_carry,
               research_push, research_next, research_done, research_drop, research_explore, research_doc,
               research_end]
TOOLS = {f.__name__: f for f in READ_TOOLS + WRITE_TOOLS + DELETE_TOOLS}
