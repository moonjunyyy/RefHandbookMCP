"""The research tools as plain functions.

The MCP server registers these functions as tools, and the CLI calls the same functions with
JSON arguments, so the fallback path (a session without the MCP server) runs the same code.
This module imports nothing from `mcp`.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
from collections.abc import Callable
from typing import Any, Literal

from . import research as rs
from .store import Handbook, HandbookError

log = logging.getLogger("refhandbook.research")

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


N1_LINE = ("N1: BEGIN ✓ (one session per message; its token goes with every call) → REGISTER (the message as "
           "U/C/A/S/R; user files as source docs; unresolved refs → RF) → DISPATCH (new U from the U; the K awaiting "
           "the user stands) → LOOP (research_next · run the card · push the exit's objects · research_done) → "
           "PROPAGATE (dispose PENDING) → SETTLE (U set or carried; doc plans synced) → END (research_end) → SHOW "
           "(the answer, then the RECEIPT line). Full card: open_entry('rs-n1').")


# ── ledgers and sessions ────────────────────────────────────────────────────

def research_ledgers(action: Literal["list", "init", "status", "export", "import", "copy", "rename"] = "list",
                     ledger: str | None = None, question: str | None = None, data: str | None = None,
                     to: str | None = None, include_log: bool = True, dry_run: bool = False, ref: str = "") -> str:
    """Manage research ledgers. list: every ledger with its open sessions. init: create one (ledger, question).
    status: machine state of one ledger. export: one ledger as JSON (include_log=false drops the
    per-session change log, the bulk of a long ledger). import: load an exported JSON string (data),
    under its own id or, with `to`, under another (a sandbox copy to inspect first); dry_run=true
    checks it and stores nothing. copy: duplicate `ledger` as `to` (a sandbox). rename: `ledger` → `to`.
    Deleting is research_ledger_delete. An export too large for one call: put it in pieces with
    research_blob (put, then append), and import with ref=<the last blob's ref>."""
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
        data = _text_or_ref(r, data or "", ref) if ref else data
        if not data:
            raise rs.ResearchError("import needs data (the JSON that export returned) or ref (a blob of it)")
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


def research_begin(ledger: str, session: str = "", view: Literal["recent", "brief", "full"] = "recent",
                   recent: int = 3, role: Literal["chat", "agent"] = "chat", label: str = "") -> str:
    """Open a session on the ledger: one per user message (role chat) or per delegated run (role
    agent). The first line is the SESSION token: pass it as `session` to every later call until
    research_end; pass it here again to re-read the ledger in the same session. Without `session`,
    an idle session of the same role (left open; it still answers for what it opened) is resumed,
    else a new one opens. Other sessions may be open beside it (an agent, another chat): a write is
    refused (CONFLICT) only if it changes an object another session changed since this one read it.
    A chat session answers at research_end for the user's directives and the continuation; an
    agent session only for what it opened. view: recent (rows changed in the last `recent` sessions plus every live row the
    obligations name; the default), brief (token and OBLIGATIONS only), full (every row).
    Never truncate its output."""
    return R().begin(ledger, session, view, recent, role, label) + "\n\n" + N1_LINE


def research_show(ledger: str, open_only: bool = False, ids: str = "", recent: int = 0, session: str = "") -> str:
    """Read the ledger. open_only: only rows that are not yet terminal. ids: only these rows
    (space-separated, e.g. "E3 H2 A1"). recent: only rows changed in the last N sessions.
    session: the reader's token — what it reads counts as seen (after a CONFLICT, read the named
    objects this way, then redo the change)."""
    r = R()
    only = set(ids.split()) if ids.strip() else None
    if recent:
        only = (only or set()) | r.recent_ids(ledger, recent)
    out = r.render(ledger, open_only, only=only)
    if session:
        r.seen(ledger, session, only, open_only)
    return out


def research_end(ledger: str, session: str, idle: str = "") -> str:
    """Close the session (for a chat session: before the reply ends). Refuses while what it answers for remains: a PENDING hit it raised, a K it
    runs, a document plan it committed and has not synced, a check error; for a chat session also
    the user's directives and a continuation. Prints the RECEIPT, the rows changed in the session
    and its changes (Δ)."""
    return R().end(ledger, session, idle)


