"""The agents at work (docs/agents.md §6): one `Crew` per store runs that store's approved runs, one
asyncio task per agent, in the runner unit (the only process that can open the users' API keys).

A run is found by its marker, `<db>.sandbox/runs/<hex>`, which the approval page writes when the user
approves it and the crew removes when the run closes; so the runner opens only stores with work. A
store with an enabled schedule has `<db>.sandbox/schedules`: the crew fires what is due (presets.py).

The planner (`tick`, about once a second, under the store's lock):
  - opens the root agent (a lead) of a newly approved run;
  - opens queued spawns as slots free;
  - starts a task for every open agent whose lease it can take (a crashed runner's lease expires);
  - cancels a run the user (or the model, through agent_run) asked to cancel;
  - closes a run whose root agent has finished, which applies the grant's retention.

An agent's task is the loop: lease, budget checks, one model turn, the tool calls, the results, again.
The store is never touched while a model call or a sandbox command is in flight: every store access
is a short `with self.lock:` block with no await inside, so the job runner's threads and the planner
interleave with the agents.

Routing (the grant's `routes`): an agent starts on the first route for its role. A call that keeps
failing (retryable errors after backoff), a refused key or a refused endpoint moves it to the next
route for the role; with another wire format, its transcript cannot be carried over, so it starts a
new segment from its brief and notes. With no route left, the agent is cancelled with the reason,
which its parent (or, for the root, the user) reads.

Transcripts are JSONL files beside the store (`<db>.sandbox/agents/<hex>/transcripts/<a>.jsonl`), one
line per model turn, user text or batch of tool results, each tagged with its segment. A segment is
what one model call sees; a new one starts at a digest checkpoint, at every step under the `minimal`
context level, and after a switch of wire format. A turn whose tool results never landed (the runner
was killed) gets "interrupted" results on resume: tool calls are never replayed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..kernel.graph import KernelError
from ..kernel.scopes import ScopeRefused
from ..store import HandbookError
from . import providers as P
from .http import Client, HttpError
from .keys import Key, KeyError_, KeyStore, scrub
from . import flows
from .presets import Presets
from .team import NOTE_KINDS, ROLES, Team, TeamError, render_note
from .workspace import Workspace

log = logging.getLogger("refhandbook.crew")

K = "kernel"
LEASE = 120.0  # seconds; renewed before every step and while waiting
TICK = 1.0
SHOW = 6000  # characters of a tool result the model sees (head and tail of longer output)
DIGEST_EVERY = 12  # steps per segment under the digest context level
MAX_CLONES = 4
WAIT_MAX = 7200.0
POLL = 1.0  # seconds between checks while an agent waits for children (no tokens spent)
JOB_POLL = 0.3  # … and while its sandbox command runs
NUDGES = 2  # answers without a tool call before the answer is taken as the agent's exit
CONCURRENT_CALLS = 4  # model calls in flight per key


def run_dir(ws: Workspace, run: str) -> Path:
    return ws.base / "agents" / run.split(":", 1)[1]


def mark(ws: Workspace, run: str) -> None:
    """Tell the runner the run has work (the approval page, after the grant)."""
    d = ws.base / "runs"
    d.mkdir(parents=True, exist_ok=True)
    (d / run.split(":", 1)[1]).touch()


def unmark(ws: Workspace, run: str) -> None:
    (ws.base / "runs" / run.split(":", 1)[1]).unlink(missing_ok=True)


def schedules_marker(ws: Workspace) -> Path:
    """Present while the store has an enabled schedule (agents/presets.py), so the runner opens it."""
    return ws.base / "schedules"


def _cut(text: str, n: int = SHOW) -> str:
    if len(text) <= n:
        return text
    head = n // 3
    return f"{text[:head]}\n… ({len(text) - n} characters cut) …\n{text[-(n - head):]}"


# ── prompts and tools: fixed for an agent's life, so the provider's prompt cache holds ──────

COMMON = """\
You are one agent of a team working on a run for a user. The team shares knowledge through notes
(a note is written once and passed by id), talks through messages, and splits work by spawning
agents. Your brief (the first message) says who you are, your task, and what you hold.

How to work:
- Work with the tools. Every answer you give must be a tool call; text alone does not reach anyone.
- Record what you learn as notes (note): one fact, finding, decision or plan per note, with the ids
  it rests on in refs. Others see your notes by id; post=true shares a note with the whole run.
- The sandbox (sh, read, write, ls) has no network unless the user's policy allows it; your working
  directory there is your run's directory under /work, shared with your team.
