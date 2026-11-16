"""MCP surface of the handbook."""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import agents_api, cap_api, entry_api, render, research_api
from .store import Handbook, HandbookError

# What a conversation is given at its start. It says where the procedure is and what carries it from
# one message to the next; the procedure itself is the cards, and they win where the two differ.
_INSTRUCTIONS = """\
A quick reference handbook: short cards that say what to do when a known situation comes up.
When something goes wrong or a recurring task starts, call `lookup` with the symptom (an error
message, an alert, a few words, or what just happened in the conversation). Check a candidate's
CONDITION really matches, then `open_entry` and follow it in order: memory items first, then the
numbered steps, taking GO TO links when a step's IF holds. Stop at END. Keep deferred items in mind
until their moment arrives.
Cards are linked: RELATED lists what to open next (escalates_to, requires, see_also, ...), and a
card's ENTRY line names the ledger its work is entered through.
When you solve a problem no card covers, record it with `save_entry` and link it with `relate`. A
card is a procedure, a set or an index, never the record of a conversation: what the user said or
corrected is a ledger row, and what a procedure missed is a change to that card.
Work that has a ledger (`research_ledgers` lists them: research questions and projects) runs as a
session loop over the research cards (rs-*). Program counter: two places carry the loop from one
message to the next, and nothing else does: the RECEIPT line that ends your previous reply, and the
plan objects (K) awaiting the user in the ledger. If either exists, your first action is
`research_begin` (card rs-n1), whatever the message says: one-word, meta, process and complaint
messages included. Once per conversation, before it, `open_entry("rs-start")`. The first line of
`research_begin` is the SESSION token every later call names; the session works the plan objects
with `research_next` / `research_push` / `research_done` and closes with `research_end` before the
reply, whose last line is the RECEIPT. A reply without a RECEIPT is a skipped cycle and says so.
A tool result that ends with a `LOOP` line shows the loop as the store has it: the open sessions,
and how many changing calls were made since a chat session was last used. Calls made with no
session in use are missed messages: card rs-x7.
Abnormal signals come before any other card (its memory item first, then the card):
{abnormal}
Sessions run side by side (another conversation, an agent with role="agent"); a CONFLICT names
objects to re-read, nothing else is shared.
Computation runs in the user's sandbox with `cap` (scripts, policies, layers, egress, rules, cards:
versioned records you keep current), `run`, `job` and `files`: open_entry("rs-ref-sandbox") says how,
including how packages and the network are reached. The cards are current.
A task too big for one conversation can go to a team of agents on the user's own API keys:
agent_run(action="request", goal=…) asks for it; the user approves it on the approval page.
A tool result that begins DEPRECATED names its replacement: switch now. Never ask the user to
approve a run."""
INSTRUCTIONS = _INSTRUCTIONS.format(abnormal=research_api.rs.abnormal_index())


READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
DELETE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)
LEDGER_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

# mcp 2 runs sync tools on worker threads. A store is one SQLite connection, and a ledger write
# checks its session's claims, then writes: so tool calls run one at a time.
_CALLS = threading.RLock()


def _serialized(fn: Callable[..., Any]) -> Callable[..., Any]:
    """One call at a time, and refusals keep their text: mcp 2 replaces the message of any
    exception other than ToolError with "Error executing tool <name>", and the research loop
    is driven by what a REFUSED says."""

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        with _CALLS:
            try:
                return fn(*args, **kwargs)
            except HandbookError as e:
                raise ToolError(str(e)) from e

    return run

log = logging.getLogger("refhandbook.server")

# The calls of a mixed tool that change something (its other calls only read, and what they return is
# passed on as it is). A tool that is not read-only and not listed here changes something on every call.
CHANGES: dict[str, set[str]] = {
    "cap": {"add", "update", "deprecate", "remove", "restore", "rename"},
    "files": {"write", "remove"}, "job": {"cancel"}, "agent_run": {"request", "cancel"},
    "sandbox_script": {"add", "update", "retire", "test"}, "sandbox_files": {"write", "remove"},
    "sandbox_job": {"cancel"}, "sandbox_policy": set(),
}


def _loop_line() -> str:
    """render.loop_state for this store; never the reason a tool fails."""
    from .kernel import runtime, sessions

    try:
        hb = handbook()
        g = runtime.attach(hb).g
        last = sessions.last_chat_use(g)
        # the changing calls since a chat session was last used: counted on the store, started again
        # whenever a research call has moved that moment
        seen, calls = getattr(hb, "_loop_calls", (None, 0))
        hb._loop_calls = (last, calls + 1 if seen == last else 1)
        return render.loop_state(sessions.all_open(g), time.time(), hb._loop_calls[1], last)
    except Exception:  # noqa: BLE001 — the line is a display; the tool's own result stands without it
        log.exception("could not read the open sessions")
        return ""