# ── rows ─────────────────────────────────────────────────────────────────

def research_add(ledger: str, session: str, sec: str, content: str, origin: str, status: str,
                 evidence: str = "", dep: str = "", grp: str = "") -> str:
    """Add a row. sec: U C R S A Z T E H X P (plan objects K come from research_push).
    origin: user | entailed(<step>) | model. status: see card rs-ref-ledger. dep: '[rel:]ID' tokens
    (rel: req der sup eq iso spec int con). grp: alternative group for an assumption."""
    return R().add(ledger, session, sec, content, origin, status, evidence, dep, grp)


def research_set(ledger: str, session: str, id: str, field: str, value: str) -> str:
    """Replace one cell of one row (content, origin, status, evidence, dep, grp), or the whole
    map with id='M', field='content'. Replace, never append: the log keeps the history.
    An invalidating change prints PENDING hits that must be disposed."""
    return R().set(ledger, session, id, field, value)


def research_dispose(ledger: str, session: str, hit: str, of: str,
                     disposition: Literal["VALID", "RECHECK", "INVALID", "UNAFFECTED"], why: str = "") -> str:
    """Dispose one PENDING hit (a row id, or a verdict cell 'H1@config') opened by a change of `of`.
    VALID: re-derived in this session. RECHECK: mark stale (opens the next layer). INVALID: already set
    false/superseded/refuted. UNAFFECTED: history only (why required)."""
    return R().dispose(ledger, session, hit, of, disposition, why)


def research_carry(ledger: str, session: str, uid: str, why: str) -> str:
    """Keep an active directive or question (U) open past this session, with the reason."""
    return R().carry(ledger, session, uid, why)


# ── plan objects ─────────────────────────────────────────────────────────

def research_push(ledger: str, session: str, do: str, page: str, frm: str, on: str = "", exit: str = "") -> str:
    """Push a plan object K: `do` on the `on` rows, to be run on card `page` (N1 N2 N3 N3b N4 RF EX RV
    X1-X9 QM DV FM VF IM DOM-*, any handbook card id, or USER to wait for the user). frm: the K or U
    it comes from; exit: the exit of frm that returns it."""
    return R().push(ledger, session, do, page, frm, on, exit)


def research_next(ledger: str, session: str, kid: str = "") -> str:
    """Take the oldest queued K (or the given one, also one awaiting the user), mark it running,
    and print its card."""
    return R().next(ledger, session, kid)


def research_done(ledger: str, session: str, kid: str, exit: str) -> str:
    """Finish the running K through an exit. Refused unless that exit already pushed at least one
    object (a terminal exit pushes page USER)."""
    return R().done(ledger, session, kid, exit)


def research_drop(ledger: str, session: str, kid: str, why: str) -> str:
    """Drop a queued or waiting K, with the reason."""
    return R().drop(ledger, session, kid, why)


# ── exploration and documents ────────────────────────────────────────────

