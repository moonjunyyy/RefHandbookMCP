"""Research ledger: the run state of the research cards (rs-*).

The handbook holds the procedures as cards; this module holds what a research
conversation has established, assumed, planned and written, so the next turn
(or the next session) continues from the stored state instead of from memory.

    rl_ledgers   one row per research question: turn, token, open flag, map
    rl_rows      the ledger rows, one table for every section (U C R S A Z T E H X P K)
    rl_configs   named assumption configurations (exploration); 'main' is derived
    rl_verdicts  claim x configuration -> verdict
    rl_docs      registered documents: source / deliverable / working
    rl_pending   propagation hits that still need a disposition
    rl_log       every change, by turn

Every write is gated: a turn must be open and the caller must pass the token the
last device output printed, so a write proves the caller read the current state.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .store import Handbook, HandbookError, slugify

# ── vocabulary ───────────────────────────────────────────────────────────

SECTIONS = {
    "U": "directives and questions",
    "C": "judgment criteria",
    "R": "readings of the user's terms",
    "S": "symbols",
    "A": "assumptions",
    "Z": "isolated unknowns",
    "T": "known results",
    "E": "objects and structures",
    "H": "claims",
    "X": "approximations",
    "P": "parked byproducts",
    "K": "action plan objects (continuations)",
}
ALLOWED = {
    "U": {"active", "question", "answered", "done", "blocked", "superseded"},
    "C": {"mandatory", "free", "superseded"},
    "R": {"confirmed", "proposed", "superseded", "refuted"},
    "S": {"confirmed", "proposed", "superseded"},
    "A": {"on", "off", "proposed", "superseded", "stale"},
    "Z": {"isolated", "superseded"},
    "T": {"on", "proposed", "superseded", "refuted", "stale"},
    "E": {"established", "open", "proposed", "superseded", "stale", "history"},
    "H": {"open", "true", "false", "undecided", "supports", "contradicts", "inconclusive",
          "superseded", "refuted", "stale", "history", "proposed"},
    "X": {"on", "off", "proposed", "superseded", "stale"},
    "P": {"parked", "superseded"},
    "K": {"queued", "running", "blocked", "done", "dropped", "superseded", "stale"},
}
VERDICTS = {"open", "true", "false", "undecided", "stale", "supports", "contradicts", "inconclusive"}
NONTERMINAL = {"active", "question", "open", "proposed", "stale", "queued", "running", "blocked"}
INVALIDATING = {"off", "superseded", "refuted", "stale", "false"}
FINISHED = {"done", "dropped", "superseded", "refuted", "history"}
# rows a user/entailed row may not rest on
NOT_A_BASIS = {"off", "superseded", "refuted", "stale", "false", "question", "proposed", "history", "dropped"}
# rows a document may not cite: replaced, or waiting for a recheck
NOT_CITABLE = {"superseded", "stale", "dropped"}
RELS = {"req", "der", "sup", "eq", "iso", "spec", "int", "con"}
ID_RE = re.compile(r"\b([UCRSAZTEHXPK]\d+)\b")
EDGE_RE = re.compile(r"(?:(\w+):)?([UCRSAZTEHXPK]\d+)\b")
VIRTUAL_PAGES = {"USER": "Wait for the user's next message; it is resolved at N1 step 3 of the next turn."}
CARD_PREFIX = "rs-"

SCHEMA = """
CREATE TABLE IF NOT EXISTS rl_ledgers (
    id TEXT PRIMARY KEY, question TEXT NOT NULL, turn INTEGER NOT NULL DEFAULT 0,
    open INTEGER NOT NULL DEFAULT 0, token TEXT, last_closed INTEGER NOT NULL DEFAULT 0,
    closed_count INTEGER NOT NULL DEFAULT 0, prompts INTEGER NOT NULL DEFAULT 0,
    running TEXT, map TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    clock INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rl_rows (
    ledger TEXT NOT NULL REFERENCES rl_ledgers(id) ON DELETE CASCADE,
    id TEXT NOT NULL, sec TEXT NOT NULL, num INTEGER NOT NULL,
    content TEXT NOT NULL, origin TEXT NOT NULL, status TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '', dep TEXT NOT NULL DEFAULT '', grp TEXT NOT NULL DEFAULT '',
    turn_created INTEGER NOT NULL, turn_updated INTEGER NOT NULL,
    clock_updated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ledger, id)
);
CREATE TABLE IF NOT EXISTS rl_configs (
    ledger TEXT NOT NULL REFERENCES rl_ledgers(id) ON DELETE CASCADE,
    name TEXT NOT NULL, members TEXT NOT NULL, spec TEXT NOT NULL, purpose TEXT NOT NULL DEFAULT '',
    turn INTEGER NOT NULL, PRIMARY KEY (ledger, name)
);
CREATE TABLE IF NOT EXISTS rl_verdicts (
    ledger TEXT NOT NULL REFERENCES rl_ledgers(id) ON DELETE CASCADE,
    claim TEXT NOT NULL, config TEXT NOT NULL, verdict TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '', turn INTEGER NOT NULL, clock INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ledger, claim, config)
);
CREATE TABLE IF NOT EXISTS rl_docs (
    ledger TEXT NOT NULL REFERENCES rl_ledgers(id) ON DELETE CASCADE,
    id TEXT NOT NULL, label TEXT NOT NULL, role TEXT NOT NULL, owner TEXT NOT NULL,
    sha TEXT NOT NULL DEFAULT '', sections TEXT NOT NULL DEFAULT '{}', sync_turn INTEGER NOT NULL DEFAULT 0,
    plan TEXT, plan_turn INTEGER, turn INTEGER NOT NULL, sync_clock INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ledger, id)
);
CREATE TABLE IF NOT EXISTS rl_pending (
    ledger TEXT NOT NULL REFERENCES rl_ledgers(id) ON DELETE CASCADE,
    src TEXT NOT NULL, hit TEXT NOT NULL, PRIMARY KEY (ledger, src, hit)
);
CREATE TABLE IF NOT EXISTS rl_turnmarks (
    ledger TEXT NOT NULL REFERENCES rl_ledgers(id) ON DELETE CASCADE,
    turn INTEGER NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (ledger, turn, kind, ref)
);
CREATE TABLE IF NOT EXISTS rl_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ledger TEXT NOT NULL REFERENCES rl_ledgers(id) ON DELETE CASCADE,
    turn INTEGER NOT NULL, ts TEXT NOT NULL, msg TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rl_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- every device write ticks rl_ledgers.clock; these triggers stamp what that write changed, so
-- "changed since a document's sync" is exact even within one turn
CREATE TRIGGER IF NOT EXISTS rl_rows_ins AFTER INSERT ON rl_rows BEGIN
    UPDATE rl_rows SET clock_updated = (SELECT clock FROM rl_ledgers WHERE id = NEW.ledger)
     WHERE ledger = NEW.ledger AND id = NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS rl_rows_upd AFTER UPDATE OF content, origin, status, evidence, dep, grp ON rl_rows BEGIN
    UPDATE rl_rows SET clock_updated = (SELECT clock FROM rl_ledgers WHERE id = NEW.ledger)
     WHERE ledger = NEW.ledger AND id = NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS rl_verdicts_ins AFTER INSERT ON rl_verdicts BEGIN
    UPDATE rl_verdicts SET clock = (SELECT clock FROM rl_ledgers WHERE id = NEW.ledger)
     WHERE ledger = NEW.ledger AND claim = NEW.claim AND config = NEW.config;
END;
CREATE TRIGGER IF NOT EXISTS rl_verdicts_upd AFTER UPDATE OF verdict, evidence ON rl_verdicts BEGIN
    UPDATE rl_verdicts SET clock = (SELECT clock FROM rl_ledgers WHERE id = NEW.ledger)
     WHERE ledger = NEW.ledger AND claim = NEW.claim AND config = NEW.config;
END;
"""

# Visible text of a deliverable must read as prose: these are ledger artefacts.
LEAKS = [
    (re.compile(r"⟵"), "basis tag"),
    (re.compile(r"\b(RECEIPT|TOKEN|PENDING)\b|NEXT:"), "device output"),
    (re.compile(r"\[unverified\]"), "status token [unverified]; write 미검증 / unverified in words"),
    (re.compile(r"\[(?:[UCRSAZTEHXPK]\d+(?:\s*[;,]\s*|\s+)?)+\]"), "bracketed ledger ids; move them to the section's basis comment"),
    (re.compile(r"`(computed|measured|sourced|followed|proposed|superseded|stale|entailed|pointer)[^`]*`"), "status vocabulary in code"),
    (re.compile(r"(?<![\w.])@(USER|N\d\w*|X\d|RF|EX|QM|DV|FM|VF|IM)\b"), "page reference"),
]
MARK_RE = re.compile(r"^\s*<!--\s*sec:\s*(\S+)(.*?)-->\s*$")
HEAD_RE = re.compile(r"^#{1,6}\s")


class ResearchError(HandbookError):
    """A refusal the caller resolves by doing what the message names."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def unverified(evidence: str | None) -> bool:
    """The evidence *is* unverified: its first token says so. A footnote elsewhere in the cell
    ("the quoted step is [unverified]") does not make the row's own basis unverified."""
    return bool(re.match(r"\s*\[?unverified\b", evidence or "", re.I))


def key(status: str | None) -> str:
    m = re.match(r"\s*([A-Za-z]+)", status or "")
    return m.group(1).lower() if m else ""


def edges(dep: str) -> list[tuple[str, str]]:
    return [((r or "req").lower(), i) for r, i in EDGE_RE.findall(dep or "")]


def page_card_id(page: str) -> str:
    p = page.strip().lstrip("@")
    return p if p.startswith(CARD_PREFIX) else CARD_PREFIX + slugify(p)


