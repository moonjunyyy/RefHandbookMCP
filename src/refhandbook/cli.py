from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from importlib import resources
from pathlib import Path

from . import render
from .store import Handbook, HandbookError, default_db_path


def load_env_file(path: str) -> None:
    """systemd EnvironmentFile syntax: KEY=VALUE per line, # comments, optional quotes; later lines win."""
    import os

    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        os.environ[k.strip()] = v


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="refhandbook", description="Quick reference handbook MCP server.")
    parser.add_argument("--env-file", help="read KEY=VALUE settings from this file first (systemd EnvironmentFile syntax)")
    parser.add_argument("--db", help="database file (default: $REFHANDBOOK_DB or ~/.refhandbook/handbook.db)")
    sub = parser.add_subparsers(dest="command")
    sv = sub.add_parser("serve", help="run the MCP server on stdio (default), or --http for remote mode")
    sv.add_argument("--http", action="store_true",
                    help="Streamable HTTP with OAuth sign-in against LDAP; configured by RHB_* environment variables")
    sub.add_parser("nslcd-env", help="remote mode: print RHB_LDAP_* settings from an nslcd.conf").add_argument(
        "file", nargs="?", default="/etc/nslcd.conf")
    sub.add_parser("check-login", help="remote mode: test a directory sign-in with the RHB_* settings").add_argument("user")
    pj = sub.add_parser("plugin-json", help="print .claude-plugin/plugin.json for a remote server")
    pj.add_argument("url", help="the server's MCP URL, e.g. https://hb.example.org/mcp")
    pj.add_argument("--write", metavar="PLUGIN_JSON", help="write it to this file instead of printing")
    sub.add_parser("seed", help="load the bundled example entries")
    sub.add_parser("audit", help="check the handbook; exit 1 if there are errors")
    sub.add_parser("index", help="list every entry")
    lk = sub.add_parser("lookup", help="find entries for a situation")
    lk.add_argument("situation", nargs="+")
    lk.add_argument("--scope", choices=["handbook", "research", "all"], default="all")
    sub.add_parser("show", help="print one entry").add_argument("id")
    sub.add_parser("export", help="write the handbook as JSON").add_argument("file", nargs="?", default="-")
    sub.add_parser("import", help="load entries from JSON").add_argument("file")
    rp = sub.add_parser("research", help="call a research tool with JSON arguments (the MCP fallback)")
    rp.add_argument("tool", help="e.g. research_begin; 'list' prints the tools")
    rp.add_argument("arguments", nargs="?", default="{}",
                    help="JSON object of the tool's arguments, @FILE for a JSON file, or - for stdin")
    ap = sub.add_parser("approve", help="the user's channel: approve a proposed rule or type (see `proposals`)")
    ap.add_argument("what", choices=["rule", "type"])
    ap.add_argument("name")
    ap.add_argument("--seen", required=True, metavar="APPROVAL",
                    help="the approval hash `proposals` showed (8+ hex digits): it names the proposal and the "
                         "rules it retires, so anything changed since is not approved")
    sub.add_parser("proposals", help="list the model's open rule proposals")
    po = sub.add_parser("policy", help="the user's channel: show or grant a sandbox policy")
    po.add_argument("name", nargs="?", default="")
    po.add_argument("--commands", help="space-separated commands the sandbox shows (replaces the list)")
    po.add_argument("--add", help="space-separated commands to add")
    po.add_argument("--network", choices=["on", "off"])
    for k in ("timeout", "memory_mb", "disk_mb", "tmp_mb", "concurrent"):
        po.add_argument(f"--{k.replace('_', '-')}", type=int)
    po.add_argument("--cpus", type=float)
    po.add_argument("--description")
    po.add_argument("--ports", help="space-separated TCP ports the network may reach ('any': every port)")
    po.add_argument("--layers", help="space-separated layers stacked on the base (replaces the list)")
    po.add_argument("--mount", action="append", metavar="SOURCE:TARGET[:rw]",
                    help="mount the user's data (under RHB_SANDBOX_MOUNT_ROOTS) at TARGET; repeat; 'none' clears")
    cp = sub.add_parser("cap", help="the user's channel: capability records (list, show, history, approve, reject, "
                                    "review, add, update, remove, restore)")
    cp.add_argument("action", choices=["list", "show", "history", "approve", "reject", "review", "add", "update",
                                       "remove", "restore", "kinds"])
    cp.add_argument("kind", nargs="?", default="")
    cp.add_argument("name", nargs="?", default="")
    cp.add_argument("--version", type=int, default=0, help="the version to approve, reject or restore")
    cp.add_argument("--spec", help="JSON object: the record's spec (add, update)")
    cp.add_argument("--body-file", help="a file holding the body (a script's or a layer build's)")
    cp.add_argument("--why", default="")
    rn = sub.add_parser("runner", help="run sandbox jobs: of --db, or of every store under --data-dir (remote)")
    rn.add_argument("--data-dir", help="the remote server's data directory (RHB_DATA_DIR)")
    rn.add_argument("--once", action="store_true", help="start what is queued, wait for it, and exit")
    rn.add_argument("--workers", type=int, default=4)
    sub.add_parser("sandbox-check", help="report the sandbox primitives this host offers")
    sub.add_parser("reject", help="the user's channel: reject a proposed rule (the model cannot revive it)"
                   ).add_argument("name")
    ix = sub.add_parser("research-index", help="print (or --write into a SKILL.md) the research skill's abnormal index")
    ix.add_argument("--write", metavar="SKILL_MD", help="replace the generated index block in this file")
    hk = sub.add_parser("research-hook", help="Claude Code hook support: prompt | stop")
    hk.add_argument("event", choices=["prompt", "stop"])
    hk.add_argument("ledger")
    args = parser.parse_args(argv)
    if args.env_file:
        load_env_file(args.env_file)

    if args.command == "serve" and args.http:
        import logging

        from . import remote

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
        cfg = remote.Config.from_env()
        remote.build(cfg).serve()
        return 0
    if args.command == "nslcd-env":
        from .nslcd import env_from_nslcd

        lines, notes = env_from_nslcd(Path(args.file).read_text())
        print("\n".join(lines))
        for n in notes:
            print(f"# note: {n}", file=sys.stderr)
        return 0
    if args.command == "check-login":
        import getpass

        from . import remote

        cfg = remote.Config.from_env()
        try:
            password = getpass.getpass(f"password for {args.user}: ")
        except EOFError:
            print("no password given (run it in a terminal)", file=sys.stderr)
            return 2
        try:
            uid = remote.make_authenticator(cfg).authenticate(args.user, password)  # type: ignore[attr-defined]
        except remote.DirectoryUnavailable as e:
            print(f"directory unavailable: {e}", file=sys.stderr)
            return 2
        except remote.PasswordChangeRequired:
            print(f"password right, but {args.user} must change it first (expired or one-time)", file=sys.stderr)
            return 1
        print(f"ok: signed in as {uid} ({cfg.auth})" if uid else f"refused ({cfg.auth}): wrong user or password, unknown account, or not in the required group; see the log")
        return 0 if uid else 1
    if args.command == "plugin-json":
        from .manifest import dump_plugin_json

        try:
            text = dump_plugin_json(args.url)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        if args.write:
            Path(args.write).write_text(text)
            print(f"wrote {args.write}")
        else:
            print(text, end="")
        return 0
    if args.command in (None, "serve"):
        from . import server

        if args.db:
            server._handbook = Handbook(args.db)
        server.mcp.run()
        return 0

    if args.command == "sandbox-check":
        from .agents import sandbox

        rows = sandbox.check()
        for name, ok, detail in rows:
            print(f"{'ok ' if ok else 'NO '} {name}: {detail}")
        return 0 if all(ok for name, ok, _ in rows if name in ("user namespaces", "seccomp")) else 1
    if args.command == "runner":
        return _runner(args)
    hb = Handbook(args.db)
    if args.command == "policy":
        return _policy(args, hb)
    if args.command == "cap":
        return _cap(args, hb)
    if args.command in ("approve", "proposals", "reject"):
        return _approve(args, hb)
    if args.command in ("research", "research-index", "research-hook"):
        return _research(args, hb)
    if args.command in ("show", "lookup", "index"):
        from . import research

        research.ensure_cards(hb)  # the research cards are part of every handbook, as the server loads them
    try:
        if args.command == "seed":
            data = json.loads(resources.files("refhandbook").joinpath("seed.json").read_text())
            print(f"Loaded {hb.load(data)} entries into {hb.path}")
        elif args.command == "audit":
            findings = hb.audit()
            print(render.audit(findings))
            return int(any(f["level"] == "error" for f in findings))
        elif args.command == "index":
            print(render.index(hb.index()))
        elif args.command == "lookup":
            situation = " ".join(args.situation)
            print(render.candidates(situation, hb.lookup(situation, scope=args.scope)))
        elif args.command == "show":
            print(render.card(hb.get_entry(args.id), hb.neighbors(args.id)))
        elif args.command == "export":
            text = json.dumps(hb.export(), indent=2, ensure_ascii=False) + "\n"
            if args.file == "-":
                sys.stdout.write(text)
            else:
                with open(args.file, "w") as f:
                    f.write(text)
        elif args.command == "import":
            with open(args.file) as f:
                print(f"Loaded {hb.load(json.load(f))} entries into {hb.path}")
    except HandbookError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