def _outside_the_loop(fn: Callable[..., Any]) -> Callable[..., Any]:
    """A tool that changes something outside a ledger (a card, a relation, a capability, a file, a job)
    ends its result with the loop's state: the device shows whether a session is open at the place the
    work happens. The research tools are the loop itself and carry their session; reads show nothing."""
    actions = CHANGES.get(fn.__name__)

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> Any:
        out = fn(*args, **kwargs)
        if isinstance(out, str) and (actions is None or kwargs.get("action") in actions):
            out = f"{out}\n\n{_loop_line()}".rstrip()
        return out

    return run


TOOLS: list[tuple[Callable[..., Any], ToolAnnotations]] = []


def tool(annotations: ToolAnnotations) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Record a tool; make() registers every recorded tool on a server."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        TOOLS.append((fn, annotations))
        return fn

    return deco


def make(**settings: Any) -> MCPServer:
    """An MCP server with every tool registered. remote.build passes the OAuth settings; tests use it
    bare to call the tools as a client would."""
    from . import version

    server = MCPServer("refhandbook", instructions=INSTRUCTIONS, version=version(), **settings)
    for fn, annotations in TOOLS:
        if annotations is not READ and fn.__name__ not in research_api.TOOLS:
            fn = _outside_the_loop(fn)
        server.tool(annotations=annotations)(_serialized(fn))
    return server


_handbook: Handbook | None = None
# Remote mode sets this: uid -> that user's Handbook. The uid comes from the access token.
_user_store: Callable[[str], Handbook] | None = None


def handbook() -> Handbook:
    global _handbook
    if _user_store is not None:
        from mcp.server.auth.middleware.auth_context import get_access_token

        token = get_access_token()
        if token is None or not token.subject:
            raise HandbookError("not signed in: this server needs an access token with a user")
        return _user_store(token.subject)
    if _handbook is None:
        _handbook = Handbook()
        research_api.bind(_handbook)  # loads the research cards and binds the ledger to this store
    return _handbook


@tool(READ)
def lookup(
    situation: Annotated[str, Field(description="The symptom as observed: error text, alert name, or a few words.")],
    limit: int = 5,
    scope: Annotated[Literal["situation", "handbook", "research", "all"], Field(
        description="situation (default): the ordinary cards and the research cards a situation leads to (the "
                    "session loop and the abnormal cards); handbook: the ordinary cards only; research: only the "
                    "research cards (rs-*), stage and reference cards included; all: every card.")] = "situation",
) -> str:
    """Find the entries that fit a situation: a fault, a request, or what just happened in the
    conversation (the user corrected something, the same correction came again, a reference cannot
    be resolved, a step was refused). Returns each candidate's condition and objective so the right
    one can be confirmed before it is opened. The research cards entered by a routed plan object
    (stage, domain and reference cards) are found with scope="research"."""
    hb = handbook()
    rows = hb.lookup(situation, limit, scope)
    for r in rows:
        r["routes"] = _routes(hb, r["id"])
    return render.candidates(situation, rows)


def _routes(hb: Handbook, card: str) -> list[tuple[str, list[str]]]:
    """The entries that route to a card and their ledgers (entry_api.card_entries), from this store's graph."""
    from .kernel import runtime

    return entry_api.card_entries(runtime.attach(hb).g, card)


@tool(READ)
def open_entry(id: str) -> str:
    """Show one entry as a card: condition, objective, memory items, numbered steps,
    deferred items, and its related entries."""
    from .store import decomposition

    hb = handbook()
    e = hb.get_entry(id)
    card = render.card(e, hb.neighbors(id), _routes(hb, e["id"]))
    parts = decomposition(e)
    if parts and not e["id"].startswith("rs-"):
        card = (f"SPLIT BEFORE USE: this card holds more than one topic ({' · '.join(parts)}). Split it first "
                "(open_entry('rs-split')), then follow the part that fits.\n\n" + card)
    return card


@tool(READ)
def index(group_by: Literal["tag", "kind", "alpha"] = "tag") -> str:
    """List every entry, grouped by tag, by kind, or alphabetically by title."""
    return render.index(handbook().index(group_by))


@tool(READ)
def traverse(
    id: str,
    types: Annotated[
        list[str] | None,
        Field(description="Only follow these relation names, e.g. ['escalates_to']. Inverse names work too."),
    ] = None,
    depth: Annotated[int, Field(ge=1, le=6)] = 2,
) -> str:
    """Walk the relation graph outward from an entry, in both directions."""
    return render.walk(id, handbook().traverse(id, types, depth))


