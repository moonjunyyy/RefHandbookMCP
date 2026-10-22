from __future__ import annotations

import argparse
import json
import logging
import os
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
    parser = argparse.ArgumentParser(prog="refhandbook", description="The reference handbook: its MCP server, "
                                     "its sandbox runner, and admin commands on a handbook database.")
    parser.add_argument("--env-file", help="read KEY=VALUE settings from this file first (systemd EnvironmentFile syntax)")
    parser.add_argument("--db", help="database file (default: $REFHANDBOOK_DB or ~/.refhandbook/handbook.db)")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the MCP server (Streamable HTTP behind the site sign-in; RHB_* settings)")
    sub.add_parser("seed", help="load the bundled example entries")
    sub.add_parser("audit", help="check the handbook; exit 1 if there are errors")
    sub.add_parser("index", help="list every entry")
    lk = sub.add_parser("lookup", help="find entries for a situation")
    lk.add_argument("situation", nargs="+")
    lk.add_argument("--scope", choices=["handbook", "research", "all"], default="all")
    sub.add_parser("show", help="print one entry").add_argument("id")
    sub.add_parser("export", help="write the handbook as JSON").add_argument("file", nargs="?", default="-")
    sub.add_parser("import", help="load entries from JSON").add_argument("file")
    rp = sub.add_parser("research", help="call a research tool with JSON arguments, on --db")
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
                    help="mount an offered directory (NAME[/sub/path] of RHB_SANDBOX_MOUNTS) at TARGET; "
                         "repeat; 'none' clears")
    ly = sub.add_parser("layers", help="the server's shared layers: build them (with the network), list them")
    ly.add_argument("action", choices=["build", "list", "recipes"])
    ly.add_argument("names", nargs="*", help="recipes to build (default: all)")
    ly.add_argument("--data-dir", help="the remote server's data directory: layers go to <dir>/layers, and every "
                                        "user's dev policy moves to the new builds")
    ly.add_argument("--root", help="where the layers go (default: next to the store, or RHB_SANDBOX_SYSTEM_LAYERS)")
    ly.add_argument("--recipes", help="a directory of recipes (recipes.toml and <name>.sh) instead of the bundled ones")
    ly.add_argument("--keep", type=int, default=2, help="builds of each layer to keep (default 2)")
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
    rn = sub.add_parser("runner", help="run sandbox jobs and agent runs: of --db, or of every store under "
                                       "--data-dir (remote)")
    rn.add_argument("--data-dir", help="the remote server's data directory (RHB_DATA_DIR)")
    rn.add_argument("--once", action="store_true", help="start what is queued, wait for it, and exit")
    rn.add_argument("--workers", type=int, default=4)
    sub.add_parser("sandbox-check", help="report the sandbox primitives this host offers")
    sub.add_parser("reject", help="the user's channel: reject a proposed rule (the model cannot revive it)"
                   ).add_argument("name")
    args = parser.parse_args(argv)
    if args.env_file:
        load_env_file(args.env_file)
    if args.command is None:
        parser.print_help()
        return 2

    if args.command == "serve":
        from . import remote

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
        cfg = remote.Config.from_env()
        remote.build(cfg).serve()
        return 0
    if args.command == "sandbox-check":
        from .agents import sandbox

        rows = sandbox.check()
        for name, ok, detail in rows:
            print(f"{'ok ' if ok else 'NO '} {name}: {detail}")
        return 0 if all(ok for name, ok, _ in rows if name in ("user namespaces", "seccomp")) else 1
    if args.command == "runner":
        return _runner(args)
    if args.command == "layers":
        return _layers(args)
    hb = Handbook(args.db)
    if args.command == "policy":
        return _policy(args, hb)
    if args.command == "cap":
        return _cap(args, hb)
    if args.command in ("approve", "proposals", "reject"):
        return _approve(args, hb)
    if args.command == "research":
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
    from . import research_api

    research_api.bind(hb)
    try:
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
    from .agents.workspace import DEFAULT_POLICY, Workspace

    ws = Workspace(hb)
    name = args.name or DEFAULT_POLICY
    changes: dict = {}
    if args.commands is not None:
        changes["commands"] = args.commands.split()
    if args.add:
        current = (ws.policy(name)["attrs"] if name in ws.policies() else ws.base_policy())["commands"]
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
            ws.set_policy(name, actor="user", **changes)
        print(cap_api.policy_text(ws, args.name))
    except HandbookError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _layers(args: argparse.Namespace) -> int:
    """The administrator's terminal: build the server's shared layers from recipes, with the host's
    network (that is the administrator's grant), and move each user's kernel-owned dev policy to
    the new builds."""
    import shutil
    import tomllib

    from .agents import layers as L
    from .agents import sandbox
    from .agents.workspace import Workspace, system_root

    recipes = Path(args.recipes) if args.recipes else Path(__file__).parent / "agents" / "recipes"
    book = tomllib.loads((recipes / "recipes.toml").read_text())
    stores = sorted((Path(args.data_dir) / "users").glob("*.db")) if args.data_dir else [Path(args.db or default_db_path())]
    root = Path(args.root) if args.root else (Path(args.data_dir) / "layers" if args.data_dir
                                               else system_root(Handbook(str(stores[0]))))
    store = L.LayerStore(root)
    if args.action == "recipes":
        for name, r in book.items():
            print(f"{name}: {r.get('description', '')}" + (f" (on {', '.join(r['parents'])})" if r.get("parents") else ""))
        return 0
    if args.action == "list":
        for lay in store.list():
            print(f"sys:{lay.name.rpartition('.v')[0]}@{lay.name.rpartition('.v')[2]}  {lay.created}  {lay.description}"
                  + (f"  (on {' '.join(lay.parents)})" if lay.parents else ""))
        return 0
    names = set(args.names or book)
    for n in names:
        if n not in book:
            print(f"error: no recipe {n!r} (recipes: {', '.join(book)})", file=sys.stderr)
            return 2

    def under(n: str) -> list[str]:
        return [p for p in book[n].get("parents", [])]

    changed = True  # what stands on a rebuilt layer is rebuilt too, so stacks stay whole
    while changed:
        changed = False
        for n in book:
            if n not in names and any(p in names for p in under(n)) and any(
                    x.name.rpartition(".v")[0] == n for x in store.list()):
                names.add(n)
                changed = True
    order: list[str] = []

    def visit(n: str) -> None:
        for p in under(n):
            visit(p)
        if n not in order:
            order.append(n)

    for n in sorted(names):
        visit(n)
    root.mkdir(parents=True, exist_ok=True)
    built: dict[str, str] = {}

    def latest(n: str) -> int:
        vs = [int(x.name.rpartition(".v")[2]) for x in store.list() if x.name.rpartition(".v")[0] == n]
        return max(vs) if vs else 0

    from .agents import egress
    from .agents.capkinds import EGRESS_PROFILES

    for n in order:
        if n not in names and latest(n):  # a parent already built: stand on its newest build
            built[n] = f"{n}.v{latest(n)}"
            continue
        r = book[n]
        d = f"{n}.v{latest(n) + 1}"
        print(f"building sys:{n}@{latest(n) + 1} …", flush=True)
        # the build reaches out as a sandbox does: through the supervisor, to the recipe's profiles only
        prof = [x for x in r.get("egress", []) if x in EGRESS_PROFILES]
        rules = egress.Rules(allow=[(h, (443,)) for x in prof for h in EGRESS_PROFILES[x][0]], names=prof)
        key = f"build-{n}-{os.getpid()}"
        sock = egress.supervisor().open(key, rules, egress.socket_root()) if prof else None
        try:
            _, code, out = store.build(
                d, (recipes / f"{n}.sh").read_text(), parents=[built[p] for p in under(n)], network=False,
                description=r.get("description", ""), timeout=float(r.get("timeout", 1800)),
                build_env={"HOME": "/tmp", **(egress.proxy_env() if sock else {})}, env=r.get("env", {}),
                extra={"binds_ro": [(str(recipes), "/recipes")] + ([(str(sock), "/run/egress")] if sock else []),
                       "egress_port": egress.PORT if sock else None})
        except (L.LayerError, sandbox.SandboxError, OSError) as e:
            print(f"error: {n}: {e}", file=sys.stderr)
            return 1
        finally:
            log = egress.supervisor().close(key) if sock else {}
        if code != 0:
            print(out[-4000:], file=sys.stderr)
            refused = [f"{q.get('host')}: {q.get('why')}" for q in log.get("requests", []) if q.get("status") == "refused"]
            if refused:
                print("egress refused: " + "; ".join(refused[-5:]), file=sys.stderr)
            print(f"error: {n}: the build exited {code}; nothing was kept", file=sys.stderr)
            return 1
        built[n] = d
        print(out.strip().splitlines()[-1] if out.strip() else "", flush=True)
    # every user's dev policy moves to the new builds (while the kernel owns it); then old builds
    # go, unless a store still pins one or a running job stacks it
    from .agents.capkinds import in_use

    keep: set[str] = set()
    for db in stores:
        try:
            ws = Workspace(Handbook(str(db)))  # opening a store brings its kernel-owned dev policy up to date
            ws.refresh_dev()
            if "dev" in ws.policies():
                print(f"{db.stem}: dev stacks {' '.join(ws.policy('dev')['attrs'].get('layers') or []) or 'nothing'}")
            keep |= {x[len("sys:"):] for x in in_use(ws.caps) if x.startswith("sys:")}
        except HandbookError as e:
            print(f"{db.stem}: dev policy not moved: {e}", file=sys.stderr)
            print("keeping every old build (a store could not be read)", file=sys.stderr)
            return 0
    for n in order:
        olds = sorted((x.name for x in store.list() if x.name.rpartition(".v")[0] == n),
                      key=lambda x: int(x.rpartition(".v")[2]))
        for old in olds[:-max(1, args.keep)]:
            if old in keep:
                continue
            try:
                store.remove(old)
            except L.LayerError:
                pass  # a newer layer stands on it
    shutil.rmtree(root / "hostetc", ignore_errors=True)  # prepared again on the next build
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