def _arguments(spec: str) -> dict:
    """The tool's JSON arguments: inline JSON, @FILE (a JSON file), or - (stdin). An import too large
    for the command line goes as @FILE; inside it, "data_file": PATH may stand in for "data"."""
    if spec == "-":
        text = sys.stdin.read()
    elif spec.startswith("@"):
        text = Path(spec[1:]).read_text()
    else:
        text = spec
    args = json.loads(text)
    if "data_file" in args:
        args["data"] = Path(args.pop("data_file")).read_text()
    return args


def _research(args, hb: Handbook) -> int:
    from . import research, research_api

    research_api.bind(hb)
    try:
        if args.command == "research-index":
            if args.write:
                path = Path(args.write)
                path.write_text(research.sync_skill_index(path.read_text()))
                print(f"index written into {path}")
            else:
                print(research.abnormal_index())
            return 0
        if args.command == "research-hook":
            payload = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
            label = f"cc:{payload['session_id']}" if payload.get("session_id") else ""
            if args.event == "prompt":
                print(research_api.R().prompt(args.ledger, label))
                return 0
            if payload.get("stop_hook_active"):
                return 0
            # this conversation's session (the label the prompt hook gave) must be closed by the reply's end
            left = research_api.R().unfinished(args.ledger, label)
            if left:
                print(f"Research on {args.ledger!r}:\n  " + "\n  ".join(left), file=sys.stderr)
                return 2
            return 0
        if args.tool == "list":
            for name, fn in research_api.TOOLS.items():
                print(f"{name}: {(fn.__doc__ or '').strip().splitlines()[0]}")
            return 0
        fn = research_api.TOOLS.get(args.tool)
        if fn is None:
            print(f"error: unknown research tool {args.tool!r}; run 'research list'", file=sys.stderr)
            return 2
        print(fn(**_arguments(args.arguments)))
        return 0
    except (HandbookError, TypeError, json.JSONDecodeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2



def _approve(args: argparse.Namespace, hb: Handbook) -> int:
    """The terminal on the server is the user's channel (as the approval page /agents is): the one place
    a proposal becomes a rule that blocks."""
    from . import research
    r = research.Research(hb)
    if args.command == "proposals":
        print(r.proposals())
        return 0
    from .kernel import proposals

    g = r.k.g
    try:
        if args.command == "reject":
            proposals.reject(g, args.name, actor="user")
            print(f"rule {args.name} rejected")
            return 0
        if args.what == "type":
            g.approve("type", args.name, actor="user")
            retired: list[str] = []
        else:
            retired = proposals.approve(g, args.name, args.seen, actor="user")
    except HandbookError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"{args.what} {args.name} approved" + "".join(f"; {o} retired" for o in retired))
    return 0