@tool(WRITE)
def save_entry(
    title: Annotated[str | None, Field(description="Unambiguous name of the situation. Required when creating.")] = None,
    id: Annotated[str | None, Field(description="Entry to update. Omit to create; the id is derived from the title.")] = None,
    kind: Annotated[str | None, Field(description="'checklist' (default) for procedures, 'reference' for facts and tables, or any other label.")] = None,
    condition: Annotated[str | None, Field(description="When this entry applies: the observable state that confirms it is the right one.")] = None,
    objective: Annotated[str | None, Field(description="What following the entry achieves.")] = None,
    body: Annotated[str | None, Field(description="Free reference text shown above the steps.")] = None,
    triggers: Annotated[list[str] | None, Field(description="Cues the entry should be found by: error strings, alert names, symptoms.")] = None,
    tags: list[str] | None = None,
    items: Annotated[
        list[dict[str, Any]] | None,
        Field(
            description=(
                "Ordered lines of the card. Each: {text, phase?, kind?, response?, when?, goto?, ends?}. "
                "phase: 'memory' (immediate, at most four), 'action' (default), 'deferred'. "
                "kind: 'step' (default, numbered), 'caution' or 'note' (placed before the step they concern). "
                "response: the expected result of the step. when: makes the step conditional. "
                "goto: id of the entry to continue in. ends: true if the entry is finished at this step."
            )
        ),
    ] = None,
) -> str:
    """Create an entry, or update one by id. On update, omitted arguments are kept and a
    list argument replaces the stored list. Returns the saved card. One card holds one topic: a
    procedure (one situation, one outcome, one sequence of at most 10 steps) or a set (one list or
    table); an entry holding more is refused with its parts, to be written as separate cards.
    A card is not the record of a conversation: what the user said, decided or corrected is a
    ledger row (research_add), and what a procedure missed is a change to that procedure's card."""
    hb = handbook()
    entry = hb.save_entry(
        id=id, title=title, kind=kind, condition=condition, objective=objective,
        body=body, triggers=triggers, tags=tags, items=items, atomic=True,
    )  # fmt: skip
    return render.card(entry, hb.neighbors(entry["id"]))


@tool(DELETE)
def delete_entry(id: str) -> str:
    """Delete an entry and every relation that touches it. To retire an entry but keep
    its history, relate its replacement to it with 'supersedes' instead."""
    handbook().delete_entry(id)
    return f"Deleted [{id}]."


@tool(WRITE)
def relate(
    src: str,
    type: Annotated[str, Field(description="A relation type or its inverse, e.g. 'escalates_to', 'requires', 'see_also'.")],
    dst: str,
    note: Annotated[str, Field(description="Why the two are linked, shown next to the link.")] = "",
) -> str:
    """Link two entries with a typed relation, read as 'src <type> dst'."""
    s, t, d = handbook().relate(src, type, dst, note)
    return f"[{s}] {t} -> [{d}]"


@tool(DELETE)
def unrelate(src: str, type: str, dst: str) -> str:
    """Remove a relation between two entries."""
    removed = handbook().unrelate(src, type, dst)
    return "Removed." if removed else "No such relation."


@tool(WRITE)
def define_relation_type(
    name: Annotated[str, Field(description="Active-voice name read src -> dst, e.g. 'mitigates'.")],
    inverse: Annotated[str | None, Field(description="Name read dst -> src, e.g. 'mitigated_by'. Omit for a symmetric relation.")] = None,
    description: str = "",
) -> str:
    """Add a relation type, or change the inverse name or description of an existing one."""
    rt = handbook().define_relation_type(name, inverse, description)
    return f"{rt['name']} / {rt['inverse']}"


@tool(READ)
def relation_types() -> str:
    """List the relation types that entries can be linked with."""
    return "\n".join(
        f"{r['name']} / {r['inverse']}" + (f" — {r['description']}" if r["description"] else "")
        for r in handbook().relation_types()
    )


@tool(READ)
def audit() -> str:
    """Check the whole handbook for entries that are hard to find, hard to confirm,
    or broken: missing condition, too many memory items, links to nothing, orphans."""
    return render.audit(handbook().audit())


# ── research ledger: the run state of the research cards ───────────────────
# The functions live in research_api (no MCP import), so the server's CLI runs the same code.

for _fn in research_api.READ_TOOLS:
    tool(READ)(_fn)
for _fn in cap_api.WRITE_TOOLS + cap_api.DEPRECATED:
    tool(LEDGER_WRITE)(_fn)


cap_api.configure(handbook, _CALLS)
agents_api.configure(handbook, _CALLS)
for _fn in agents_api.WRITE_TOOLS:
    tool(LEDGER_WRITE)(_fn)
for _fn in agents_api.READ_TOOLS:
    tool(READ)(_fn)
for _fn in research_api.WRITE_TOOLS:
    tool(LEDGER_WRITE)(_fn)
for _fn in research_api.DELETE_TOOLS:
    tool(DELETE)(_fn)
# entry nodes and their refs (docs/entry-graph.md): reading any node, and the write path
for _fn in entry_api.READ_TOOLS:
    tool(READ)(_fn)
for _fn in entry_api.WRITE_TOOLS:
    tool(LEDGER_WRITE)(_fn)