def _agent_keys(data_dir: Path):  # noqa: ANN202 — the runner's KeyStore, or None without the private key
    from .agents import keys as K

    try:
        return K.KeyStore(data_dir / "agent-keys.db", private=K.load_private())
    except (K.KeyError_, OSError, ValueError) as e:
        logging.getLogger("refhandbook.runner").warning(
            "agents cannot open API keys (%s): runs will stop at their first model call", e)
        return None


def _runner(args: argparse.Namespace) -> int:
    """Run sandbox jobs and agent runs. With --data-dir, every user's store (users/<uid>.db) that has a
    queued job (a marker in users/<uid>.db.sandbox/queue/) or an approved run (…sandbox/runs/) is
    opened; its jobs start on the job pool, its runs on the crew (agents/crew.py)."""
    import signal
    import time

    from .agents.crew import CrewService
    from .agents.workspace import Runner, Workspace

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    runners: dict[str, Runner] = {}
    crews = CrewService(_agent_keys(Path(args.data_dir) if args.data_dir
                                    else Path(args.db or default_db_path()).parent))

    def runner_for(db: str) -> Runner:
        r = runners.get(db)
        if r is None:
            r = runners[db] = Runner(Workspace(Handbook(db)), workers=args.workers)
        return r

    def stores() -> list[str]:
        if args.data_dir:
            root = Path(args.data_dir) / "users"
            out = {str(m.parent.parent)[: -len(".sandbox")] for pattern in ("*.db.sandbox/queue/*", "*.db.sandbox/runs/*")
                   for m in root.glob(pattern)}
            return sorted(out | set(runners))
        return [args.db or str(default_db_path())]

    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    log = logging.getLogger("refhandbook.runner")
    while not stop["now"]:
        for db in stores():
            try:  # one store's trouble (a busy file, a bad row) never stops the others
                r = runner_for(db)
                if (Path(f"{db}.sandbox") / "runs").is_dir():
                    crews.attach(db, r)
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
    crews.close()
    for r in runners.values():
        r.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