def _policy(args: argparse.Namespace, hb: Handbook) -> int:
    """The terminal on the server is the user's channel: a policy granted here is the user's."""
    from . import cap_api
    from .agents.workspace import Workspace

    ws = Workspace(hb)
    changes: dict = {}
    if args.commands is not None:
        changes["commands"] = args.commands.split()
    if args.add:
        name = args.name or "default"
        current = ws.policy(name if name in ws.policies() else "default")["attrs"]["commands"]
        changes["commands"] = list(changes.get("commands", current)) + args.add.split()
    if args.network:
        changes["network"] = args.network == "on"
    if args.ports:
        changes["ports"] = "any" if args.ports.strip() == "any" else [int(x) for x in args.ports.split()]
    if args.layers is not None:
        changes["layers"] = args.layers.split()
    if args.mount:
        try:
            changes["mounts"] = [] if args.mount == ["none"] else [
                {"source": m.split(":")[0], "target": m.split(":")[1], "rw": m.split(":")[2:] == ["rw"]}
                for m in args.mount]
        except IndexError:
            print("error: --mount SOURCE:TARGET[:rw]", file=sys.stderr)
            return 2
    for k in ("timeout", "memory_mb", "disk_mb", "tmp_mb", "concurrent", "cpus", "description"):
        if getattr(args, k) is not None:
            changes[k] = getattr(args, k)
    try:
        if changes:
            ws.set_policy(args.name or "default", actor="user", **changes)
        print(cap_api.policy_text(ws, args.name))
    except HandbookError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _cap(args: argparse.Namespace, hb: Handbook) -> int:
    """Capability records from the server's terminal, as the user."""

    from . import cap_api

    cap_api.configure(lambda: hb, threading.RLock())
    cap_api._spaces.clear()
    ws = cap_api.W()
    caps = ws.caps
    try:
        spec = json.loads(args.spec) if args.spec else None
        body = Path(args.body_file).read_text() if args.body_file else None
        a = args.action
        if a in ("kinds", "list"):
            print(cap_api.cap(a, kind=args.kind))
        elif a == "show":
            print(cap_api._show(ws, args.kind, args.name))
        elif a == "history":
            print(cap_api.cap("history", kind=args.kind, name=args.name))
        elif a == "approve":
            print(caps.approve(args.kind, args.name, args.version, actor="user"))
        elif a == "reject":
            print(caps.reject(args.kind, args.name, args.version, actor="user"))
        elif a == "review":
            print(cap_api.cap("review", kind=args.kind or "policy", name=args.name))
        elif a == "add":
            print(caps.add(args.kind, args.name, spec=spec, body=body, actor="user")[1])
        elif a == "update":
            print(caps.update(args.kind, args.name, spec=spec, body=body, actor="user")[1])
        elif a == "remove":
            print(caps.remove(args.kind, args.name, actor="user", why=args.why))
        elif a == "restore":
            print(caps.restore(args.kind, args.name, actor="user", version=args.version or None)[1])
    except (HandbookError, json.JSONDecodeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _runner(args: argparse.Namespace) -> int:
    """Run sandbox jobs. With --data-dir, every user's store (users/<uid>.db) that has a queued job
    (a marker in users/<uid>.db.sandbox/queue/) is opened and its jobs started."""
    import signal
    import time

    from .agents.workspace import Runner, Workspace

    runners: dict[str, Runner] = {}

    def runner_for(db: str) -> Runner:
        r = runners.get(db)
        if r is None:
            r = runners[db] = Runner(Workspace(Handbook(db)), workers=args.workers)
        return r

    def stores() -> list[str]:
        if args.data_dir:
            root = Path(args.data_dir) / "users"
            out = {str(m.parent.parent)[: -len(".sandbox")] for m in root.glob("*.db.sandbox/queue/*")}
            return sorted(out | set(runners))
        return [args.db or str(default_db_path())]

    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    log = logging.getLogger("refhandbook.runner")
    while not stop["now"]:
        for db in stores():
            try:  # one store's trouble (a busy file, a bad row) never stops the others
                r = runner_for(db)
                r.reap_lost()
                r.poll()
                with r.lock:  # the capability records' TTL reviews of this store
                    if r.ws.caps.due():
                        r.ws.caps.sweep()
            except Exception:  # noqa: BLE001
                log.exception("runner: %s", db)
        if args.once:
            break
        time.sleep(0.5)
    for r in runners.values():
        r.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