class Research:
    def __init__(self, hb: Handbook):
        self.hb = hb
        self.db = hb.db
        self.db.executescript(SCHEMA)

    # ── plumbing ─────────────────────────────────────────────────────────

    def _ledger(self, ledger: str) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM rl_ledgers WHERE id = ?", (ledger,)).fetchone()
        if row is None:
            known = ", ".join(r[0] for r in self.db.execute("SELECT id FROM rl_ledgers ORDER BY id")) or "none"
            raise ResearchError(f"no ledger {ledger!r}; create it with init. Known: {known}")
        return dict(row)

    def _rows(self, ledger: str, sec: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM rl_rows WHERE ledger = ?" + (" AND sec = ?" if sec else "") + " ORDER BY sec, num"
        rows = [dict(r) for r in self.db.execute(sql, (ledger, sec) if sec else (ledger,))]
        order = list(SECTIONS)
        return sorted(rows, key=lambda r: (order.index(r["sec"]), r["num"]))

    def _row(self, ledger: str, rid: str) -> dict[str, Any]:
        r = self.db.execute("SELECT * FROM rl_rows WHERE ledger = ? AND id = ?", (ledger, rid)).fetchone()
        if r is None:
            raise ResearchError(f"no row {rid!r} in ledger {ledger!r}")
        return dict(r)

    def _digest(self, ledger: str) -> str:
        h = hashlib.sha1(ledger.encode())
        for table, order in (("rl_rows", "id"), ("rl_configs", "name"), ("rl_verdicts", "claim, config"),
                             ("rl_docs", "id"), ("rl_pending", "src, hit")):
            for r in self.db.execute(f"SELECT * FROM {table} WHERE ledger = ? ORDER BY {order}", (ledger,)):
                h.update(json.dumps(list(r), ensure_ascii=False, default=str).encode())
        lg = self._ledger(ledger)
        h.update(f"{lg['turn']}|{lg['open']}|{lg['running']}|{lg['map']}".encode())
        return h.hexdigest()[:10]

    def _log(self, ledger: str, turn: int, msg: str) -> None:
        self.db.execute("INSERT INTO rl_log (ledger, turn, ts, msg) VALUES (?, ?, ?, ?)", (ledger, turn, _now(), msg))

    def _gate(self, ledger: str, token: str | None) -> dict[str, Any]:
        lg = self._ledger(ledger)
        if not lg["open"]:
            raise ResearchError(f"REFUSED: no turn is open on {ledger!r}. Run research_begin first (untruncated).")
        if self._digest(ledger) != lg["token"]:
            raise ResearchError(
                f"REFUSED: ledger {ledger!r} changed outside this caller since the last device output "
                f"(another session, or a direct edit). Report it (X7), then re-read with research_begin turn={lg['turn']}."
            )
        if token != lg["token"]:
            raise ResearchError(
                f"REFUSED: stale or missing token (the ledger moved on, perhaps through another session). "
                f"Re-read with research_begin turn={lg['turn']}: the token is on the first line of its output."
            )
        return lg

    def _seal(self, ledger: str) -> str:
        token = self._digest(ledger)
        self.db.execute("UPDATE rl_ledgers SET token = ? WHERE id = ?", (token, ledger))
        return token

    def _touch(self, ledger: str, turn: int, *ids: str) -> None:
        self.db.executemany("INSERT OR IGNORE INTO rl_turnmarks VALUES (?, ?, 'touched', ?, '')",
                            [(ledger, turn, i) for i in ids])

    def _write(self, ledger: str, token: str | None, fn) -> str:
        """Run fn(lg) inside one transaction behind the gate; return its text plus the next token."""
        with self.db:
            lg = self._gate(ledger, token)
            self.db.execute("UPDATE rl_ledgers SET clock = clock + 1 WHERE id = ?", (ledger,))
            out = fn(lg)
            new = self._seal(ledger)
        return f"{out}\nTOKEN {new}"

    # ── ledgers ──────────────────────────────────────────────────────────

    def ledgers(self) -> str:
        rows = self.db.execute(
            "SELECT id, question, turn, open, last_closed FROM rl_ledgers ORDER BY id").fetchall()
        if not rows:
            return "No research ledgers yet. Create one with init."
        return "\n".join(f"{r['id']}  turn {r['turn']}{' (open)' if r['open'] else ''} · last closed {r['last_closed']} · {r['question']}"
                         for r in rows)

    def init(self, ledger: str, question: str) -> str:
        lid = slugify(ledger)
        if self.db.execute("SELECT 1 FROM rl_ledgers WHERE id = ?", (lid,)).fetchone():
            raise ResearchError(f"ledger {lid!r} exists; ledgers are never recreated. Use research_begin.")
        with self.db:
            self.db.execute("INSERT INTO rl_ledgers (id, question, created_at, map) VALUES (?, ?, ?, ?)",
                            (lid, question, _now(), f"Q  {question}"))
            self._seal(lid)
        return f"created ledger {lid!r}: {question}\nNext: research_begin(ledger={lid!r}, turn=1)"

    def status(self, ledger: str) -> dict[str, Any]:
        lg = self._ledger(ledger)
        pend = self._column("SELECT hit FROM rl_pending WHERE ledger = ?", ledger)
        return {k: lg[k] for k in ("turn", "open", "last_closed", "closed_count", "prompts", "running")} | {"pending": pend}

    def prompt(self, ledger: str) -> str:
        """Hook support: count one user prompt and say what the turn must start with."""
        with self.db:
            self.db.execute("UPDATE rl_ledgers SET prompts = prompts + 1 WHERE id = ?", (ledger,))
            lg = self._ledger(ledger)
            # a hook is not a model write: keep the token valid for the reader
            self.db.execute("UPDATE rl_ledgers SET token = ? WHERE id = ?", (self._digest(ledger), ledger))
        nxt = lg["turn"] if lg["open"] else lg["prompts"]
        return f"[research cycle active on {ledger!r}] First action this turn: research_begin(ledger={ledger!r}, turn={nxt})."

    def _column(self, sql: str, *params: Any) -> list[Any]:
        return [r[0] for r in self.db.execute(sql, params)]

    # ── reading ──────────────────────────────────────────────────────────

    def main_members(self, ledger: str) -> list[str]:
        return [r["id"] for r in self._rows(ledger) if r["sec"] in ("A", "T") and key(r["status"]) == "on"]

    def _configs(self, ledger: str) -> dict[str, dict[str, Any]]:
        out = {"main": {"name": "main", "members": self.main_members(ledger), "spec": "A/T rows that are on",
                        "purpose": "the user's main line", "turn": 0}}
        for r in self.db.execute("SELECT * FROM rl_configs WHERE ledger = ? ORDER BY turn, name", (ledger,)):
            out[r["name"]] = dict(r) | {"members": r["members"].split()}
        return out

    def render(self, ledger: str, open_only: bool = False, only: set[str] | None = None, title: str = "") -> str:
        """The ledger as tables. `only` restricts the rows (sections without rows are left out, and so
        are the configuration, verdict and document blocks unless a claim or K is among the rows)."""
        lg = self._ledger(ledger)
        out = [f"# Ledger — {lg['question']}  [{ledger}] · turn {lg['turn']}{' (open)' if lg['open'] else ''}"
               + (f" · {title}" if title else "")]
        rows = self._rows(ledger)
        for sec, name in SECTIONS.items():
            mine = [r for r in rows if r["sec"] == sec and (not open_only or key(r["status"]) in NONTERMINAL)
                    and (only is None or r["id"] in only)]
            if (open_only or only is not None) and not mine:
                continue
            out += ["", f"## {sec} — {name}", "| id | content | origin | status | evidence | dep |" + (" grp |" if sec == "A" else ""),
                    "|---|---|---|---|---|---|" + ("---|" if sec == "A" else "")]
            for r in mine:
                cells = [r["id"], r["content"], r["origin"], r["status"], r["evidence"], r["dep"]] + ([r["grp"]] if sec == "A" else [])
                out.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
        if only is not None:
            hs = [i for i in only if i.startswith("H")]
            if hs:
                out += ["", "## V — verdicts of these claims", self.matrix(ledger, claims=hs, header=False)]
            return "\n".join(out)
        cfgs = self._configs(ledger)
        out += ["", "## G — configurations (main = the user's line; others = exploration)"]
        for c in cfgs.values():
            tag = "" if c["name"] == "main" else f"  ← {c['spec']}"
            out.append(f"- **{c['name']}**: {{{', '.join(c['members'])}}}{tag}" + (f" — {c['purpose']}" if c["purpose"] and c["name"] != "main" else ""))
        out += ["", "## V — verdicts (claim × configuration)", self.matrix(ledger, header=False)]
        docs = self.db.execute("SELECT * FROM rl_docs WHERE ledger = ? ORDER BY id", (ledger,)).fetchall()
        if docs:
            out += ["", "## D — documents"]
            out += [f"- {d['id']} {d['role']} ({d['owner']}) {d['label']} · synced turn {d['sync_turn']}"
                    + (" · PLAN PENDING" if d["plan"] else "") for d in docs]
        out += ["", "## M — question map", lg["map"]]
        return "\n".join(out)

    def matrix(self, ledger: str, claims: list[str] | None = None, header: bool = True) -> str:
        cfgs = list(self._configs(ledger))
        hs = [r for r in self._rows(ledger, "H") if not claims or r["id"] in claims]
        if not hs:
            return "(no claims)"
        v = {(r["claim"], r["config"]): r for r in self.db.execute("SELECT * FROM rl_verdicts WHERE ledger = ?", (ledger,))}
        used = [c for c in cfgs if c == "main" or any((h["id"], c) in v for h in hs)]
        lines = (["Verdicts per configuration:"] if header else []) + [
            "| claim | " + " | ".join(used) + " |", "|---|" + "---|" * len(used)]
        for h in hs:
            lines.append(f"| {h['id']} {h['content'][:40]} | " + " | ".join(
                v[(h["id"], c)]["verdict"] if (h["id"], c) in v else "·" for c in used) + " |")
        flips = self.boundary(ledger, [h["id"] for h in hs])
        if flips:
            lines += ["", "Boundary (one change between two configurations flips the verdict):"] + [f"- {f}" for f in flips]
        return "\n".join(lines)

    def boundary(self, ledger: str, claims: list[str]) -> list[str]:
        cfgs = self._configs(ledger)
        v = {(r["claim"], r["config"]): r["verdict"] for r in self.db.execute(
            "SELECT * FROM rl_verdicts WHERE ledger = ?", (ledger,))}
        decided = {"true", "false"}
        out = []
        names = list(cfgs)
        for h in claims:
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    va, vb = v.get((h, a)), v.get((h, b))
                    if va not in decided or vb not in decided or va == vb:
                        continue
                    sa, sb = set(cfgs[a]["members"]), set(cfgs[b]["members"])
                    only_a, only_b = sorted(sa - sb), sorted(sb - sa)
                    if len(only_a) + len(only_b) == 1:
                        x = (only_a or only_b)[0]
                        with_x, without = (a, b) if only_a else (b, a)
                        out.append(f"{h}: {x} decides it — with {x} ({with_x}) {v[(h, with_x)]}, "
                                   f"without ({without}) {v[(h, without)]}")
                    elif len(only_a) == 1 and len(only_b) == 1:
                        out.append(f"{h}: swapping {only_a[0]} ({a}, {va}) for {only_b[0]} ({b}, {vb}) flips it")
        return out

    # ── turn protocol ────────────────────────────────────────────────────

    def recent_ids(self, ledger: str, turns: int) -> set[str]:
        lg = self._ledger(ledger)
        since = max(0, lg["turn"] - max(0, turns) + 1)
        ids = set(self._column("SELECT id FROM rl_rows WHERE ledger = ? AND turn_updated >= ?", ledger, since))
        ids |= set(self._column("SELECT ref FROM rl_turnmarks WHERE ledger = ? AND turn >= ? AND kind = 'touched'",
                                ledger, since))
        # what the obligations will name: live K, open directives, rows to re-judge
        for r in self._rows(ledger):
            k = key(r["status"])
            if (r["sec"] == "K" and k in {"queued", "running", "blocked"}) or \
               (r["sec"] == "U" and k in {"active", "question"}) or \
               (r["sec"] not in ("K", "U") and k in {"stale", "proposed", "open"}):
                ids.add(r["id"])
        return ids

    def begin(self, ledger: str, turn: int, view: str = "recent", recent: int = 3) -> str:
        if view not in ("brief", "recent", "full"):
            raise ResearchError("view must be brief, recent or full")
        lg = self._ledger(ledger)
        notes = []
        with self.db:
            if self._digest(ledger) != lg["token"]:
                notes.append("WARNING: ledger changed outside this caller since the last device output "
                             "(another session or a direct edit) — report it (X7) and re-read the changed rows.")
            if lg["open"] and lg["turn"] != turn:
                raise ResearchError(f"REFUSED: turn {lg['turn']} is still open. Close it with research_end, "
                                    "or report why it cannot close.")
            if not lg["open"] and turn <= lg["last_closed"]:
                raise ResearchError(f"REFUSED: turn {turn} is already closed (last closed {lg['last_closed']}). "
                                    f"Use turn={lg['last_closed'] + 1}.")
            if not lg["open"] and turn > lg["last_closed"] + 1:
                notes.append(f"WARNING: turn gap — last closed turn is {lg['last_closed']}, this is {turn}. "
                             "Turns ran outside the cycle; report it (X7) and register what they changed.")
                self._log(ledger, turn, f"gap: last closed {lg['last_closed']}")
            self.db.execute("UPDATE rl_ledgers SET open = 1, turn = ? WHERE id = ?", (turn, ledger))
            token = self._seal(ledger)
        out = [f"TOKEN {token}   LEDGER {ledger}   TURN {turn}   (every write needs this token; never truncate this output)"]
        out += notes
        n = self.db.execute("SELECT count(*) FROM rl_rows WHERE ledger = ?", (ledger,)).fetchone()[0]
        if view == "full":
            out += [self.render(ledger)]
        elif view == "recent":
            ids = self.recent_ids(ledger, recent)
            out += [self.render(ledger, only=ids, title=f"VIEW recent: {len(ids)} of {n} rows (changed in the last "
                                                       f"{recent} turns, or live); research_show for the rest"),
                    "", "## M — question map", self._ledger(ledger)["map"]]
        else:
            out += [f"VIEW brief: {n} rows not shown; research_show (or research_begin view=recent) reads them"]
        out += ["", "=" * 20 + " OBLIGATIONS THIS TURN " + "=" * 20]
        out += self._obligations(ledger)
        return "\n".join(out)

    def _obligations(self, ledger: str) -> list[str]:
        out = []
        for src, hit in self.db.execute("SELECT src, hit FROM rl_pending WHERE ledger = ? ORDER BY src, hit", (ledger,)):
            out.append(f"  PENDING   {hit} (from {src}): dispose")
        rows = self._rows(ledger)
        for r in rows:
            k = key(r["status"])
            if r["sec"] == "K" and k in {"queued", "running", "blocked"}:
                tag = "AWAITING USER" if k == "blocked" else k.upper()
                out.append(f"  K-{tag:13} {r['id']}: {r['content'][:80]}")
        for r in rows:
            k = key(r["status"])
            if r["sec"] == "U" and k in {"active", "question"}:
                out.append(f"  DIRECTIVE {r['id']} ({k}): address it, or carry with a reason :: {r['content'][:70]}")
            elif r["sec"] not in ("K", "U") and k in {"stale", "proposed", "open"}:
                out.append(f"  {k.upper():9} {r['id']}: re-judge :: {r['content'][:70]}")
        for c, h in self.db.execute("SELECT config, claim FROM rl_verdicts WHERE ledger = ? AND verdict = 'stale'", (ledger,)):
            out.append(f"  STALE     {h}@{c}: recheck the verdict")
        for d in self.db.execute("SELECT * FROM rl_docs WHERE ledger = ? AND role = 'deliverable'", (ledger,)):
            behind = self._changed_since(ledger, d["sync_clock"])
            if d["plan"]:
                out.append(f"  DOC-PLAN  {d['id']} {d['label']}: planned changes not synced — rewrite, then research_doc sync")
            elif behind and d["sync_clock"]:
                out.append(f"  DOC       {d['id']} {d['label']}: {len(behind)} ledger change(s) since its sync — "
                           "plan before the next edit (research_doc plan)")
        out.append(f"  {len(out)} obligation(s). research_end refuses while PENDING, a running K, unaddressed "
                   "DIRECTIVES or an unsynced DOC-PLAN remain.")
        return out

    def end(self, ledger: str, token: str | None, turn: int, idle: str = "") -> str:
        with self.db:
            lg = self._gate(ledger, token)
            if lg["turn"] != turn:
                raise ResearchError(f"REFUSED: the open turn is {lg['turn']}, not {turn}")
            blockers = [f"PENDING {hit} (from {src})" for src, hit in self.db.execute(
                "SELECT src, hit FROM rl_pending WHERE ledger = ?", (ledger,))]
            touched = set(self._column("SELECT ref FROM rl_turnmarks WHERE ledger = ? AND turn = ? AND kind = 'touched'", ledger, turn))
            carried = set(self._column("SELECT ref FROM rl_turnmarks WHERE ledger = ? AND turn = ? AND kind = 'carry'", ledger, turn))
            rows = self._rows(ledger)
            ks = [r for r in rows if r["sec"] == "K"]
            for r in ks:
                if key(r["status"]) == "running":
                    blockers.append(f"K {r['id']} is still running: finish its card with research_done")
            if ks and not any(key(r["status"]) in {"queued", "blocked"} for r in ks):
                blockers.append("NO CONTINUATION: push the next K (a queued step, or @USER awaiting the user) before ending")
            for r in rows:
                if r["sec"] == "U" and key(r["status"]) in {"active", "question"} and r["id"] not in touched | carried:
                    blockers.append(f"DIRECTIVE {r['id']} neither addressed (set) nor carried")
            if not any(t.startswith("U") for t in touched) and not idle:
                blockers.append("NO DIRECTIVE this turn: register or update the user's message as U, "
                                "or end with idle=\"<why nothing was asked>\"")
            for d in self.db.execute("SELECT id, label FROM rl_docs WHERE ledger = ? AND plan IS NOT NULL", (ledger,)):
                blockers.append(f"DOC-PLAN {d['id']} {d['label']} committed but not synced")
            errors, warnings = self.check(ledger)
            blockers += [f"CHECK {e}" for e in errors]
            if blockers:
                raise ResearchError("REFUSED: turn cannot close:\n  " + "\n  ".join(blockers))
            if idle:
                self._log(ledger, turn, f"idle: {idle}")
            self.db.execute("UPDATE rl_ledgers SET open = 0, last_closed = ?, closed_count = closed_count + 1 WHERE id = ?",
                            (turn, ledger))
            token = self._seal(ledger)
        delta = self._column("SELECT msg FROM rl_log WHERE ledger = ? AND turn = ? ORDER BY seq", ledger, turn)
        out = [f"RECEIPT ledger {ledger} · turn {turn} · token {token} · Δ {len(delta)} · check 0 errors, {len(warnings)} warnings"]
        out += [f"WARN  {w}" for w in warnings]
        changed = set(self._column("SELECT ref FROM rl_turnmarks WHERE ledger = ? AND turn = ? AND kind = 'touched'",
                                   ledger, turn))
        changed &= set(self._column("SELECT id FROM rl_rows WHERE ledger = ?", ledger))
        out += [self.render(ledger, only=changed, title=f"rows changed this turn: {len(changed)}")
                if changed else "(no row changed this turn)",
                "", f"Δ turn {turn}: " + (" · ".join(delta) if delta else "none"),
                f"NEXT: first action of the next turn, before anything else, even for a one-word message: "
                f"research_begin(ledger={ledger!r}, turn={turn + 1})"]
        return "\n".join(out)

    # ── rows ─────────────────────────────────────────────────────────────

    def add(self, ledger: str, token: str | None, sec: str, content: str, origin: str, status: str,
            evidence: str = "", dep: str = "", grp: str = "") -> str:
        sec = sec.upper()
        if sec not in SECTIONS:
            raise ResearchError(f"unknown section {sec!r}; use one of {' '.join(SECTIONS)}")
        if not content.strip() or not origin.strip():
            raise ResearchError("content and origin are required")
        if key(status) not in ALLOWED[sec]:
            raise ResearchError(f"REFUSED: status {status!r} not allowed in {sec}; use one of {sorted(ALLOWED[sec])}")
        if grp and sec != "A":
            raise ResearchError("grp (alternative group) applies to assumptions only")
        if sec == "K":
            raise ResearchError("plan objects are created with research_push, not research_add")

        def fn(lg):
            known = set(self._column("SELECT id FROM rl_rows WHERE ledger = ?", ledger))
            for r, d in edges(dep):
                if r not in RELS:
                    raise ResearchError(f"unknown relation {r!r}; use one of {sorted(RELS)}")
                if d not in known:
                    raise ResearchError(f"dep {d} does not exist")
            n = 1 + (self.db.execute("SELECT max(num) FROM rl_rows WHERE ledger = ? AND sec = ?", (ledger, sec)).fetchone()[0] or 0)
            rid = f"{sec}{n}"
            self.db.execute("INSERT INTO rl_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                            (ledger, rid, sec, n, content.strip(), origin.strip(), status.strip(), evidence.strip(),
                             dep.strip(), grp.strip(), lg["turn"], lg["turn"]))
            self._log(ledger, lg["turn"], f"+{rid} {status}")
            self._touch(ledger, lg["turn"], rid)
            if sec in ("A", "T") and key(status) == "on":
                self._open_main_hits(ledger, rid, lg["turn"])
            return rid

        return self._write(ledger, token, fn)

    def set(self, ledger: str, token: str | None, rid: str, field: str, value: str) -> str:
        if rid == "M":
            if field != "content":
                raise ResearchError("the map M has one field: content (replaced whole)")

            def fm(lg):
                self.db.execute("UPDATE rl_ledgers SET map = ? WHERE id = ?", (value, ledger))
                self._log(ledger, lg["turn"], "~M replaced")
                return "map replaced"
            return self._write(ledger, token, fm)
        if field not in ("content", "origin", "status", "evidence", "dep", "grp"):
            raise ResearchError("field must be one of content, origin, status, evidence, dep, grp")

        def fn(lg):
            r = self._row(ledger, rid)
            if field == "status" and key(value) not in ALLOWED[r["sec"]]:
                raise ResearchError(f"REFUSED: status {value!r} not allowed in {r['sec']}; use one of {sorted(ALLOWED[r['sec']])}")
            if field == "status" and r["sec"] == "H" and key(value) in VERDICTS and key(value) not in ("stale",):
                main = self.db.execute("SELECT verdict FROM rl_verdicts WHERE ledger = ? AND claim = ? AND config = 'main'",
                                       (ledger, rid)).fetchone()
                if main and main[0] != key(value):
                    raise ResearchError(f"REFUSED: {rid} has main verdict {main[0]!r}; change it with research_explore verdict")
            if field == "dep":
                known = set(self._column("SELECT id FROM rl_rows WHERE ledger = ?", ledger))
                for rel, d in edges(value):
                    if rel not in RELS or d not in known:
                        raise ResearchError(f"bad dep {rel}:{d}")
            old = r[field]
            self.db.execute(f"UPDATE rl_rows SET {field} = ?, turn_updated = ? WHERE ledger = ? AND id = ?",
                            (value.strip(), lg["turn"], ledger, rid))
            self._log(ledger, lg["turn"], f"~{rid}.{field}: {old} → {value.strip()}")
            self._touch(ledger, lg["turn"], rid)
            msg = [f"{rid}.{field}: {old} → {value.strip()}"]
            invalidated = field == "status" and key(value) in INVALIDATING and key(old) not in INVALIDATING
            if invalidated or field in ("content", "dep"):
                # switching a premise off is a main-line decision; the exploration cells that hold
                # the premise keep it, so only supersession, refutation or new content reaches them
                switch_only = r["sec"] in ("A", "T") and field == "status" and key(value) == "off"
                hits = self._direct_hits(ledger, rid, configs=not switch_only)
                if r["sec"] in ("A", "T") and field == "status" and (key(old) == "on") != (key(value) == "on"):
                    hits |= self._main_verdict_hits(ledger)
                for h in sorted(hits):
                    self.db.execute("INSERT OR IGNORE INTO rl_pending VALUES (?, ?, ?)", (ledger, rid, h))
                if hits:
                    msg.append(f"PENDING {rid}: {' '.join(sorted(hits))} — dispose each before research_end")
            elif r["sec"] in ("A", "T") and field == "status" and (key(old) == "on") != (key(value) == "on"):
                hits = self._main_verdict_hits(ledger)
                for h in sorted(hits):
                    self.db.execute("INSERT OR IGNORE INTO rl_pending VALUES (?, ?, ?)", (ledger, rid, h))
                if hits:
                    msg.append(f"PENDING {rid}: {' '.join(sorted(hits))} — the main line changed; dispose each")
            return "\n".join(msg)

        return self._write(ledger, token, fn)

    def _open_main_hits(self, ledger: str, rid: str, turn: int) -> None:
        for h in self._main_verdict_hits(ledger):
            self.db.execute("INSERT OR IGNORE INTO rl_pending VALUES (?, ?, ?)", (ledger, rid, h))

    def _main_verdict_hits(self, ledger: str) -> set[str]:
        return {f"{c}@main" for c in self._column(
            "SELECT claim FROM rl_verdicts WHERE ledger = ? AND config = 'main' AND verdict NOT IN ('stale', 'open')", ledger)}

    def _direct_hits(self, ledger: str, x: str, configs: bool = True) -> set[str]:
        """Everything that rests on x: rows whose dep cites it, verdict cells of configurations that
        contain it (configs=False when only x's main-line switch changed), and main verdicts."""
        hits = set()
        for r in self._rows(ledger):
            if r["sec"] == "K" or key(r["status"]) in FINISHED or r["id"] == x:
                continue  # a plan object's `on` ids say where it works, not what it rests on
            if x in {d for _, d in edges(r["dep"])}:
                hits.add(r["id"])
        for c in (self._configs(ledger).values() if configs else ()):
            if c["name"] != "main" and x in c["members"]:
                for claim in self._column("SELECT claim FROM rl_verdicts WHERE ledger = ? AND config = ? AND verdict NOT IN ('stale','open')",
                                          ledger, c["name"]):
                    hits.add(f"{claim}@{c['name']}")
        if x in self.main_members(ledger):
            # a premise of the main line changed: every main verdict is suspect
            hits |= self._main_verdict_hits(ledger)
        return hits

    def dispose(self, ledger: str, token: str | None, hit: str, of: str, as_: str, why: str = "") -> str:
        v = as_.upper()
        if v not in {"VALID", "RECHECK", "INVALID", "UNAFFECTED"}:
            raise ResearchError("as must be VALID, RECHECK, INVALID or UNAFFECTED")

        def fn(lg):
            if not self.db.execute("SELECT 1 FROM rl_pending WHERE ledger = ? AND src = ? AND hit = ?", (ledger, of, hit)).fetchone():
                pend = [f"{h} (from {s})" for s, h in self.db.execute("SELECT src, hit FROM rl_pending WHERE ledger = ?", (ledger,))]
                raise ResearchError(f"REFUSED: {hit} is not pending under {of}; pending: {', '.join(pend) or 'none'}")
            touched = set(self._column("SELECT ref FROM rl_turnmarks WHERE ledger = ? AND turn = ? AND kind = 'touched'", ledger, lg["turn"]))
            msg = []
            if "@" in hit:  # a verdict cell
                claim, cfg = hit.split("@", 1)
                if v == "INVALID":
                    raise ResearchError("a verdict cell is RECHECKed (marked stale) or re-derived (VALID), not INVALID")
                if v == "RECHECK":
                    self.db.execute("UPDATE rl_verdicts SET verdict = 'stale', turn = ? WHERE ledger = ? AND claim = ? AND config = ?",
                                    (lg["turn"], ledger, claim, cfg))
                    if cfg == "main":
                        self.db.execute("UPDATE rl_rows SET status = ?, turn_updated = ? WHERE ledger = ? AND id = ?",
                                        (f"stale({of})", lg["turn"], ledger, claim))
                        more = self._direct_hits(ledger, claim) - {hit}
                        for h in sorted(more):
                            self.db.execute("INSERT OR IGNORE INTO rl_pending VALUES (?, ?, ?)", (ledger, claim, h))
                        if more:
                            msg.append(f"PENDING {claim}: {' '.join(sorted(more))}")
                if v == "VALID" and hit not in touched:
                    raise ResearchError(f"REFUSED: VALID needs the verdict {hit} re-recorded this turn (research_explore verdict)")
            else:
                r = self._row(ledger, hit)
                k = key(r["status"])
                if v == "RECHECK":
                    was_main = r["sec"] in ("A", "T") and k == "on"
                    self.db.execute("UPDATE rl_rows SET status = ?, turn_updated = ? WHERE ledger = ? AND id = ?",
                                    (f"stale({of})", lg["turn"], ledger, hit))
                    self._log(ledger, lg["turn"], f"~{hit}.status: {r['status']} → stale({of})")
                    if was_main:  # it left the main line: every main verdict is suspect
                        cells = self._main_verdict_hits(ledger)
                        for h in sorted(cells):
                            self.db.execute("INSERT OR IGNORE INTO rl_pending VALUES (?, ?, ?)", (ledger, hit, h))
                        if cells:
                            msg.append(f"{hit} left the main line until re-derived; PENDING {hit}: {' '.join(sorted(cells))}")
                    if r["sec"] == "H":  # the claim itself is in doubt: every verdict cell of it is
                        n = self.db.execute("UPDATE rl_verdicts SET verdict = 'stale', turn = ? WHERE ledger = ? AND claim = ?"
                                            " AND verdict != 'stale'", (lg["turn"], ledger, hit)).rowcount
                        if n:
                            msg.append(f"{hit}: {n} verdict cell(s) marked stale")
                    more = self._direct_hits(ledger, hit)
                    for h in sorted(more):
                        self.db.execute("INSERT OR IGNORE INTO rl_pending VALUES (?, ?, ?)", (ledger, hit, h))
                    if more:
                        msg.append(f"PENDING {hit}: {' '.join(sorted(more))}")
                elif v == "INVALID" and k not in INVALIDATING:
                    raise ResearchError(f"REFUSED: set {hit} to false / superseded / refuted first, then dispose INVALID")
                elif v == "VALID" and hit not in touched:
                    raise ResearchError(f"REFUSED: VALID needs {hit} re-derived this turn (a new row, or a set), then dispose")
            if v == "UNAFFECTED" and not why:
                raise ResearchError("REFUSED: UNAFFECTED needs a why")
            self.db.execute("DELETE FROM rl_pending WHERE ledger = ? AND hit = ?", (ledger, hit))
            self._log(ledger, lg["turn"], f"dispose {hit} of {of}: {v}" + (f" ({why})" if why else ""))
            self._touch(ledger, lg["turn"], hit)
            return "\n".join([f"{hit} of {of}: {v}"] + msg)

        return self._write(ledger, token, fn)

    def carry(self, ledger: str, token: str | None, uid: str, why: str) -> str:
        def fn(lg):
            r = self._row(ledger, uid)
            if r["sec"] != "U":
                raise ResearchError(f"REFUSED: {uid} is not a U row")
            if not why.strip():
                raise ResearchError("REFUSED: carry needs a why")
            self.db.execute("INSERT OR REPLACE INTO rl_turnmarks VALUES (?, ?, 'carry', ?, ?)", (ledger, lg["turn"], uid, why))
            self._log(ledger, lg["turn"], f"carry {uid}: {why}")
            return f"carry {uid}: {why}"
        return self._write(ledger, token, fn)

    # ── plan objects (K) ─────────────────────────────────────────────────

    def _resolve_page(self, page: str) -> str:
        p = page.strip().lstrip("@")
        if p.upper() in VIRTUAL_PAGES:
            return p.upper()
        for cand in (p, page_card_id(p)):
            if self.hb.exists(cand):
                return cand
        cards = self._column("SELECT id FROM entries WHERE id LIKE 'rs-%' ORDER BY id")
        names = " ".join(c[len(CARD_PREFIX):].upper() for c in cards)
        raise ResearchError(f"REFUSED: unknown page {page!r}; research pages: {names} USER (or any handbook card id)")

    def push(self, ledger: str, token: str | None, do: str, page: str, frm: str, on: str = "", exit: str = "") -> str:
        target = self._resolve_page(page)

        def fn(lg):
            known = set(self._column("SELECT id FROM rl_rows WHERE ledger = ?", ledger))
            if frm not in known:
                raise ResearchError(f"REFUSED: from {frm} does not exist")
            for d in ID_RE.findall(on or ""):
                if d not in known:
                    raise ResearchError(f"REFUSED: on {d} does not exist")
            status = "blocked: user" if target == "USER" else "queued"
            ev = f"from:{frm}" + (f"/{exit}" if exit else "") + f" @{target}"
            if target == "USER":
                waiting = [r for r in self._rows(ledger, "K")
                           if key(r["status"]) == "blocked" and r["evidence"].endswith("@USER")]
                if waiting:  # one standing continuation: re-arm it with the new objects
                    w = waiting[-1]
                    self.db.execute("UPDATE rl_rows SET content = ?, evidence = ?, dep = ?, turn_updated = ? "
                                    "WHERE ledger = ? AND id = ?",
                                    (f"{do} → @USER", ev, " ".join(ID_RE.findall(on or "")), lg["turn"], ledger, w["id"]))
                    self._log(ledger, lg["turn"], f"~{w['id']} re-armed: {do}")
                    self._touch(ledger, lg["turn"], w["id"])
                    return f"{w['id']} (the standing @USER continuation, re-armed)"
            n = 1 + (self.db.execute("SELECT max(num) FROM rl_rows WHERE ledger = ? AND sec = 'K'", (ledger,)).fetchone()[0] or 0)
            kid = f"K{n}"
            self.db.execute("INSERT INTO rl_rows VALUES (?, ?, 'K', ?, ?, ?, ?, ?, ?, '', ?, ?, 0)",
                            (ledger, kid, n, f"{do} → @{target}", f"entailed({frm})", status, ev,
                             " ".join(ID_RE.findall(on or "")), lg["turn"], lg["turn"]))
            self._log(ledger, lg["turn"], f"+{kid} {status}")
            self._touch(ledger, lg["turn"], kid)
            return kid
        return self._write(ledger, token, fn)

    def next(self, ledger: str, token: str | None, kid: str = "") -> str:
        def fn(lg):
            ks = self._rows(ledger, "K")
            if any(key(r["status"]) == "running" for r in ks):
                raise ResearchError("REFUSED: a K is already running; finish it with research_done first")
            pick = [r for r in ks if (r["id"] == kid and key(r["status"]) in {"queued", "blocked"})] if kid else \
                [r for r in ks if key(r["status"]) == "queued"][:1]
            if not pick:
                raise ResearchError("REFUSED: no queued K (or the given K is not queued/blocked)")
            r = pick[0]
            page = re.search(r"@(\S+)", r["evidence"]).group(1)
            self.db.execute("UPDATE rl_rows SET status = 'running', turn_updated = ? WHERE ledger = ? AND id = ?",
                            (lg["turn"], ledger, r["id"]))
            self.db.execute("UPDATE rl_ledgers SET running = ? WHERE id = ?", (r["id"], ledger))
            self._log(ledger, lg["turn"], f"~{r['id']}.status: {r['status']} → running")
            self._touch(ledger, lg["turn"], r["id"])
            head = f"RUN {r['id']}: {r['content']}  on [{r['dep']}]"
            if page in VIRTUAL_PAGES:
                return f"{head}\nPAGE {page}: {VIRTUAL_PAGES[page]}"
            from . import render
            return f"{head}\n----- CARD [{page}] -----\n" + render.card(self.hb.get_entry(page), self.hb.neighbors(page))
        return self._write(ledger, token, fn)

    def done(self, ledger: str, token: str | None, kid: str, exit: str) -> str:
        def fn(lg):
            r = self._row(ledger, kid)
            if key(r["status"]) != "running":
                raise ResearchError(f"REFUSED: {kid} is not running")
            pushed = [k["id"] for k in self._rows(ledger, "K")
                      if re.search(rf"from:{re.escape(kid)}/{re.escape(exit)}(\s|$)", k["evidence"])]
            if not pushed:
                raise ResearchError(f"REFUSED: exit {exit!r} of {kid} returned no object. Push its K objects with "
                                    f"research_push(frm={kid!r}, exit={exit!r}); a terminal exit pushes page USER.")
            st = f"done ({exit} → {' '.join(pushed)})"
            self.db.execute("UPDATE rl_rows SET status = ?, turn_updated = ? WHERE ledger = ? AND id = ?",
                            (st, lg["turn"], ledger, kid))
            self.db.execute("UPDATE rl_ledgers SET running = NULL WHERE id = ?", (ledger,))
            self._log(ledger, lg["turn"], f"~{kid}: running → done via {exit} → {' '.join(pushed)}")
            return f"{kid} done via {exit} → {' '.join(pushed)}"
        return self._write(ledger, token, fn)

    def drop(self, ledger: str, token: str | None, kid: str, why: str) -> str:
        def fn(lg):
            r = self._row(ledger, kid)
            if r["sec"] != "K" or key(r["status"]) not in {"queued", "blocked"}:
                raise ResearchError(f"REFUSED: {kid} is not a queued/blocked K")
            if not why.strip():
                raise ResearchError("REFUSED: drop needs a why")
            self.db.execute("UPDATE rl_rows SET status = 'dropped', evidence = ?, turn_updated = ? WHERE ledger = ? AND id = ?",
                            (f"{r['evidence']} · dropped: {why}", lg["turn"], ledger, kid))
            self.db.execute("DELETE FROM rl_pending WHERE ledger = ? AND hit = ?", (ledger, kid))
            self._log(ledger, lg["turn"], f"~{kid}: dropped ({why})")
            return f"{kid} dropped"
        return self._write(ledger, token, fn)

    # ── exploration ──────────────────────────────────────────────────────

    def _resolve_spec(self, ledger: str, spec: str) -> list[str]:
        rows = {r["id"]: r for r in self._rows(ledger)}
        members: list[str] = []
        for tok in spec.replace(",", " ").split():
            if tok == "main":
                members += [m for m in self.main_members(ledger) if m not in members]
            elif ">" in tok:
                a, b = tok.split(">", 1)
                if a not in members:
                    raise ResearchError(f"swap {tok}: {a} is not in the configuration so far")
                members[members.index(a)] = b
            elif tok[0] in "+":
                members.append(tok[1:])
            elif tok[0] in "-!¬":
                if tok[1:] not in members:
                    raise ResearchError(f"remove {tok}: {tok[1:]} is not in the configuration so far")
                members.remove(tok[1:])
            else:
                members.append(tok)
        groups: dict[str, str] = {}
        for m in members:
            r = rows.get(m)
            if r is None or r["sec"] not in ("A", "T"):
                raise ResearchError(f"configuration member {m} must be an existing A or T row")
            if key(r["status"]) in {"superseded", "refuted"}:
                raise ResearchError(f"configuration member {m} is {r['status']}; use its replacement")
            if r["grp"]:
                if r["grp"] in groups:
                    raise ResearchError(f"{m} and {groups[r['grp']]} are alternatives (group {r['grp']!r}); keep one")
                groups[r["grp"]] = m
        return sorted(dict.fromkeys(members), key=lambda i: (i[0], int(i[1:])))

    def config(self, ledger: str, token: str | None, name: str, spec: str, purpose: str = "") -> str:
        name = slugify(name).replace("-", "_")
        if name == "main":
            raise ResearchError("REFUSED: 'main' is the user's line: it is the set of A/T rows that are on. "
                                "The user switches it; exploration uses other names.")

        def fn(lg):
            members = self._resolve_spec(ledger, spec)
            old = self.db.execute("SELECT members FROM rl_configs WHERE ledger = ? AND name = ?", (ledger, name)).fetchone()
            if old and self._column("SELECT 1 FROM rl_verdicts WHERE ledger = ? AND config = ?", ledger, name):
                if old[0] != " ".join(members):
                    raise ResearchError(f"REFUSED: configuration {name!r} already has verdicts; define a new name instead")
            self.db.execute("INSERT OR REPLACE INTO rl_configs VALUES (?, ?, ?, ?, ?, ?)",
                            (ledger, name, " ".join(members), spec, purpose, lg["turn"]))
            self._log(ledger, lg["turn"], f"+config {name} = {{{' '.join(members)}}}")
            model = [m for m in members if self._row(ledger, m)["origin"].lower().startswith("model")]
            note = f"  (explores model premise(s) {' '.join(model)})" if model else ""
            return f"config {name} = {{{', '.join(members)}}}{note}"
        return self._write(ledger, token, fn)

    def verdict(self, ledger: str, token: str | None, claim: str, config: str, verdict: str, evidence: str) -> str:
        verdict = key(verdict)
        if verdict not in VERDICTS - {"stale"}:
            raise ResearchError(f"verdict must be one of {sorted(VERDICTS - {'stale'})}")

        def fn(lg):
            h = self._row(ledger, claim)
            if h["sec"] != "H":
                raise ResearchError(f"{claim} is not a claim (H)")
            cfgs = self._configs(ledger)
            if config not in cfgs:
                raise ResearchError(f"unknown configuration {config!r}; known: {', '.join(cfgs)}")
            ev = evidence.strip()
            if verdict == "false" and "cex:" not in ev:
                raise ResearchError("REFUSED: false needs the counterexample in evidence ('cex: …')")
            if verdict == "undecided" and not re.search(r"tried:|not found:", ev):
                raise ResearchError("REFUSED: undecided needs the attempt in evidence ('tried: …' or 'not found: <calls>')")
            if verdict in {"true", "false"} and not ev:
                raise ResearchError("REFUSED: a decided verdict needs evidence (computed / followed / sourced: … / measured)")
            old = self.db.execute("SELECT verdict FROM rl_verdicts WHERE ledger = ? AND claim = ? AND config = ?",
                                  (ledger, claim, config)).fetchone()
            self.db.execute("INSERT OR REPLACE INTO rl_verdicts VALUES (?, ?, ?, ?, ?, ?, 0)",
                            (ledger, claim, config, verdict, ev, lg["turn"]))
            if config == "main":
                self.db.execute("UPDATE rl_rows SET status = ?, turn_updated = ? WHERE ledger = ? AND id = ?",
                                (verdict, lg["turn"], ledger, claim))
            self._log(ledger, lg["turn"], f"verdict {claim}@{config}: {old[0] if old else '·'} → {verdict}")
            self._touch(ledger, lg["turn"], claim, f"{claim}@{config}")
            msg = [f"{claim}@{config}: {verdict}"]
            if old and old[0] in {"true", "false"} and old[0] != verdict:
                hits = self._direct_hits(ledger, claim)
                for hh in sorted(hits):
                    self.db.execute("INSERT OR IGNORE INTO rl_pending VALUES (?, ?, ?)", (ledger, claim, hh))
                if hits:
                    msg.append(f"PENDING {claim}: {' '.join(sorted(hits))} — the verdict flipped; dispose each")
            return "\n".join(msg)
        return self._write(ledger, token, fn)

    # ── tracing and checking ─────────────────────────────────────────────

    def closure(self, ledger: str, ids: list[str]) -> str:
        seen, frontier, hits = set(ids), list(ids), []
        while frontier:
            x = frontier.pop()
            for y in sorted(self._direct_hits(ledger, x)):
                hits.append((y, x))
                if y not in seen:
                    seen.add(y)
                    if "@" not in y:
                        frontier.append(y)
        if not hits:
            return f"closure of {' '.join(ids)}: nothing depends on it"
        return "\n".join([f"closure of {' '.join(ids)} — {len(hits)} hit(s); each needs VALID · RECHECK · INVALID · UNAFFECTED:"]
                         + [f"  {y:10} via {x}" for y, x in hits])

    def check(self, ledger: str) -> tuple[list[str], list[str]]:
        err: list[str] = []
        warn: list[str] = []
        lg = self._ledger(ledger)
        rows = self._rows(ledger)
        ids = {r["id"]: r for r in rows}
        for r in rows:
            rid, sec, own = r["id"], r["sec"], key(r["status"])
            origin = r["origin"].lower()
            ev = r["evidence"].lower()
            if own not in ALLOWED[sec]:
                err.append(f"{rid}: status {r['status']!r} not allowed in {sec}")
            if sec == "A" and own == "on" and origin.startswith("model"):
                err.append(f"{rid}: a model premise is on the main line; only the user adopts it "
                           "(then set origin to 'user(adopted, turn N)'); explore it in a named configuration instead")
            if key(r["evidence"]) == "sourced" and not re.search(r"chat:|file:|https?://", ev):
                err.append(f"{rid}: 'sourced' without a locator (chat:<uuid>, file:<path>, or a URL)")
            if re.search(r"\brecall", ev) and "[unverified]" not in ev:
                err.append(f"{rid}: recall is not evidence — retrieve it (RF) or mark [unverified]")
            if re.search(r"not found:\s*($|[·;])", ev):
                err.append(f"{rid}: 'not found:' must name the calls that were made")
            if own == "proposed" and origin.startswith("model") and sec != "K" and "closure:" not in ev:
                err.append(f"{rid}: model-origin proposed without 'closure: <what the user givens were checked against>'")
            if len(r["evidence"]) > 240 or r["evidence"].count(";") >= 3:
                warn.append(f"{rid}: evidence cell is accreting; replace it with the current state (history is in the log)")
            if own in FINISHED or own == "stale" or sec == "K":
                continue
            for rel, d in edges(r["dep"]):
                if d not in ids:
                    err.append(f"{rid}: cites missing {d}")
                    continue
                dr = ids[d]
                dk = key(dr["status"])
                if dr["origin"].lower().startswith("model") and not origin.startswith("model"):
                    err.append(f"{rid}: rests on model-origin {d}; a {r['origin']} row cannot (mark {rid} model, "
                               "or have the user adopt the premise)")
                if not origin.startswith("model") and dk in NOT_A_BASIS:
                    err.append(f"{rid}: rests on {d} with status {dr['status']!r} — mark {rid} stale or re-derive")
                if origin.startswith("model") and dk in {"superseded", "refuted", "stale"}:
                    err.append(f"{rid}: rests on {d} with status {dr['status']!r} — mark {rid} stale or re-derive")
                if key(dr["evidence"]) == "pointer":
                    err.append(f"{rid}: rests on {d}, which is only a pointer — retrieve the original (RF)")
                if d.startswith("Z"):
                    warn.append(f"{rid}: uses isolated unknown {d} — confirm it appears only as a symbol or gauge")
                if rel == "int" and "map" not in ev:
                    warn.append(f"{rid}: 'int' edge to {d} without an explicit map in evidence")
                if unverified(dr["evidence"]) and key(r["evidence"]) in {"computed", "followed", "sourced"}:
                    warn.append(f"{rid}: evidence {r['evidence']!r} rests on [unverified] {d}; the conclusion is at most [unverified]")
            if sec == "H" and own == "open" and lg["turn"] - r["turn_created"] >= 3 and not re.search(r"tried:|not found:", ev):
                warn.append(f"{rid}: open for {lg['turn'] - r['turn_created']} turns with no recorded attempt")
        cfgs = self._configs(ledger)
        verdicts = [dict(v) for v in self.db.execute("SELECT * FROM rl_verdicts WHERE ledger = ?", (ledger,))]
        for v in verdicts:
            h = ids.get(v["claim"])
            if h is None or v["config"] not in cfgs:
                err.append(f"verdict {v['claim']}@{v['config']}: unknown claim or configuration")
                continue
            members = set(cfgs[v["config"]]["members"])
            if v["verdict"] == "true":
                es = edges(h["dep"])
                if es and all(rel == "sup" for rel, _ in es):
                    err.append(f"{h['id']}@{v['config']}: true on 'sup' edges only — supports is evidence, not proof")
                for rel, d in es:
                    if d.startswith("T") and d not in members:
                        err.append(f"{h['id']}@{v['config']}: true, but rests on external result {d}, which is not "
                                   f"in configuration {v['config']!r}")
                for rel, d in es:
                    if rel == "con" and d in ids:
                        other = next((w for w in verdicts if w["claim"] == d and w["config"] == v["config"]), None)
                        if other and other["verdict"] == "true":
                            err.append(f"{h['id']} contradicts {d}, both true under {v['config']!r}")
            if v["config"] == "main" and key(h["status"]) not in (v["verdict"], "superseded", "refuted", "history", "stale"):
                err.append(f"{h['id']}: status {h['status']!r} disagrees with its main verdict {v['verdict']!r}")
        for c in cfgs.values():
            for m in c["members"]:
                if m not in ids:
                    err.append(f"configuration {c['name']}: member {m} missing")
        return err, warn

    # ── documents ────────────────────────────────────────────────────────

    @staticmethod
    def parse_sections(text: str) -> dict[str, dict[str, Any]]:
        """A section starts at a heading followed by '<!-- sec:ID basis: … -->' and runs to the
        next such heading. Text before the first one is the preamble '_pre'."""
        lines = text.split("\n")
        starts = []
        for i, line in enumerate(lines):
            m = MARK_RE.match(line)
            if m:
                head = i - 1 if i > 0 and HEAD_RE.match(lines[i - 1]) else i
                starts.append((head, i, m.group(1), m.group(2)))
        out: dict[str, dict[str, Any]] = {}
        bounds = [s[0] for s in starts] + [len(lines)]
        pre = "\n".join(lines[: bounds[0]]).strip()
        if pre:
            out["_pre"] = {"text": pre, "basis": [], "heading": ""}
        for n, (head, mark, sid, rest) in enumerate(starts):
            body = "\n".join(lines[head: bounds[n + 1]]).strip()
            if sid in out:
                raise ResearchError(f"section id {sid!r} appears twice")
            out[sid] = {"text": body, "basis": ID_RE.findall(rest), "heading": lines[head].strip() if head != mark else ""}
        return out

    @staticmethod
    def visible(text: str) -> str:
        """Prose a reader sees outside comments, code and mathematics (where brackets are commutators)."""
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        text = re.sub(r"\$\$.*?\$\$|\\\[.*?\\\]", "", text, flags=re.S)
        text = re.sub(r"(?<!\\)\$[^$\n]+?\$|\\\(.*?\\\)", "", text)
        return text

    def lint(self, text: str) -> list[str]:
        vis = self.visible(text)
        out = []
        for n, line in enumerate(vis.split("\n"), 1):
            for rx, what in LEAKS:
                m = rx.search(line)
                if m:
                    out.append(f"line {n}: {what}: {m.group(0)!r}")
        for n, line in enumerate(text.split("\n"), 1):
            if HEAD_RE.match(line) and n < len(text.split("\n")) and not MARK_RE.match(text.split("\n")[n]) \
                    and line.startswith("## "):
                out.append(f"line {n}: level-2 heading without a section marker on the next line: {line.strip()!r}")
        return out

    def _doc(self, ledger: str, did: str) -> dict[str, Any]:
        d = self.db.execute("SELECT * FROM rl_docs WHERE ledger = ? AND id = ?", (ledger, did)).fetchone()
        if d is None:
            raise ResearchError(f"no document {did!r}; register it first")
        return dict(d)

    def doc_register(self, ledger: str, token: str | None, label: str, role: str, text: str, owner: str = "") -> str:
        role = role.lower()
        if role not in {"source", "deliverable", "working"}:
            raise ResearchError("role must be source (the user's original), deliverable (written for the user) "
                                "or working (the model's own)")
        owner = owner or {"source": "user", "deliverable": "user", "working": "model"}[role]

        def fn(lg):
            n = 1 + len(self._column("SELECT id FROM rl_docs WHERE ledger = ?", ledger))
            did = f"D{n}"
            sha = hashlib.sha256(text.encode()).hexdigest()
            secs = {}
            if role == "deliverable" and text.strip():
                secs = {k: {"hash": _h(v["text"]), "basis": v["basis"]} for k, v in self.parse_sections(text).items()}
            clock = self._ledger(ledger)["clock"]
            self.db.execute("INSERT INTO rl_docs VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
                            (ledger, did, label, role, owner, sha, json.dumps(secs), lg["turn"] if secs else 0, lg["turn"],
                             clock if secs else 0))
            self._log(ledger, lg["turn"], f"+{did} {role} {label}")
            rule = {"source": "read-only: never edit it; work on a copy registered as working",
                    "deliverable": "readable prose; ids only in section basis comments; plan before every change",
                    "working": "the model's scratch; never handed to the user as the deliverable"}[role]
            return f"{did} registered as {role} ({owner}): {label} — {rule}"
        return self._write(ledger, token, fn)

    def _changed_since(self, ledger: str, clock: int) -> set[str]:
        """Rows and claims changed by any device write after the given write clock."""
        ch = set(self._column("SELECT id FROM rl_rows WHERE ledger = ? AND clock_updated > ? AND sec != 'K'", ledger, clock))
        ch |= set(self._column("SELECT claim FROM rl_verdicts WHERE ledger = ? AND clock > ?", ledger, clock))
        return ch

    def doc_check(self, ledger: str, did: str, text: str) -> str:
        d = self._doc(ledger, did)
        if d["role"] == "source":
            ok = hashlib.sha256(text.encode()).hexdigest() == d["sha"]
            return (f"{did} source unchanged" if ok else
                    f"ERROR {did}: the user's source differs from the registered original — it was edited; "
                    "restore it and put changes in a working copy")
        if d["role"] == "working":
            return f"{did} working document: no reader rules apply"
        problems = self.lint(text)
        rows = {r["id"]: r for r in self._rows(ledger)}
        for sid, s in self.parse_sections(text).items():
            for b in s["basis"]:
                if b not in rows:
                    problems.append(f"section {sid}: basis cites missing {b}")
                elif key(rows[b]["status"]) in NOT_CITABLE:
                    problems.append(f"section {sid}: basis cites {b}, which is {rows[b]['status']}")
        return "\n".join([f"{did}: {len(problems)} problem(s)"] + [f"  {p}" for p in problems])

    def doc_plan(self, ledger: str, token: str | None, did: str, text: str,
                 items: list[dict[str, Any]] | None = None) -> str:
        """Without items: a read-only draft of the change list. With items: commit it (needs the token)."""
        d = self._doc(ledger, did)
        if d["role"] != "deliverable":
            raise ResearchError(f"{did} is {d['role']}; plans apply to deliverables")
        secs = self.parse_sections(text)
        stored = json.loads(d["sections"])
        rows = {r["id"]: r for r in self._rows(ledger)}
        changed = self._changed_since(ledger, d["sync_clock"]) if d["sync_clock"] else set(rows)
        reach = set(changed)
        for c in list(changed):
            for line in self.closure(ledger, [c]).splitlines()[1:]:
                reach.add(line.split()[0].split("@")[0])
        affected, stale_cite = [], []
        for sid, s in secs.items():
            if sid == "_pre":
                continue
            if set(s["basis"]) & reach:
                affected.append(sid)
            if any(b in rows and key(rows[b]["status"]) in NOT_CITABLE for b in s["basis"]):
                stale_cite.append(sid)
        cited = {b for s in secs.values() for b in s["basis"]}
        unplaced = sorted(i for i in changed if i in rows and i not in cited and rows[i]["sec"] in "EHTACRSZXP"
                          and key(rows[i]["status"]) not in NOT_CITABLE | FINISHED)
        merge = []
        ss = [k for k in secs if k != "_pre" and secs[k]["basis"]]
        for i, a in enumerate(ss):
            for b in ss[i + 1:]:
                A, B = set(secs[a]["basis"]), set(secs[b]["basis"])
                if A and B and len(A & B) / len(A | B) >= 0.5:
                    merge.append(f"{a}+{b}")
        drift = [k for k in secs if k in stored and _h(secs[k]["text"]) != stored[k]["hash"]]
        if items is None:
            draft = ([{"sec": s, "op": "rewrite", "why": "basis changed: " + " ".join(sorted(set(secs[s]["basis"]) & reach))}
                      for s in affected]
                     + [{"sec": s, "op": "rewrite", "why": "cites a replaced or stale row"} for s in stale_cite if s not in affected]
                     + ([{"sec": "new:<name>", "op": "add", "rows": unplaced,
                          "why": "not yet in the document; one add item per new section — split, or move rows to omit"}]
                        if unplaced else []))
            out = [f"PLAN DRAFT for {did} {d['label']} (changes since turn {d['sync_turn']}: {' '.join(sorted(changed)) or 'none'})",
                   f"  affected sections: {' '.join(affected) or 'none'}",
                   f"  sections citing replaced/stale rows: {' '.join(stale_cite) or 'none'}",
                   f"  rows not in the document: {' '.join(unplaced) or 'none'}",
                   f"  merge candidates (basis overlap ≥ 0.5): {' '.join(merge) or 'none'}"]
            if drift:
                out.append(f"  WARNING sections edited since the last sync without a plan: {' '.join(drift)}")
            out += ["", "Decide one op per item — rewrite | merge (into) | add (rows) | retire | keep (why) | omit (rows, why) —",
                    "then commit with research_doc(action='plan', items=[…], token=…). Draft:",
                    json.dumps(draft, ensure_ascii=False, indent=1)]
            return "\n".join(out)

        def fn(lg):
            covered_secs, covered_rows, problems = set(), set(), []
            for it in items:
                op = it.get("op")
                if op not in {"rewrite", "merge", "add", "retire", "keep", "omit"}:
                    problems.append(f"bad op {op!r}")
                    continue
                for s in str(it.get("sec", "")).replace("+", ",").split(","):
                    s = s.strip()
                    if s and not s.startswith("new:"):
                        if s not in secs:
                            problems.append(f"{op}: no section {s!r}")
                        covered_secs.add(s)
                if op == "merge":
                    if it.get("into") not in secs:
                        problems.append(f"merge needs into=<existing section>, got {it.get('into')!r}")
                    else:
                        covered_secs.add(it["into"])
                if op in {"keep", "omit"} and not it.get("why"):
                    problems.append(f"{op} on {it.get('sec') or it.get('rows')} needs a why")
                covered_rows |= set(it.get("rows") or [])
                if op == "keep" and set(str(it.get("sec", "")).split(",")) & set(stale_cite):
                    problems.append(f"keep is not allowed for {it['sec']}: it cites a replaced or stale row")
            for s in affected + stale_cite:
                if s not in covered_secs:
                    problems.append(f"section {s} is affected but has no plan item")
            for u in unplaced:
                if u not in covered_rows:
                    problems.append(f"row {u} changed and is not in the document: plan add or omit (with why)")
            if problems:
                raise ResearchError("REFUSED: plan incomplete:\n  " + "\n  ".join(problems))
            self.db.execute("UPDATE rl_docs SET plan = ?, plan_turn = ? WHERE ledger = ? AND id = ?",
                            (json.dumps(items, ensure_ascii=False), lg["turn"], ledger, did))
            self._log(ledger, lg["turn"], f"plan {did}: {len(items)} item(s)")
            return (f"plan committed for {did}: {len(items)} item(s). Rewrite each planned section whole from the current "
                    "ledger (never append corrections), then research_doc(action='sync').")
        return self._write(ledger, token, fn)

    def doc_sync(self, ledger: str, token: str | None, did: str, text: str) -> str:
        def fn(lg):
            d = self._doc(ledger, did)
            if d["role"] != "deliverable":
                raise ResearchError(f"{did} is {d['role']}; only deliverables are synced")
            secs = self.parse_sections(text)
            stored = json.loads(d["sections"])
            plan = json.loads(d["plan"]) if d["plan"] else None
            problems = []
            if plan is None:
                problems.append("no committed plan: run research_doc(action='plan') first; changes are listed before they are made")
            plan = plan or []
            planned = {}
            for it in plan:
                for s in str(it.get("sec", "")).replace("+", ",").split(","):
                    if s.strip():
                        planned[s.strip()] = it
                if it.get("op") == "merge" and it.get("into"):
                    planned[it["into"]] = it  # the target is rewritten as the merged passage
            new_ids = [k for k in secs if k not in stored and k != "_pre"]
            adds = [it for it in plan if it["op"] == "add" and str(it.get("sec", "")).startswith("new:")]
            if len(new_ids) != len(adds):
                problems.append(f"{len(adds)} new section(s) planned, {len(new_ids)} found ({' '.join(new_ids) or 'none'})")
            for sid, info in stored.items():
                it = planned.get(sid)
                now = secs.get(sid)
                op = it["op"] if it else None
                if op in (None, "keep"):
                    if now is None:
                        problems.append(f"section {sid} disappeared without a plan item")
                    elif _h(now["text"]) != info["hash"] and sid != "_pre":
                        problems.append(f"section {sid} changed without a plan item (unplanned edit)")
                elif op == "rewrite":
                    if now is None:
                        problems.append(f"section {sid} planned as rewrite but missing")
                    elif _h(now["text"]) == info["hash"]:
                        problems.append(f"section {sid} planned as rewrite but unchanged")
                elif op == "retire" or (op == "merge" and sid != it.get("into")):
                    if now is not None:
                        problems.append(f"section {sid} planned as {op} but still present")
                elif op == "merge" and now is None:
                    problems.append(f"merge target {sid} missing")
            for it in plan:
                if it["op"] == "merge" and it.get("into") in secs and it["into"] in stored \
                        and _h(secs[it["into"]]["text"]) == stored[it["into"]]["hash"]:
                    problems.append(f"merge target {it['into']} unchanged: merged sections are rewritten as one")
                for r in it.get("rows") or []:
                    if it["op"] == "add" and not any(r in s["basis"] for s in secs.values()):
                        problems.append(f"row {r} planned as add but no section cites it in its basis")
            report = self.doc_check(ledger, did, text)
            if not report.startswith(f"{did}: 0 problem"):
                problems += [line.strip() for line in report.splitlines()[1:]]
            if problems:
                raise ResearchError("REFUSED: document does not match its plan:\n  " + "\n  ".join(problems))
            new = {k: {"hash": _h(v["text"]), "basis": v["basis"]} for k, v in secs.items()}
            self.db.execute("UPDATE rl_docs SET sections = ?, sync_turn = ?, sync_clock = ?, plan = NULL, plan_turn = NULL, "
                            "sha = ? WHERE ledger = ? AND id = ?",
                            (json.dumps(new), lg["turn"], self._ledger(ledger)["clock"],
                             hashlib.sha256(text.encode()).hexdigest(), ledger, did))
            self._log(ledger, lg["turn"], f"sync {did}: {len(new)} section(s)")
            return f"{did} synced at turn {lg['turn']}: {len([k for k in new if k != '_pre'])} section(s), reader lint clean"
        return self._write(ledger, token, fn)

    # ── export / import ──────────────────────────────────────────────────

    CHILD_TABLES = ("rl_rows", "rl_configs", "rl_verdicts", "rl_docs", "rl_pending", "rl_turnmarks", "rl_log")

    def export(self, ledger: str, include_log: bool = True) -> dict[str, Any]:
        lg = self._ledger(ledger)
        tables = {}
        for t in self.CHILD_TABLES:
            if t == "rl_log" and not include_log:
                continue
            tables[t] = [dict(r) for r in self.db.execute(f"SELECT * FROM {t} WHERE ledger = ?", (ledger,))]
        return {"ledger": dict(lg), "tables": tables}

    def import_(self, data: dict[str, Any], as_ledger: str | None = None, dry_run: bool = False) -> str:
        """Load an export. `as_ledger` stores it under another id (a sandbox copy to inspect first);
        `dry_run` loads it inside a transaction, reports, and rolls back."""
        try:
            lg = dict(data["ledger"])
            tables = data["tables"]
        except (KeyError, TypeError) as e:
            raise ResearchError("import needs the JSON that export returned: {ledger: {...}, tables: {...}}") from e
        src = lg["id"]
        lid = slugify(as_ledger) if as_ledger else src
        if self.db.execute("SELECT 1 FROM rl_ledgers WHERE id = ?", (lid,)).fetchone():
            raise ResearchError(f"ledger {lid!r} exists here; import refuses to overwrite it "
                                f"(import with as_ledger=<new name>, or delete/rename the existing one)")
        unknown = set(tables) - set(self.CHILD_TABLES)
        if unknown:
            raise ResearchError(f"unknown tables in the import: {sorted(unknown)}")
        lg["id"] = lid
        counts: dict[str, int] = {}

        class _Rollback(Exception):
            pass

        try:
            with self.db:
                self.db.execute(f"INSERT INTO rl_ledgers ({', '.join(lg)}) VALUES ({', '.join('?' * len(lg))})",
                                list(lg.values()))
                for t, rows in tables.items():
                    for r in rows:
                        r = {k: v for k, v in r.items() if not (t == "rl_log" and k == "seq")} | {"ledger": lid}
                        self.db.execute(f"INSERT INTO {t} ({', '.join(r)}) VALUES ({', '.join('?' * len(r))})",
                                        list(r.values()))
                    counts[t] = len(rows)
                errors, warnings = self.check(lid)
                self._log(lid, lg["turn"], f"imported from {src!r}" if lid != src else "imported")
                self._seal(lid)
                if dry_run:
                    raise _Rollback
        except _Rollback:
            pass
        except sqlite3.Error as e:
            raise ResearchError(f"import failed, nothing stored: {e}") from e
        summary = ", ".join(f"{t[3:]} {n}" for t, n in counts.items())
        head = (f"DRY RUN (nothing stored): ledger {lid!r}" if dry_run else f"imported ledger {lid!r}") + \
               f" at turn {lg['turn']} (last closed {lg['last_closed']}) · {summary}"
        return "\n".join([head, f"check: {len(errors)} errors, {len(warnings)} warnings"]
                         + [f"  ERROR {e}" for e in errors[:20]] + [f"  WARN  {w}" for w in warnings[:10]]
                         + ([f"  … {len(errors) + len(warnings) - 30} more"] if len(errors) + len(warnings) > 30 else []))

    def copy(self, ledger: str, to: str) -> str:
        """A separate ledger with the same content: a sandbox to try changes or an import on."""
        out = self.import_(self.export(ledger), as_ledger=to)
        return out.replace("imported ledger", "copied to ledger", 1)

    def rename(self, ledger: str, to: str) -> str:
        lg = self._ledger(ledger)
        new = slugify(to)
        if self.db.execute("SELECT 1 FROM rl_ledgers WHERE id = ?", (new,)).fetchone():
            raise ResearchError(f"ledger {new!r} exists; pick another name")
        with self.db:
            cols = [c for c in lg if c != "id"]
            self.db.execute(f"INSERT INTO rl_ledgers (id, {', '.join(cols)}) SELECT ?, {', '.join(cols)} "
                            "FROM rl_ledgers WHERE id = ?", (new, ledger))
            for t in self.CHILD_TABLES:
                self.db.execute(f"UPDATE {t} SET ledger = ? WHERE ledger = ?", (new, ledger))
            self.db.execute("DELETE FROM rl_ledgers WHERE id = ?", (ledger,))
            self._log(new, lg["turn"], f"renamed from {ledger!r}")
            self._seal(new)
        return (f"renamed ledger {ledger!r} → {new!r}"
                + (f"; turn {lg['turn']} is open: re-read with research_begin(ledger={new!r}, turn={lg['turn']})"
                   if lg["open"] else ""))

    def delete(self, ledger: str, confirm: str) -> str:
        lg = self._ledger(ledger)
        if confirm != ledger:
            raise ResearchError(f"REFUSED: deleting is permanent; pass confirm={ledger!r} (the ledger id) to proceed. "
                                "To keep a copy, export it first, or copy it to another name.")
        n = self.db.execute("SELECT count(*) FROM rl_rows WHERE ledger = ?", (ledger,)).fetchone()[0]
        with self.db:
            for t in self.CHILD_TABLES:
                self.db.execute(f"DELETE FROM {t} WHERE ledger = ?", (ledger,))
            self.db.execute("DELETE FROM rl_ledgers WHERE id = ?", (ledger,))
        return f"deleted ledger {ledger!r} ({n} rows, last closed turn {lg['last_closed']})"


