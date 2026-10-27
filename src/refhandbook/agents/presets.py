"""Presets and schedules: runs the user keeps ready, and when they run by themselves.

A preset is a goal and a grant (routes, limits, pruning, sandbox policy), checked as a grant is when
it is saved. A schedule names a preset and a cron expression (agents/cron.py). Both are the user's:
written only from the pages (actor `user`); the model can list presets and ask for a run from one,
which still waits for the user's approval.

A schedule is the user's approval given ahead of time: when it falls due, the runner opens the run and
writes its grant as the user, as the page does. It does not start a run while the previous one it
started is still going (that firing is recorded as skipped), and after a stop it fires once, not once
per missed time. The store has a marker, <db>.sandbox/schedules, while any schedule is enabled, so the
runner opens the store without one being asked for.

An input or a block's command may name {date}, {time} and {datetime}: a scheduled run says when it ran.
"""

from __future__ import annotations

import datetime as dt
import re
import secrets
import time
from typing import Any

from ..kernel.graph import Graph
from . import cron, flows, package
from .flows import fill  # noqa: F401 — the tools' import
from .team import Team, TeamError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
U = "user"


def _now() -> float:
    return round(time.time(), 3)


class Presets:
    def __init__(self, g: Graph, marker: Any = None):
        """`marker`: the schedules marker file (a Path); kept present while a schedule is enabled."""
        self.g = g
        self.marker = marker
        package.install(g)
        self._migrate()

    def _migrate(self) -> None:
        """A preset kept before flows (a goal and a routing table) becomes a flow of one team block told
        that goal, so every preset opens in the flow editor and runs the same way."""
        for p in self.list():
            a = p["attrs"]
            if a.get("flow"):
                continue
            flow = flows.from_grant(p["content"], a.get("grant"))
            try:
                flow = flows.check(flow)
                grant = flows.fit(a.get("grant") or {}, flow)
            except TeamError:
                grant = a.get("grant")  # no usable route: the editor shows the block to finish
            self.g.update_node(p["id"], actor=U, content="", attrs={"flow": flow, "grant": grant})

    # ── presets ──────────────────────────────────────────────────────────

    def save(self, name: str, goal: str, grant: dict[str, Any], *, title: str = "", actor: str = U,
             flow: dict[str, Any] | None = None) -> dict[str, Any]:
        """Keep a preset; with a flow (agents/flows.py), a flow preset: its routing the blocks' keys and
        models, the grant raised to what the flow needs, and the goal (the flow's input) optional."""
        if actor != U:
            raise TeamError("only the user saves a preset (on the page)")
        name = name.strip().lower()
        if not NAME_RE.match(name):
            raise TeamError("preset name: lowercase letters, digits, . _ - (up to 48)")
        if flow is None:  # a goal and a routing table: one team block told the goal, with no input
            if not goal.strip():
                raise TeamError("a preset needs a goal")
            flow, goal = flows.from_grant(goal, grant), ""
        flow = flows.check(flow)
        cfg = flows.fit(grant, flow)
        nid = f"preset:{name}"
        attrs = {"name": name, "title": title.strip() or (goal.strip() or name).splitlines()[0][:80], "grant": cfg,
                 "flow": flow, "saved": _now()}
        if self.g.get_node(nid) is None:
            self.g.put_node(nid, "preset", actor=U, content=goal.strip(), attrs=attrs)
        else:
            self.g.update_node(nid, actor=U, content=goal.strip(), attrs=attrs)
        return self.g.node(nid)

    def get(self, name: str) -> dict[str, Any]:
        n = self.g.get_node(f"preset:{name}")
        if n is None or n["type"] != "preset" or n["author"] != U:
            raise TeamError(f"no preset {name!r}; presets: {', '.join(p['attrs']['name'] for p in self.list()) or 'none'}")
        return n

    def list(self) -> list[dict[str, Any]]:
        return [self.g.node(r[0]) for r in self.g.db.execute(
            "SELECT id FROM k_nodes WHERE type = 'preset' AND author = 'user' ORDER BY id")]

    def delete(self, name: str, *, actor: str = U) -> None:
        if actor != U:
            raise TeamError("only the user deletes a preset")
        self.get(name)
        with self.g.tx():
            for s in self.schedules(name):
                self.g.delete_node(s["id"], actor=U)
            self.g.delete_node(f"preset:{name}", actor=U)
        self._mark()

    def start(self, name: str, *, at: dt.datetime | None = None, actor: str = U, **attrs: Any) -> str:
        """Open a run from the preset and approve it with its grant, as the user (the page's 지금 실행,
        or a schedule the user made). Returns the run."""
        if actor != U:
            raise TeamError("only the user starts a run from a preset; the model asks with agent_run")
        p = self.get(name)
        at = at or dt.datetime.now()
        a = p["attrs"]
        return Team(self.g).begin(fill(p["content"], at), a["grant"], title=f"{a['title']} · {at:%m-%d %H:%M}",
                                  flow=a.get("flow"), at=at, actor=U, preset=name, **attrs)

    # ── schedules ────────────────────────────────────────────────────────

    def schedule(self, preset: str, expr: str, *, actor: str = U, now: dt.datetime | None = None) -> dict[str, Any]:
        if actor != U:
            raise TeamError("only the user schedules a preset (on the page)")
        self.get(preset)
        try:
            c = cron.parse(expr)
        except cron.CronError as e:
            raise TeamError(f"schedule: {e}") from e
        sid = f"schedule:{secrets.token_hex(4)}"
        self.g.put_node(sid, "schedule", actor=U, content=c.text, attrs={
            "preset": preset, "cron": c.text, "enabled": True,
            "next_at": c.next_after(now or dt.datetime.now()).timestamp(), "created": _now()})
        self._mark()
        return self.g.node(sid)

    def schedules(self, preset: str | None = None) -> list[dict[str, Any]]:
        out = [self.g.node(r[0]) for r in self.g.db.execute(
            "SELECT id FROM k_nodes WHERE type = 'schedule' AND author = 'user' ORDER BY id")]
        return [s for s in out if preset is None or s["attrs"]["preset"] == preset]

    def _schedule(self, sid: str) -> dict[str, Any]:
        n = self.g.get_node(sid)
        if n is None or n["type"] != "schedule" or n["author"] != U:
            raise TeamError(f"no schedule {sid!r}")
        return n

    def set_enabled(self, sid: str, enabled: bool, *, actor: str = U, now: dt.datetime | None = None) -> None:
        if actor != U:
            raise TeamError("only the user turns a schedule on or off")
        s = self._schedule(sid)
        attrs: dict[str, Any] = {"enabled": enabled}
        if enabled:  # from now on: what was missed while it was off is not made up
            attrs["next_at"] = cron.parse(s["attrs"]["cron"]).next_after(now or dt.datetime.now()).timestamp()
        self.g.update_node(sid, actor=U, attrs=attrs)
        self._mark()

    def unschedule(self, sid: str, *, actor: str = U) -> None:
        if actor != U:
            raise TeamError("only the user removes a schedule")
        self._schedule(sid)
        self.g.delete_node(sid, actor=U)
        self._mark()

    def due(self, now: dt.datetime | None = None) -> list[str]:
        """Fire every enabled schedule that is due (the runner, about once a second). Returns the runs
        it started. A firing whose previous run is still going is skipped; a failing one is recorded."""
        now = now or dt.datetime.now()
        started = []
        for s in self.schedules():
            a = s["attrs"]
            if not a.get("enabled") or float(a.get("next_at") or 0) > now.timestamp():
                continue
            nxt = cron.parse(a["cron"]).next_after(now).timestamp()  # after a stop: once, then on time
            last = self.g.get_node(a["last_run"]) if a.get("last_run") else None
            if last is not None and last["state"] == "open":
                self.g.update_node(s["id"], actor="kernel", attrs={
                    "next_at": nxt, "skipped": int(a.get("skipped", 0)) + 1,
                    "last_note": f"{now:%Y-%m-%d %H:%M} skipped: {a['last_run']} was still running"})
                continue
            try:
                run = self.start(a["preset"], at=now, actor=U, schedule=s["id"])
            except TeamError as e:
                self.g.update_node(s["id"], actor="kernel", attrs={
                    "next_at": nxt, "last_note": f"{now:%Y-%m-%d %H:%M} failed: {e}"})
                continue
            self.g.update_node(s["id"], actor="kernel", attrs={
                "next_at": nxt, "last_run": run, "last_at": now.timestamp(), "last_note": ""})
            started.append(run)
        return started

    def _mark(self) -> None:
        if self.marker is None:
            return
        if any(s["attrs"].get("enabled") for s in self.schedules()):
            self.marker.parent.mkdir(parents=True, exist_ok=True)
            self.marker.touch()
        else:
            self.marker.unlink(missing_ok=True)