def research_explore(ledger: str, action: Literal["config", "verdict", "matrix"], session: str | None = None,
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
        return r.config(ledger, session, name, spec, purpose)
    if action == "verdict":
        if not claim or not config or not verdict:
            raise rs.ResearchError("verdict needs claim, config and verdict")
        return r.verdict(ledger, session, claim, config, verdict, evidence)
    raise rs.ResearchError(f"unknown action {action!r}")


def research_doc(ledger: str, action: Literal["register", "plan", "sync", "check"], session: str | None = None,
                 doc: str | None = None, text: str = "", label: str = "document",
                 role: Literal["source", "deliverable", "working"] | None = None,
                 items: list[dict[str, Any]] | None = None, ref: str = "") -> str:
    """Documents (card rs-n4). register: label, role (source = the user's original, read-only;
    deliverable = written for the user; working = the model's own), text. plan: without items, a
    draft change list for doc from its current text; with items (and session), commit it.
    sync: the rewritten text, checked against the committed plan and the reader lint.
    check: a source against its registered original, or a deliverable against the lint.
    ref: a blob (research_blob) in place of text — send a long document once, then name it by ref."""
    r = R()
    text = _text_or_ref(r, text, ref)
    if action == "register":
        if not role:
            raise rs.ResearchError("register needs role")
        return r.doc_register(ledger, session, label, role, text)
    if not doc:
        raise rs.ResearchError(f"{action} needs doc (the D# id)")
    if action == "plan":
        return r.doc_plan(ledger, session if items else None, doc, text, items)
    if action == "sync":
        return r.doc_sync(ledger, session, doc, text)
    if action == "check":
        return r.doc_check(ledger, doc, text)
    raise rs.ResearchError(f"unknown action {action!r}")


def _text_or_ref(r: rs.Research, text: str, ref: str) -> str:
    if not ref:
        return text
    if text:
        raise rs.ResearchError("pass text or ref, not both")
    try:
        return r.k.g.get_blob(ref).decode()
    except UnicodeDecodeError as e:
        raise rs.ResearchError(f"blob {ref} is not UTF-8 text") from e


def research_blob(action: Literal["put", "append", "info"], text: str = "", ref: str = "") -> str:
    """Content-addressed text in your store, so a large argument is sent once and then named by its
    hash. put: store text, get its ref. append: a new blob = the blob `ref` followed by `text`; the
    old ref is consumed (to send something larger than one call in pieces: put the first piece,
    append the rest, use the last ref). info: the size of `ref`. Tools that take a long text
    (research_doc, research_ledgers import) take `ref` in its place. Blobs are kept 7 days."""
    g = R().k.g
    if action == "put":
        sha = g.put_blob(text)
    elif action == "append":
        sha = g.append_blob(ref, text)
    elif action == "info":
        sha = g.blob_sha(ref)
    else:
        raise rs.ResearchError(f"unknown action {action!r}")
    size = g.db.execute("SELECT size FROM k_blobs WHERE sha = ?", (sha,)).fetchone()[0]
    return f"ref {sha} · {size} bytes"


def research_review(ledger: str, action: Literal["done", "proposals"] = "done", session: str | None = None,
                    why: str = "", rules: list[dict[str, Any]] | None = None) -> str:
    """Review the rules against what happened (card rs-rv), when begin lists REVIEW or a process
    question exposes a gap. done: record the finding in `why` (resets REVIEW), and propose rule
    changes in `rules`: [{id, phase (check|obligation|close|pre|derive), body, message, severity,
    replaces}]. A proposal runs at once as a warning on every ledger and blocks nothing until the
    user approves it. proposals: list the open proposals."""
    r = R()
    if action == "proposals":
        return r.proposals()
    return r.review(ledger, session, why, rules)


def research_check(ledger: str, closure_of: list[str] | None = None) -> str:
    """Consistency check of the ledger, or, with closure_of, everything that depends on those ids."""
    r = R()
    if closure_of:
        return r.closure(ledger, closure_of)
    errors, warnings = r.check(ledger)
    return "\n".join([f"check: {len(errors)} error(s), {len(warnings)} warning(s)"]
                     + [f"ERROR {e}" for e in errors] + [f"WARN  {w}" for w in warnings])


def _signals(fn: Callable[..., str]) -> Callable[..., str]:
    """Every tool on a ledger: a refusal of the work is logged on that ledger as a review signal
    (Research.note_refusal), then raised unchanged."""
    sig = inspect.signature(fn)
    if "ledger" not in sig.parameters:
        return fn

    @functools.wraps(fn)
    def tool(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except HandbookError as e:
            ledger = sig.bind_partial(*args, **kwargs).arguments.get("ledger")
            if ledger:
                try:
                    R().note_refusal(ledger, e)
                except Exception:  # noqa: BLE001 — the signal is best-effort; the refusal is what the caller needs
                    log.exception("could not log a refusal on %s", ledger)
            raise

    return tool


READ_TOOLS = [research_show, research_check]
DELETE_TOOLS = [research_ledger_delete]
WRITE_TOOLS = [research_ledgers, research_begin, research_add, research_set, research_dispose, research_carry,
               research_push, research_next, research_done, research_drop, research_explore, research_doc,
               research_end, research_blob, research_review]
for _group in (READ_TOOLS, DELETE_TOOLS, WRITE_TOOLS):
    _group[:] = [_signals(f) for f in _group]
    globals().update({f.__name__: f for f in _group})
TOOLS = {f.__name__: f for f in READ_TOOLS + WRITE_TOOLS + DELETE_TOOLS}