def _h(text: str) -> str:
    return hashlib.sha1(text.strip().encode()).hexdigest()[:12]


# ── research cards ───────────────────────────────────────────────────────
#
# The pages in research_pages/ are the single source of the research cards. Each page is
# Markdown with a fixed shape (header lines, ENTRY, ◆, numbered steps, ### notes, **EXITS**),
# parsed here into handbook entries so the same procedure is read as a card through MCP and
# edited as a page by a person.

FOOTER_WHEN = "the chosen exit's objects are pushed"
FOOTER_TEXT = ("research_done(K, exit). CONTINUE: N1 step 4 (next K) · CLOSE: N1 steps 5–8, "
               "the reply ends with NEXT · NEXT TURN: N1 step 1")
PAGE_HEAD = re.compile(r"^# PAGE (\S+) — (.+)$")
EXIT_RE = re.compile(r"^- \*\*(\w+)\*\*: (.+?) → (.+)$")
STEP_RE = re.compile(r"^(\d+)\.\s+(.*)$")
PUSH_TARGET = re.compile(r"@([A-Za-z][\w-]*)")


def parse_page(text: str) -> dict[str, Any]:
    lines = text.rstrip().split("\n")
    m = PAGE_HEAD.match(lines[0])
    if not m:
        raise ResearchError(f"page must start with '# PAGE <ID> — <title>': {lines[0]!r}")
    pid, title = m.group(1), m.group(2).strip()
    meta, i = {}, 1
    while i < len(lines) and re.match(r"^(KIND|TAGS|TRIGGERS|OBJECTIVE):", lines[i]):
        k, v = lines[i].split(":", 1)
        meta[k] = v.strip()
        i += 1
    for k in ("KIND", "TAGS", "TRIGGERS", "OBJECTIVE"):
        if k not in meta:
            raise ResearchError(f"page {pid}: missing {k}:")
    condition: list[str] = []
    body: list[str] = []
    items: list[dict[str, Any]] = []
    pushes: set[str] = set()
    mode, cur, block, in_entry = "pre", None, [], False
    seen_step = False

    def flush_block():
        nonlocal block
        text_ = "\n".join(block).strip("\n")
        if text_.strip():
            if seen_step or mode == "exits":
                items.append({"phase": "action", "kind": "note", "text": text_})
            else:
                body.append(text_)
        block = []

    def flush_cur():
        nonlocal cur
        if cur:
            cur["text"] = cur["text"].rstrip()
            items.append(cur)
        cur = None

    for line in lines[i:]:
        if line.startswith("ENTRY"):
            condition.append(line.split("—", 1)[1].strip() if "—" in line else line.strip())
            in_entry = True
            continue
        if in_entry:
            if line.strip() and not line.startswith(("◆", "#", "**")) and not STEP_RE.match(line):
                condition.append(line.strip())
                continue
            in_entry = False
        if line.startswith("◆"):
            flush_cur(); flush_block()
            # unnumbered, so that the card's step numbers equal the page's "step N" references
            phase_kind = ("memory", "caution") if not seen_step and not items else ("action", "caution")
            cur = {"phase": phase_kind[0], "kind": phase_kind[1], "text": line[1:].strip()}
            continue
        if line.startswith("**EXITS**"):
            flush_cur(); flush_block()
            mode = "exits"
            items.append({"phase": "action", "kind": "note",
                          "text": "EXITS — take the one whose condition holds; it returns the objects it names."})
            continue
        if mode == "exits":
            em = EXIT_RE.match(line)
            if em:
                flush_cur()
                label, cond, push = em.groups()
                targets = {t for t in PUSH_TARGET.findall(push) if t.upper() not in ("USER",) and not t.startswith("<")}
                pushes |= targets
                items.append({"phase": "action", "kind": "step", "when": cond.strip(),
                              "text": f"({label}) {push.strip()}", "ends": True})
                continue
            if line.strip():
                block.append(line)
            else:
                flush_block()
            continue
        sm = STEP_RE.match(line)
        if sm:
            flush_cur(); flush_block()
            seen_step = True
            cur = {"phase": "action", "kind": "step", "text": sm.group(2)}
            continue
        if line.startswith("#"):
            flush_cur(); flush_block()
            items.append({"phase": "action", "kind": "note", "text": line.lstrip("#").strip()})
            seen_step = True
            continue
        if cur is not None and (line.startswith(" ") or not line.strip()):
            cur["text"] += "\n" + (line[3:] if line.startswith("   ") else line.strip())
            continue
        if cur is not None and cur["kind"] in ("step", "caution") and line.strip() and not line.startswith(("|", "-")):
            # a ◆ memory line wrapped onto the next line
            if cur["phase"] == "memory" or cur["kind"] == "caution":
                cur["text"] += " " + line.strip()
                continue
        flush_cur()
        if line.strip():
            block.append(line)
        else:
            flush_block()
    flush_cur(); flush_block()
    kind = meta["KIND"]
    if kind == "checklist":
        items.append({"phase": "deferred", "kind": "step", "when": FOOTER_WHEN, "text": FOOTER_TEXT})
    if kind == "reference" and not condition:
        first = body.pop(0) if body else "Consulted from a card step."
        condition = [first]
    entry = {
        "id": page_card_id(pid),
        "title": f"Research {pid} — {title}",
        "kind": kind,
        "condition": " ".join(condition),
        "objective": meta["OBJECTIVE"],
        "body": "\n\n".join(body),
        "triggers": [t.strip() for t in meta["TRIGGERS"].split(";") if t.strip()] + [f"research {pid}"],
        "tags": [t.strip() for t in meta["TAGS"].split(",") if t.strip()],
        "items": [{k: v for k, v in it.items() if v not in (None, "")} for it in items],
    }
    rels = [{"src": entry["id"], "type": "pushes_to", "dst": page_card_id(t), "note": "an exit returns objects for it"}
            for t in sorted(pushes) if page_card_id(t) != entry["id"]]  # a self-push stays in the exit text
    return {"entry": entry, "relations": rels}


