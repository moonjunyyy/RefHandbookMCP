"""MCP surface of the handbook."""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import render, research_api, sandbox_api
from .store import Handbook, HandbookError

INSTRUCTIONS = """\
A quick reference handbook: short cards that say what to do when a known situation comes up.
When something goes wrong or a recurring task starts, call `lookup` with the symptom (an error
message, an alert, a few words). Check a candidate's CONDITION really matches, then `open_entry`
and follow it in order: memory items first, then the numbered steps, taking GO TO links when a
step's IF holds. Stop at END. Keep deferred items in mind until their moment arrives.
Cards are linked: RELATED lists what to open next (escalates_to, requires, see_also, ...).
When you solve a problem no card covers, record it with `save_entry` and link it with `relate`.
Research work runs as a ledgered session loop over the research cards (rs-*): every user message
opens a session with `research_begin` (its first line is the SESSION token every later call names),
works the plan objects with `research_next` / `research_push` / `research_done`, and closes with
`research_end` before the reply. Sessions run side by side (another conversation, an agent with
role="agent"); a CONFLICT names objects to re-read, nothing else is shared.
Computation runs in the user's sandbox: write a script with `sandbox_script`, run it with
`sandbox_run` (a background job; read it later with `sandbox_job`), and keep files in the workspace
with `sandbox_files`. A script needs no approval: it can use only what the user's policy
(`sandbox_policy`) puts in the sandbox. Never ask the user to approve a run."""

def _version() -> str:
    from .manifest import project_version

    return project_version()


mcp = MCPServer("refhandbook", instructions=INSTRUCTIONS, version=_version())

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

TOOLS: list[tuple[Callable[..., Any], ToolAnnotations]] = []


def tool(annotations: ToolAnnotations) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a tool on the local (stdio) server and record it, so the remote server
    (remote.build) registers the same set."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        TOOLS.append((fn, annotations))
        mcp.tool(annotations=annotations)(_serialized(fn))
        return fn

    return deco


def install(server: MCPServer) -> None:
    for fn, annotations in TOOLS:
        server.tool(annotations=annotations)(_serialized(fn))


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
    scope: Annotated[Literal["handbook", "research", "all"], Field(
        description="handbook: the ordinary cards (default); research: only the research cards (rs-*); all: both.")] = "handbook",
) -> str:
    """Find the entries that fit a situation. Returns each candidate's condition and
    objective so the right one can be confirmed before it is opened. The research loop's cards
    (rs-*) are found with scope="research"."""
    return render.candidates(situation, handbook().lookup(situation, limit, scope))


@tool(READ)
def open_entry(id: str) -> str:
    """Show one entry as a card: condition, objective, memory items, numbered steps,
    deferred items, and its related entries."""
    hb = handbook()
    return render.card(hb.get_entry(id), hb.neighbors(id))


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
    list argument replaces the stored list. Returns the saved card."""
    hb = handbook()
    entry = hb.save_entry(
        id=id, title=title, kind=kind, condition=condition, objective=objective,
        body=body, triggers=triggers, tags=tags, items=items,
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
# The functions live in research_api (no MCP import), so the CLI fallback runs the same code.

for _fn in research_api.READ_TOOLS:
    tool(READ)(_fn)
for _fn in sandbox_api.READ_TOOLS:
    tool(READ)(_fn)
for _fn in sandbox_api.WRITE_TOOLS:
    tool(LEDGER_WRITE)(_fn)


sandbox_api.configure(handbook, _CALLS)
for _fn in research_api.WRITE_TOOLS:
    tool(LEDGER_WRITE)(_fn)
for _fn in research_api.DELETE_TOOLS:
    tool(DELETE)(_fn)