- Spawn only for independent, context-heavy subtasks; give a child the note ids it needs (give),
  not long text. Prefer the cheaper models for workers when the grant offers them (spawn's model).
- Read your children's results with wait before you finish; you cannot finish while one is unread.
- A note becomes verified only when another agent checks it (verify). Never verify your own note.
- End with finish(outcome, text, refs): text is what your parent (or the user) reads; refs carry the
  notes that back it. If finish is refused, the refusal says what is missing.
- Stuck on a known kind of problem? lookup the symptom in the handbook and follow the card.
"""

ROLE_TEXT = {
    "lead": "Your role: lead. Plan the work, split it among workers where that pays, check what comes "
            "back (have a verifier check what matters), and give the user one clear result.",
    "worker": "Your role: worker. Do your task thoroughly and report back what you found or made, with "
              "the notes and files that back it. Spawn only if your task truly splits.",
    "verifier": "Your role: verifier. Check the notes and results you were given: re-derive, re-run, look "
                "for counter-evidence. Mark each with verify (verified or disputed, with evidence), then "
                "finish with your verdict.",
}


def system_prompt(role: str) -> str:
    return COMMON + "\n" + ROLE_TEXT[role]


S = {"type": "string"}
IDS = {"type": "array", "items": {"type": "string"}}


def _tool(name: str, description: str, props: dict[str, Any], required: list[str]) -> P.ToolSpec:
    return P.ToolSpec(name, description, {"type": "object", "properties": props, "required": required})


TOOLS = [
    _tool("sh", "Run a shell command in the sandbox, in your run's directory under /work. Returns the exit "
          "code, stdout and stderr (long output is cut in the middle).",
          {"cmd": S, "timeout": {"type": "number", "description": "seconds; at most the policy's"}}, ["cmd"]),
    _tool("read", "Read a text file of the workspace (a path relative to your run's directory, or /work/…).",
          {"path": S, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, ["path"]),
    _tool("write", "Write a text file of the workspace (replacing it).", {"path": S, "text": S}, ["path", "text"]),
    _tool("ls", "List a directory of the workspace.", {"path": S}, []),
    _tool("note", "Record a note (one fact, finding, plan, decision or question). Returns its id.",
          {"text": S, "kind": {"type": "string", "enum": list(NOTE_KINDS)}, "title": S, "refs": IDS,
           "pin": {"type": "boolean", "description": "keep it whole in your context"},
           "post": {"type": "boolean", "description": "share it with every agent of the run"}}, ["text"]),
    _tool("recall", "Search the run's notes by words.", {"query": S, "limit": {"type": "integer"}}, ["query"]),
    _tool("open", "Show a note, message or artifact of the run by id.", {"id": S}, ["id"]),
    _tool("verify", "Mark another agent's note verified or disputed, with your evidence.",
          {"id": S, "verdict": {"type": "string", "enum": ["verified", "disputed"]}, "evidence": S},
          ["id", "verdict", "evidence"]),
    _tool("send", "Send a message to another agent of the run, carrying notes by id.",
          {"to": S, "text": S, "refs": IDS}, ["to", "text"]),
    _tool("spawn", "Start agents. mode fresh: one agent (role, goal, give). split: one per part. clone: n "
          "copies of you that continue from your context, each with a variant instruction. Returns ids; "
          "with no slot free a spawn is queued and starts when one frees.",
          {"mode": {"type": "string", "enum": ["fresh", "split", "clone"]},
           "role": {"type": "string", "enum": list(ROLES)}, "goal": S, "give": IDS,
           "model": {"type": "string", "description": "one of the grant's models for that role"},
           "parts": {"type": "array", "items": {"type": "object", "properties": {
               "goal": S, "give": IDS, "role": {"type": "string", "enum": list(ROLES)}, "model": S},
               "required": ["goal"]}},
           "n": {"type": "integer"}, "variants": {"type": "array", "items": S}}, ["mode"]),
    _tool("wait", "Wait (without spending tokens) for agents you spawned to finish, and read their results. "
          "ids: default all your unfinished children. mode all (default) or any.",
          {"ids": IDS, "mode": {"type": "string", "enum": ["all", "any"]}, "timeout": {"type": "number"}}, []),
    _tool("cancel", "Cancel one of your descendants (and its own descendants).", {"id": S, "why": S}, ["id", "why"]),
    _tool("checkpoint", "Write a digest of your work so far (goal, done, open, decisions, note ids); your "
          "context restarts from it. Call it when asked to.", {"digest": S}, ["digest"]),
    _tool("finish", "End your work: outcome, the text your parent (or the user) reads, and the notes that "
          "back it.", {"outcome": {"type": "string", "enum": ["done", "partial", "failed"]}, "text": S,
                       "refs": IDS}, ["outcome", "text"]),
    _tool("lookup", "Find handbook cards for a situation (a symptom, an error, a few words).", {"situation": S},
          ["situation"]),
    _tool("open_entry", "Open a handbook card by id.", {"id": S}, ["id"]),
]


# ── transcripts ──────────────────────────────────────────────────────────


class Transcript:
    def __init__(self, path: Path):
        self.path = path

    def lines(self, seg: int | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for raw in self.path.read_text().splitlines():
            try:
                x = json.loads(raw)
            except ValueError:
                continue  # a line cut by a crash
            if seg is None or x.get("seg") == seg:
                out.append(x)
        return out

    def append(self, seg: int, kind: str, entries: list[Any], calls: list[P.ToolCall] | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line: dict[str, Any] = {"seg": seg, "kind": kind, "entries": entries, "at": round(time.time(), 3)}
        if calls:
            line["calls"] = [{"id": c.id, "name": c.name, "args": c.args} for c in calls]
        with open(self.path, "a") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


# ── an agent's state in the task ─────────────────────────────────────────


class AgentFailed(Exception):
    pass


@dataclass
class Ctx:
    aid: str
    run: str
    role: str
    seg: int
    route: int
    adapter: P.Adapter
    key: Key
    transcript: Transcript
    history: list[Any] = field(default_factory=list)
    finished: bool = False
    new_segment: str | None = None  # a digest to restart from after this step
    since_segment: int = 0


class Crew:
    """The runs of one store. Every store access holds `lock` (the job runner's lock for the store)."""

    def __init__(self, ws: Workspace, lock: threading.RLock, keys: KeyStore | None, *,
                 runner: Any = None, adapter_for: Callable[[Key], P.Adapter] | None = None,
                 http: Client | None = None):
        self.ws, self.lock, self.keys, self.runner = ws, lock, keys, runner
        self.adapter_for = adapter_for or (lambda k: P.adapter(k.format, k.base_url))
        self.http = http
        with lock:
            self.team = Team(ws.g)
            self.presets = Presets(ws.g, schedules_marker(ws))
        self.g = ws.g
        self.uid = ws.owner
        self.rid = f"crew:{os.getpid()}:{secrets.token_hex(3)}"
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.sems: dict[str, asyncio.Semaphore] = {}
        self.stopped = False

    # ── the planner ──────────────────────────────────────────────────────

    def runs(self) -> list[str]:
        d = self.ws.base / "runs"
        return [f"run:{m.name}" for m in sorted(d.iterdir())] if d.is_dir() else []

    async def serve(self) -> None:
        while not self.stopped:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 — one bad tick never stops the crew
                log.exception("crew %s: tick", self.uid)
            await asyncio.sleep(TICK)

    async def tick(self) -> int:
        """One planning pass; returns how many agent tasks it started."""
        if self.http is None:
            self.http = Client(timeout=900.0)
        for aid, t in list(self.tasks.items()):
            if t.done():
                del self.tasks[aid]
        with self.lock:  # the user's schedules that are due open their runs (as the page would)
            for run in self.presets.due():
                mark(self.ws, run)
        started = 0
        for run in self.runs():
            with self.lock:
                start = self._plan(run)
            for aid in start:
                self.tasks[aid] = asyncio.create_task(self._agent(aid), name=aid)
                started += 1
        return started

    def _plan(self, run: str) -> list[str]:
        t, g = self.team, self.g
        n = g.get_node(run)
        if n is None or n["state"] != "open":
            unmark(self.ws, run)
            return []
        a = n["attrs"]
        if a.get("cancel"):
            for ag in t.agents(run, "open"):
                task = self.tasks.pop(ag["id"], None)
                if task is not None:
                    task.cancel()
            t.cancel_run(run, str(a["cancel"]), actor=K)
            self._retained(run)
            unmark(self.ws, run)
            return []
        if a.get("phase") not in ("approved", "running"):
            return []
        root = t.root(run)
        if root is None:
            try:
                root = t.open_agent(run, role="lead", goal=n["content"], mode="root", actor=K)
            except (KernelError, HandbookError) as e:
                t.set_phase(run, "failed", error=str(e))
                t.cancel_run(run, f"the lead could not start: {e}", actor=K)
                unmark(self.ws, run)
                return []
        if g.node(root)["state"] == "closed":
            ra = g.node(root)["attrs"]
            if ra.get("outcome") in ("cancelled", "failed"):  # the lead did not get there: the run failed
                t.set_phase(run, "failed", error=ra.get("error") or f"the lead ended {ra.get('outcome')}")
            try:
                t.close_run(run, actor=K)
            except ScopeRefused as e:
                t.set_phase(run, "failed", error=str(e))
                log.warning("run %s cannot close: %s", run, e)
            self._retained(run)
            unmark(self.ws, run)
            return []
        for q in t.queued(run):
            if t.free_slot(run) is None:
                break
            spec, parent = q["attrs"]["spec"], q["attrs"]["parent"]
            if g.node(parent)["state"] != "open":
                t.mark_request(q["id"], "dropped", why="its parent finished")
                continue
            try:
                child = t.open_agent(run, parent=parent, actor="model", **spec)
                t.mark_request(q["id"], "started", agent=child)
            except (KernelError, HandbookError) as e:
                t.mark_request(q["id"], "dropped", why=str(e))
        start = []
        for ag in t.agents(run, "open"):
            if ag["id"] in self.tasks:
                continue
            if t.lease(ag["id"], self.rid, LEASE):
                start.append(ag["id"])
        return start

    def _retained(self, run: str) -> None:
        """Transcripts follow retention: kept under all and verified, removed under exits and purge."""
        try:
            level = self.team.grant(run)["retention"]
        except TeamError:
            level = "verified"
        if level in ("exits", "purge"):
            shutil.rmtree(run_dir(self.ws, run) / "transcripts", ignore_errors=True)

    # ── an agent ─────────────────────────────────────────────────────────

    async def _agent(self, aid: str) -> None:
        try:
            await self._live(aid)
        except asyncio.CancelledError:
            raise
        except AgentFailed as e:
            self._fail(aid, str(e))
        except Exception as e:  # noqa: BLE001 — the agent ends with the reason; the crew goes on
            log.exception("agent %s", aid)
            self._fail(aid, f"runner error: {type(e).__name__}: {e}")
        finally:
            with self.lock:
                n = self.g.get_node(aid)
                if n is not None and n["state"] == "open":
                    self.team.release(aid, self.rid)

    # ── a flow's conductor (agents/flows.py): the root of a run with a flow, which calls no model ──

    async def _conduct(self, aid: str, flow: dict[str, Any]) -> None:
        while True:
            with self.lock:
                if not self.team.lease(aid, self.rid, LEASE) or self.g.node(aid)["state"] != "open":
                    return
                if self._conduct_step(aid, flow):
                    return
            await asyncio.sleep(POLL)

    def _exit(self, root: str, child: str) -> dict[str, Any] | None:
        for e in self.g.edges(dst=root, type_="to"):
            p = self.g.node(e["src"])
            if p["attrs"].get("from") == child and p["attrs"].get("kind") == "exit":
                return p
        return None

    def _conduct_step(self, aid: str, flow: dict[str, Any]) -> bool:
        """One look at the flow: open what can start, skip what cannot run; True once it is finished."""
        t, g = self.team, self.g
        root = g.node(aid)
        run = root["attrs"]["run"]
        placed: dict[str, str] = dict(root["attrs"].get("flow_agents") or {})  # step → agent
        skipped: dict[str, str] = dict(root["attrs"].get("flow_skipped") or {})  # step → why
        steps = {s["id"]: s for s in flow["steps"]}

        def outcome(sid: str) -> str | None:  # done, partial, failed, cancelled; None while not settled
            if sid in skipped:
                return "skipped"
            a = placed.get(sid)
            if a is None:
                return None
            n = g.node(a)
            return (n["attrs"].get("outcome") or "failed") if n["state"] == "closed" else None

        changed = False
        for sid in flows.order(flow["steps"], flow["edges"]):
            if sid in placed or sid in skipped:
                continue
            before = flows.inputs(flow, sid)
            got = {b: outcome(b) for b in before}
            if any(o in ("failed", "cancelled", "skipped") for o in got.values()):
                bad = [b for b, o in got.items() if o in ("failed", "cancelled", "skipped")]
                skipped[sid] = f"after {', '.join(steps[b]['title'] for b in bad)} did not finish"
                changed = True
                continue
            if any(o is None for o in got.values()):
                continue  # still waiting on a step before it
            if t.free_slot(run) is None:
                continue  # every slot busy: next look
            s = steps[sid]
            given, lines = [], []
            for b in before:
                p = self._exit(aid, placed[b])
                if p is not None:
                    lines.append(f"From step '{steps[b]['title']}' ({got[b]}): {p['content']}")
                    given += [n["id"] for n in t.carried(p["id"])]
            goal = s["goal"] + (("\n\nWhat the steps before this one returned:\n" + "\n\n".join(lines)) if lines else "")
            try:
                child = t.open_agent(run, role=s["role"], goal=goal, parent=aid, model=s["model"] or None,
                                     give=list(dict.fromkeys(given)), actor=K, variant=s["title"])
            except ScopeRefused:
                continue  # no slot or ticket just now
            except (KernelError, HandbookError) as e:
                skipped[sid] = f"could not start: {e}"
                changed = True
                continue
            t.update_agent(child, step=sid)
            placed[sid] = child
            changed = True
        if changed:
            t.update_agent(aid, flow_agents=placed, flow_skipped=skipped, status="waiting")
        if any(outcome(sid) is None for sid in steps):
            return False
        # every step settled: read each one's result, and return them all
        parts, refs, done = [], [], 0
        for sid in flows.order(flow["steps"], flow["edges"]):
            o = outcome(sid)
            if sid in skipped:
                parts.append(f"## {steps[sid]['title']} (skipped: {skipped[sid]})")
                continue
            p = self._exit(aid, placed[sid])
            if p is not None and p["state"] == "sent":
                t.read(aid, p["id"])
            parts.append(f"## {steps[sid]['title']} ({o})\n{p['content'] if p else ''}")
            done += o in ("done", "partial")
            if sid in flows.sinks(flow) and p is not None:
                refs += [n["id"] for n in t.carried(p["id"])]
        for p in t.inbox(aid):  # anything else addressed to the conductor
            t.read(aid, p["id"])
        total = len(steps)
        result = "done" if done == total else "partial" if done else "failed"
        t.finish(aid, result, "\n\n".join(parts), list(dict.fromkeys(refs)), actor=K)
        return True

    def _fail(self, aid: str, why: str) -> None:
        with self.lock:
            n = self.g.get_node(aid)
            if n is not None and n["state"] == "open":
                self.team.update_agent(aid, error=why)
                self.team.cancel_agent(aid, why, actor=K)

    def _open_key(self, provider: str, label: str) -> Key:
        if self.keys is None:
            raise KeyError_("the runner has no access to API keys (no agent-keys credential)")
        return self.keys.get(self.uid, provider, label)

    def _brief(self, aid: str, note: str = "") -> str:
        t, g = self.team, self.g
        n = g.node(aid)
        a = n["attrs"]
        run = a["run"]
        grant = t.grant(run)
        r = g.node(run)
        held = t.held(aid)
        pinned = [render_note(x) for x, pin in held if pin]
        others = [render_note(x, full=False) for x, pin in held if not pin]
        digest = a.get("digest")
        parts = [f"You are agent {aid}, role {a['role']}, depth {a['depth']} of at most {grant['max_depth']}.",
                 f"Run {run}. The user's goal: {r['content']}"]
        if a.get("parent"):
            parts.append(f"Your parent is {a['parent']}; your task from it: {n['content']}")
        else:
            parts.append("You lead the run: your finish text is the result the user reads.")
        if a.get("variant"):
            parts.append(f"Your variant: {a['variant']}")
        parts.append(f"Sandbox: your working directory is /work/runs/{run.split(':', 1)[1]} (policy "
                     f"{grant['policy']}). Limits: {grant['max_steps']} model turns for you; "
                     f"{grant['max_agents']} agents at once and {grant['max_spawns']} in all for the run.")
        models = sorted({f"{x['model']} ({', '.join(x['roles'])})" for x in grant["routes"]})
        parts.append("Models of the grant: " + "; ".join(models))
        if pinned:
            parts.append("Notes you hold (pinned):\n" + "\n".join(pinned))
        if others:
            parts.append("Other notes you hold (open them by id):\n" + "\n".join(others))
        if digest:
            parts.append(f"Your last digest:\n{digest}")
        if note:
            parts.append(note)
        return "\n\n".join(parts)

    def _route(self, aid: str) -> tuple[dict[str, Any], dict[str, Any], int]:
        n = self.g.node(aid)
        grant = self.team.grant(n["attrs"]["run"])
        i = int(n["attrs"].get("route", 0))
        return n, grant, i

    async def _live(self, aid: str) -> None:
        with self.lock:
            n = self.g.node(aid)
            flow = None if n["attrs"].get("parent") else self.g.node(n["attrs"]["run"])["attrs"].get("flow")
        if flow:
            return await self._conduct(aid, flow)
        with self.lock:
            n, grant, i = self._route(aid)
            a = n["attrs"]
            route = grant["routes"][i]
            run_root = run_dir(self.ws, a["run"])
        provider, label = route["key"].split("/", 1)
        try:
            key = await asyncio.to_thread(self._open_key, provider, label)
        except KeyError_ as e:
            key = Key(provider, label, "", "", "")
            ctx = Ctx(aid, a["run"], a["role"], int(a.get("segment", 0)), i, P.Adapter(), key,
                      Transcript(run_root / a["transcript"]))
            await self._next_route(ctx, f"key {route['key']}: {e}")
        else:
            ctx = Ctx(aid, a["run"], a["role"], int(a.get("segment", 0)), i, self.adapter_for(key), key,
                      Transcript(run_root / a["transcript"]))
            self._load(ctx)
        nudges = 0
        while True:
            await asyncio.sleep(0)  # one step at a time per agent: no agent holds the loop
            with self.lock:
                if not self.team.lease(aid, self.rid, LEASE):
                    return  # another runner holds it now
                n, grant, _ = self._route(aid)
                if n["state"] != "open":
                    return
                warn = self._budget(n, grant)
                if warn is None:
                    return  # out of budget: cancelled
                self.team.update_agent(aid, status="running")
                opts = P.Options(effort=grant.get("effort") or None, trim=n["attrs"]["context"] == "trim",
                                 agent={"id": aid, "role": ctx.role, "goal": n["content"], "run": ctx.run,
                                        "parent": n["attrs"].get("parent"), "variant": n["attrs"].get("variant")})
                model = grant["routes"][ctx.route]["model"]
            step = await self._call(ctx, model, opts)
            ctx.transcript.append(ctx.seg, "turn", step.native, step.calls)
            ctx.history += step.native
            with self.lock:
                self.team.add_usage(aid, step.usage)
            if not step.calls:
                nudges += 1
                if step.refusal or nudges > NUDGES:
                    if self._auto_finish(ctx, step):
                        return
                msg = ("You answered without a tool call; nobody reads that. To end, call finish(outcome, text, "
                       "refs); otherwise go on with the tools.")
                self._say(ctx, msg)
                continue
            nudges = 0
            results = []
            for call in step.calls:
                if ctx.finished:
                    results.append((call, "not run: you finished in an earlier call of this turn", True))
                    continue
                text, err = await self._dispatch(ctx, call)
                results.append((call, text, err))
            if ctx.finished:
                ctx.transcript.append(ctx.seg, "results", ctx.adapter.results(results))
                return
            with self.lock:
                extra = self._mail(ctx) + (warn and [warn] or [])
                if self.g.node(aid)["attrs"]["context"] == "digest":
                    ctx.since_segment += 1
                    if ctx.since_segment >= DIGEST_EVERY and ctx.new_segment is None:
                        extra.append("Checkpoint now: call checkpoint(digest) with your goal, what is done, what "
                                     "is open, the decisions made and the note ids that matter.")
            entries = ctx.adapter.results(results, "\n\n".join(extra) or None)
            ctx.transcript.append(ctx.seg, "results", entries)
            ctx.history += entries
            with self.lock:
                level = self.g.node(aid)["attrs"]["context"]
            if ctx.new_segment is not None:
                self._segment(ctx, f"You checkpointed; your digest is above. Continue from it.")
            elif level == "minimal":
                self._segment(ctx, "Your last step:\n" + _render_step(step, results))

    def _load(self, ctx: Ctx) -> None:
        """The current segment's history, with interrupted tool calls answered; or a fresh brief."""
        lines = ctx.transcript.lines(ctx.seg)
        if not lines:
            with self.lock:
                brief = self._brief(ctx.aid)
            self._say(ctx, brief)
            return
        for x in lines:
            ctx.history += x["entries"]
        last = lines[-1]
        if last["kind"] == "turn" and last.get("calls"):
            calls = [P.ToolCall(c["id"], c["name"], c["args"]) for c in last["calls"]]
            entries = ctx.adapter.results([(c, "interrupted: the runner restarted before this call finished; it "
                                                  "was not re-run. Check its effects before repeating it.", True)
                                           for c in calls])
            ctx.transcript.append(ctx.seg, "results", entries)
            ctx.history += entries

    def _say(self, ctx: Ctx, text: str) -> None:
        entries = ctx.adapter.user(text)
        ctx.transcript.append(ctx.seg, "user", entries)
        ctx.history += entries

    def _segment(self, ctx: Ctx, note: str) -> None:
        ctx.seg += 1
        ctx.history = []
        ctx.new_segment = None
        ctx.since_segment = 0
        with self.lock:
            self.team.update_agent(ctx.aid, segment=ctx.seg)
            brief = self._brief(ctx.aid, note)
        self._say(ctx, brief)

    def _budget(self, n: dict[str, Any], grant: dict[str, Any]) -> str | None:
        """None if the agent is out of budget (it is cancelled here); else a warning to pass on, or ''."""
        a = n["attrs"]
        steps, max_steps = int(a.get("steps", 0)), int(grant["max_steps"])
        if steps >= max_steps:
            self.team.cancel_agent(n["id"], f"its {max_steps} model turns are used up", actor=K)
            return None
        used = self.team.run_usage(a["run"])
        tokens, max_tokens = used.get("input", 0) + used.get("output", 0), int(grant["max_tokens"])
        if max_tokens and tokens >= max_tokens:
            self.team.update_agent(n["id"], error="token budget used up")
            self.g.update_node(a["run"], actor=K, attrs={"cancel": f"the run's {max_tokens} tokens are used up",
                                                         "cancel_by": "kernel"})
            return None
        if steps >= max_steps - 3 or (max_tokens and tokens >= 0.9 * max_tokens):
            return (f"Budget nearly used up ({steps}/{max_steps} turns" + (f", {tokens}/{max_tokens} tokens" if max_tokens
                    else "") + "): wrap up now and finish with what you have.")
        return ""

    def _auto_finish(self, ctx: Ctx, step: P.Step) -> bool:
        """An agent that keeps answering in plain text (or a refusal) ends with that text as its exit."""
        outcome = "failed" if step.refusal else "done"
        with self.lock:
            try:
                self.team.finish(ctx.aid, outcome, step.text or "(no answer)", actor="model")
                return True
            except ScopeRefused as e:
                if step.refusal:
                    self.team.cancel_agent(ctx.aid, f"the model declined: {step.text[:300]}", actor=K)
                    return True
                self._say(ctx, f"finish refused: {e}")
                return False

    # ── model calls, with backoff and routing ───────────────────────────

    def _sem(self, ref: str) -> asyncio.Semaphore:
        s = self.sems.get(ref)
        if s is None:
            s = self.sems[ref] = asyncio.Semaphore(CONCURRENT_CALLS)
        return s

    async def _call(self, ctx: Ctx, model: str, opts: P.Options) -> P.Step:
        system = system_prompt(ctx.role)
        assert self.http is not None
        while True:
            err = ""
            for attempt in range(5):
                try:
                    if ctx.key.provider == "custom":
                        await P.check_endpoint(ctx.adapter.base)
                    async with self._sem(f"{ctx.key.provider}/{ctx.key.label}"):
                        return await ctx.adapter.step(self.http, ctx.key.secret, model, system, TOOLS, ctx.history, opts)
                except P.ProviderError as e:
                    err = scrub(str(e), [ctx.key.secret])
                    if e.auth:
                        await asyncio.to_thread(self._mark_key, ctx.key, "rejected")
                        break
                    if not e.retryable or attempt == 4:
                        break
                    await asyncio.sleep(min(60.0, e.retry_after or 2.0 * 2 ** attempt))
                except HttpError as e:
                    err = scrub(f"{type(e).__name__}: {e}", [ctx.key.secret])
                    if attempt == 4:
                        break
                    await asyncio.sleep(2.0 * 2 ** attempt)
            model = await self._next_route(ctx, err)

    def _mark_key(self, key: Key, status: str) -> None:
        if self.keys is not None:
            self.keys.mark(self.uid, key.provider, key.label, status)

    async def _next_route(self, ctx: Ctx, why: str) -> str:
        """Move the agent to its next route; returns the model. No route left: AgentFailed."""
        with self.lock:
            n, grant, i = self._route(ctx.aid)
            order = list(n["attrs"].get("routes") or [i])
            later = order[order.index(i) + 1:] if i in order else []
        for j in later:
            route = grant["routes"][j]
            provider, label = route["key"].split("/", 1)
            try:
                key = await asyncio.to_thread(self._open_key, provider, label)
            except KeyError_ as e:
                why = f"{why}; key {route['key']}: {e}"
                continue
            old = ctx.adapter
            ctx.key, ctx.adapter, ctx.route = key, self.adapter_for(key), j
            with self.lock:
                self.team.update_agent(ctx.aid, route=j, provider=provider, key=label, model=route["model"],
                                       last_switch=why[:500])
                self.g.log(K, f"agent moved to route {j} ({route['key']} {route['model']}): {why[:300]}", ctx.aid)
            if not ctx.history or old.name != ctx.adapter.name:
                self._segment(ctx, f"(You continue on {route['model']}: the previous model failed. Your notes "
                                   "above are what you have; re-check files in the workspace if needed.)")
            return route["model"]
        raise AgentFailed(f"no route left for this {ctx.role}: {why}")

    # ── tools ────────────────────────────────────────────────────────────

    async def _dispatch(self, ctx: Ctx, call: P.ToolCall) -> tuple[str, bool]:
        if call.error:
            return call.error, True
        fn = getattr(self, f"_t_{call.name}", None)
        if fn is None:
            return f"no tool {call.name!r}", True
        try:
            out = fn(ctx, call, **call.args)
            if asyncio.iscoroutine(out):
                out = await out
            return _cut(str(out)), False
        except TypeError as e:
            return f"bad arguments for {call.name}: {e}", True
        except (KernelError, HandbookError, ValueError, OSError) as e:
            return _cut(str(e)), True

    def _path(self, ctx: Ctx, path: str) -> str:
        path = (path or ".").strip()
        return path if path == "/work" or path.startswith("/work/") else f"runs/{ctx.run.split(':', 1)[1]}/{path}"

    async def _t_sh(self, ctx: Ctx, call: P.ToolCall, cmd: str, timeout: float | None = None) -> str:
        d = f"/work/runs/{ctx.run.split(':', 1)[1]}"
        with self.lock:
            policy = self.team.grant(ctx.run)["policy"]
            pol = self.ws.policy(policy)["attrs"]
            if pol["commands"] != ["*"] and "sh" not in pol["commands"]:
                raise TeamError(f"policy {policy} does not offer sh")
            limit = float(pol["timeout"])
            t = limit if timeout is None else max(1.0, min(float(timeout), limit))
            body = f"mkdir -p {d} && cd {d} || exit 1\n{cmd}\n"
            jid = f"job:{secrets.token_hex(5)}"
            self.g.put_node(jid, "job", actor="model", state="queued", content=f"{ctx.aid}: {cmd[:200]}", attrs={
                "script": f"agent:{ctx.aid.rsplit(':', 1)[1]}", "blob": self.g.put_blob(body), "interpreter": "sh",
                "policy": policy, "args": [], "timeout": t, "submitted": time.time(), "agent": ctx.aid})
            (self.ws.base / "queue" / jid[4:]).touch()
        if self.runner is not None:
            await asyncio.to_thread(self.runner.poll)
        end = time.time() + t + 120
        while True:
            await asyncio.sleep(JOB_POLL)
            with self.lock:
                j = self.ws.job(jid)
                if j["state"] not in ("queued", "running"):
                    break
                if time.time() > end:
                    self.ws.cancel(jid, actor="kernel")
                    end += 30
                self.team.lease(ctx.aid, self.rid, LEASE)
        from ..cap_api import _hints

        with self.lock:
            j = self.ws.job(jid)
            out, err = self.ws.output(j, "stdout"), self.ws.output(j, "stderr")
            hints = _hints(self.ws, j)
        a = j["attrs"]
        head = f"{j['state']}" + (f", exit {a['exit']}" if "exit" in a else "") + (f": {a['error']}" if a.get("error") else "")
        return (f"{head}\n--- stdout ---\n{_cut(out, SHOW // 2)}" + (f"\n--- stderr ---\n{_cut(err, SHOW // 3)}" if err else "")
                + "".join("\n" + h for h in hints))

    def _t_read(self, ctx: Ctx, call: P.ToolCall, path: str, offset: int = 0, limit: int = 0) -> str:
        with self.lock:
            text = self.ws.read(self._path(ctx, path))
        lines = text.splitlines()
        if offset or limit:
            lines = lines[max(0, offset):(offset + limit) if limit else None]
        return "\n".join(lines)

    def _t_write(self, ctx: Ctx, call: P.ToolCall, path: str, text: str) -> str:
        with self.lock:
            n = self.ws.write(self._path(ctx, path), text)
        return f"wrote {n} bytes to {path}"

    def _t_ls(self, ctx: Ctx, call: P.ToolCall, path: str = ".") -> str:
        with self.lock:
            rows = self.ws.ls(self._path(ctx, path))
        return "\n".join(f"{k:4} {size:>10}  {name}" for name, k, size in rows) or "(empty)"

    def _t_note(self, ctx: Ctx, call: P.ToolCall, text: str, kind: str = "finding", title: str = "",
                refs: list[str] | None = None, pin: bool = False, post: bool = False) -> str:
        with self.lock:
            return self.team.note(ctx.run, ctx.aid, text, kind=kind, refs=refs, pin=pin, post=post, title=title)

    def _t_recall(self, ctx: Ctx, call: P.ToolCall, query: str, limit: int = 8) -> str:
        with self.lock:
            found = self.team.recall(ctx.run, query, agent=ctx.aid, limit=max(1, min(int(limit), 30)))
        return "\n".join(render_note(n, full=False) for n in found) or "no notes match"

    def _t_open(self, ctx: Ctx, call: P.ToolCall, id: str) -> str:
        with self.lock:
            n = self.g.node(id)
            if self.team._run_of(id) != ctx.run:
                raise TeamError(f"{id} belongs to another run")
            if n["type"] == "note":
                return render_note(n)
            if n["type"] == "packet":
                carried = self.team.carried(id)
                return (f"[{id}] from {n['attrs'].get('from')} ({n['attrs'].get('kind')}): {n['content']}"
                        + "".join("\n  carries " + render_note(c, full=False) for c in carried))
            if n["type"] == "artifact":
                return f"[{id}] file {n['attrs'].get('path')} ({n['attrs'].get('size')} bytes)"
        raise TeamError(f"{id} is a {n['type']}, not a note, message or artifact")

    def _t_verify(self, ctx: Ctx, call: P.ToolCall, id: str, verdict: str, evidence: str) -> str:
        with self.lock:
            if self.team._run_of(id) != ctx.run:
                raise TeamError(f"{id} belongs to another run")
            n = self.team.verify(id, ctx.aid, verdict, evidence)
        return f"{id} is {n['state']}"

    def _t_send(self, ctx: Ctx, call: P.ToolCall, to: str, text: str, refs: list[str] | None = None) -> str:
        with self.lock:
            handoff = self.g.node(ctx.aid)["attrs"]["handoff"]
            return self.team.send(ctx.aid, to, text, refs, handoff=handoff)

    def _t_spawn(self, ctx: Ctx, call: P.ToolCall, mode: str, role: str = "worker", goal: str = "",
                 give: list[str] | None = None, model: str | None = None, parts: list[dict[str, Any]] | None = None,
                 n: int = 1, variants: list[str] | None = None) -> str:
        with self.lock:
            me = self.g.node(ctx.aid)
            if mode == "fresh":
                if not goal.strip():
                    raise TeamError("a spawn needs a goal")
                specs = [{"role": role, "goal": goal, "give": give or [], "model": model, "mode": "fresh"}]
            elif mode == "split":
                if not parts:
                    raise TeamError("split needs parts: [{goal, give, role?, model?}]")
                specs = [{"role": p.get("role") or role, "goal": p["goal"], "give": p.get("give") or [],
                          "model": p.get("model") or model, "mode": "split"} for p in parts]
            elif mode == "clone":
                k = max(1, min(int(n or len(variants or []) or 1), MAX_CLONES))
                vs = (variants or []) + [""] * k
                specs = [{"role": ctx.role, "goal": me["content"], "give": [], "model": me["attrs"]["model"],
                          "mode": "clone", "variant": vs[i]} for i in range(k)]
            else:
                raise TeamError("mode: fresh, split or clone")
            out = []
            for spec in specs:
                if self.team.free_slot(ctx.run) is None:
                    out.append(f"{self.team.queue_spawn(ctx.run, ctx.aid, spec)} (queued: starts when a slot frees)")
                    continue
                try:
                    child = self.team.open_agent(ctx.run, parent=ctx.aid, actor="model", **spec)
                except ScopeRefused as e:
                    out.append(f"refused: {e}")
                    continue
                if mode == "clone":
                    self._clone_transcript(ctx, call, child, spec["variant"])
                out.append(child)
        return "\n".join(out)

    def _clone_transcript(self, ctx: Ctx, call: P.ToolCall, child: str, variant: str) -> None:
        """A clone on the same wire format continues from its parent's segment: the parent's spawn call
        is answered, in the clone's copy, with who the clone is."""
        c = self.g.node(child)
        grant = self.team.grant(ctx.run)
        route = grant["routes"][int(c["attrs"]["route"])]
        if route["key"] != f"{ctx.key.provider}/{ctx.key.label}":
            return  # another key or format: the clone starts from its brief
        dst = Transcript(run_dir(self.ws, ctx.run) / c["attrs"]["transcript"])
        for x in ctx.transcript.lines(ctx.seg):
            dst.append(0, x["kind"], x["entries"], None)
        last = ctx.transcript.lines(ctx.seg)[-1]
        answers = [(P.ToolCall(x["id"], x["name"], x["args"]),
                    f"You are the clone {child}, not the agent that spawned you. Continue the task on your own"
                    + (f" with this variant: {variant}" if variant else "") + "; finish when done." if x["id"] == call.id
                    else "not run in the clone", x["id"] != call.id) for x in last.get("calls") or []]
        dst.append(0, "results", ctx.adapter.results(answers))

    async def _t_wait(self, ctx: Ctx, call: P.ToolCall, ids: list[str] | None = None, mode: str = "all",
                      timeout: float | None = None) -> str:
        end = time.time() + max(1.0, min(float(timeout or WAIT_MAX), WAIT_MAX))
        with self.lock:
            if ids is None or not ids:
                ids = [c["id"] for c in self.team.children(ctx.aid) if c["state"] == "open"]
                ids += [q["id"] for q in self.team.queued(ctx.run) if q["attrs"]["parent"] == ctx.aid]
            for i in ids:
                n = self.g.node(i)
                if n["type"] == "agent" and n["attrs"].get("parent") != ctx.aid:
                    raise TeamError(f"{i} is not a child of yours")
            if not ids:
                return "you have no unfinished children"
            self.team.update_agent(ctx.aid, status="waiting")
        while True:
            with self.lock:
                done, pending, dropped = self._resolve(ids)
                if self.g.node(ctx.aid)["state"] != "open":
                    raise TeamError("you were cancelled")
                if (mode == "any" and (done or dropped)) or not pending or time.time() > end:
                    out = [self._exit_of(ctx.aid, a) for a in done] + [f"{q}: not started ({why})" for q, why in dropped]
                    if pending:
                        out.append("still running: " + ", ".join(pending))
                    self.team.update_agent(ctx.aid, status="running")
                    return "\n\n".join(out)
                self.team.lease(ctx.aid, self.rid, LEASE)
            await asyncio.sleep(POLL)

    def _resolve(self, ids: list[str]) -> tuple[list[str], list[str], list[tuple[str, str]]]:
        done, pending, dropped = [], [], []
        for i in ids:
            n = self.g.node(i)
            if n["type"] == "spawn_request":
                if n["state"] == "dropped":
                    dropped.append((i, n["attrs"].get("why", "")))
                    continue
                if n["state"] == "queued":
                    pending.append(i)
                    continue
                i, n = n["attrs"]["agent"], self.g.node(n["attrs"]["agent"])
            (done if n["state"] == "closed" else pending).append(i)
        return done, pending, dropped

    def _exit_of(self, me: str, child: str) -> str:
        for e in self.g.edges(dst=me, type_="to"):
            p = self.g.node(e["src"])
            if p["attrs"].get("from") == child and p["attrs"].get("kind") == "exit":
                if p["state"] == "sent":
                    self.team.read(me, p["id"])
                notes = self.team.carried(p["id"])
                return (f"{child} finished ({p['attrs'].get('outcome')}): {p['content']}"
                        + "".join("\n  " + render_note(x, full=False) for x in notes))
        return f"{child} finished without an exit message"

    def _t_cancel(self, ctx: Ctx, call: P.ToolCall, id: str, why: str) -> str:
        with self.lock:
            from ..kernel import scopes

            if ctx.aid not in scopes.ancestors(self.g, id):
                raise TeamError(f"{id} is not one of your descendants")
            self.team.cancel_agent(id, why, actor="model")
        task = self.tasks.pop(id, None)
        if task is not None:
            task.cancel()
        return f"{id} cancelled"

    def _t_checkpoint(self, ctx: Ctx, call: P.ToolCall, digest: str) -> str:
        with self.lock:
            nid = self.team.note(ctx.run, ctx.aid, digest, kind="digest", pin=False)
            self.team.update_agent(ctx.aid, digest=digest)
        ctx.new_segment = digest
        return f"digest {nid} recorded; your context restarts from it"

    def _t_finish(self, ctx: Ctx, call: P.ToolCall, outcome: str, text: str, refs: list[str] | None = None) -> str:
        if outcome not in ("done", "partial", "failed"):
            raise TeamError("outcome: done, partial or failed")
        with self.lock:
            try:
                self.team.finish(ctx.aid, outcome, text, refs)
            except ScopeRefused as e:
                raise TeamError(str(e)) from e
        ctx.finished = True
        return "finished"

    def _t_lookup(self, ctx: Ctx, call: P.ToolCall, situation: str) -> str:
        from .. import render

        with self.lock:
            return render.candidates(situation, self.ws.hb.lookup(situation, 5, "all"))

    def _t_open_entry(self, ctx: Ctx, call: P.ToolCall, id: str) -> str:
        from .. import render

        with self.lock:
            return render.card(self.ws.hb.get_entry(id), self.ws.hb.neighbors(id))

    def _mail(self, ctx: Ctx) -> list[str]:
        """Unread messages to the agent, rendered and marked read (children's exits included)."""
        out = []
        for p in self.team.inbox(ctx.aid):
            self.team.read(ctx.aid, p["id"])
            notes = self.team.carried(p["id"])
            kind = "result" if p["attrs"].get("kind") == "exit" else "message"
            out.append(f"New {kind} {p['id']} from {p['attrs'].get('from')}: {p['content']}"
                       + "".join("\n  " + render_note(x, full=False) for x in notes))
        return out


def _render_step(step: P.Step, results: list[tuple[P.ToolCall, str, bool]]) -> str:
    out = [f"You said: {step.text}"] if step.text else []
    for c, text, err in results:
        out.append(f"{c.name}({json.dumps(c.args, ensure_ascii=False)[:500]}) → {'error: ' if err else ''}"
                   f"{_cut(text, 1500)}")
    return "\n".join(out)


class CrewService:
    """The crews of the runner process, on one asyncio loop in a thread of its own."""

    def __init__(self, keys: KeyStore | None, adapter_for: Callable[[Key], P.Adapter] | None = None):
        self.keys, self.adapter_for = keys, adapter_for
        self.crews: dict[str, Crew] = {}
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="rhb-crew", daemon=True)
        self.thread.start()

    def attach(self, db: str, runner: Any) -> Crew:
        crew = self.crews.get(db)
        if crew is None:
            crew = self.crews[db] = Crew(runner.ws, runner.lock, self.keys, runner=runner,
                                         adapter_for=self.adapter_for)
            asyncio.run_coroutine_threadsafe(crew.serve(), self.loop)
        return crew

    def close(self) -> None:
        async def stop() -> None:
            for c in self.crews.values():
                c.stopped = True
                for t in list(c.tasks.values()):
                    t.cancel()
                await asyncio.gather(*c.tasks.values(), return_exceptions=True)
                if c.http is not None:
                    await c.http.aclose()

        asyncio.run_coroutine_threadsafe(stop(), self.loop).result(timeout=30)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=10)