def load_pages() -> tuple[str, dict[str, Any]]:
    from importlib import resources

    folder = resources.files("refhandbook").joinpath("research_pages")
    texts = {f.name: f.read_text() for f in sorted(folder.iterdir(), key=lambda f: f.name) if f.name.endswith(".md")}
    digest = hashlib.sha1("\0".join(f"{k}\n{v}" for k, v in texts.items()).encode()).hexdigest()
    entries, relations = [], []
    for name, text in texts.items():
        parsed = parse_page(text)
        entries.append(parsed["entry"])
        relations += parsed["relations"]
    ids = {e["id"] for e in entries}
    for r in relations:
        if r["dst"] not in ids:
            raise ResearchError(f"{r['src']} pushes to unknown card {r['dst']}")
    return digest, {"entries": entries, "relations": relations,
                    "relation_types": [{"name": "pushes_to", "inverse": "pushed_from",
                                        "description": "An exit of the source card returns plan objects for the target."}]}


def ensure_cards(hb: Handbook) -> str:
    """Load the research cards when the pages changed. Cards with the rs- prefix are managed
    here: edited copies are replaced, and rs- cards no longer in the pages are removed."""
    digest, data = load_pages()
    hb.db.executescript(SCHEMA)
    row = hb.db.execute("SELECT value FROM rl_meta WHERE key = 'cards'").fetchone()
    if row and row[0] == digest and hb.exists("rs-n1"):
        return "research cards up to date"
    for rt in data["relation_types"]:
        if not hb.db.execute("SELECT 1 FROM relation_types WHERE name = ?", (rt["name"],)).fetchone():
            hb.define_relation_type(rt["name"], rt["inverse"], rt["description"])
    bundled = {e["id"] for e in data["entries"]}
    for e in data["entries"]:
        hb.save_entry(**{k: e[k] for k in ("id", "title", "kind", "condition", "objective", "body",
                                            "triggers", "tags", "items")})
    for stale in hb._column("SELECT id FROM entries WHERE id LIKE 'rs-%'"):
        if stale not in bundled:
            hb.delete_entry(stale)
    with hb.db:
        hb.db.execute("DELETE FROM relations WHERE src LIKE 'rs-%' AND dst LIKE 'rs-%'")
    for r in data["relations"]:
        hb.relate(r["src"], r["type"], r["dst"], r["note"])
    with hb.db:
        hb.db.execute("INSERT OR REPLACE INTO rl_meta VALUES ('cards', ?)", (digest,))
    return f"loaded {len(bundled)} research cards"


def abnormal_index() -> str:
    """The abnormal rows of the research skill's index, generated from the X pages so the skill's
    memory items are the cards' memory items (one source)."""
    _, data = load_pages()
    rows = ["| signal | ◆ memory item | card |", "|---|---|---|"]
    for e in sorted((e for e in data["entries"] if re.fullmatch(r"rs-x\d", e["id"])), key=lambda e: e["id"]):
        signal = re.sub(r";?\s+-\s+", "; ", e["condition"].split("signal:", 1)[-1]).replace(":;", ":").strip()
        memory = next(i["text"] for i in e["items"] if i["phase"] == "memory")
        rows.append(f"| {signal} | **{e['id'][3:].upper()}** — {memory} | `{e['id']}` |")
    return "\n".join(rows)


def sync_skill_index(skill_md: str) -> str:
    """Return skill_md with its generated abnormal index replaced by the pages' current one."""
    begin, end = "<!-- BEGIN GENERATED: refhandbook research-index -->\n", "<!-- END GENERATED -->"
    if begin not in skill_md or end not in skill_md:
        raise ResearchError("the skill has no generated index markers")
    head, rest = skill_md.split(begin, 1)
    return head + begin + abnormal_index() + "\n" + end + rest.split(end, 1)[1]
