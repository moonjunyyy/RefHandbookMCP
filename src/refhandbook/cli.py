from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path

from . import render
from .store import Handbook, HandbookError


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
    ap.add_argument("--retire", metavar="RULE", action="append", default=[],
                    help="retire this rule in the same step (the one the proposal replaces)")
    sub.add_parser("proposals", help="list the model's open rule proposals")
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

    hb = Handbook(args.db)
    if args.command in ("approve", "proposals"):
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
            if args.event == "prompt":
                print(research_api.R().prompt(args.ledger))
                return 0
            payload = json.loads(sys.stdin.read() or "{}")
            if payload.get("stop_hook_active"):
                return 0
            st = research_api.R().status(args.ledger)
            if st["open"]:
                print(f"Research turn {st['turn']} on {args.ledger!r} is still open: dispose PENDING, settle U rows, "
                      "then research_end.", file=sys.stderr)
                return 2
            if st["prompts"] > st["last_closed"]:
                print(f"Prompt {st['prompts']} has no closed research turn (last closed {st['last_closed']}): "
                      f"research_begin turn={st['prompts']}, register the message, research_end.", file=sys.stderr)
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


if __name__ == "__main__":
    sys.exit(main())


def _approve(args: argparse.Namespace, hb: Handbook) -> int:
    """The terminal on the server is the user's channel (as the approval page will be): the one place
    a proposal becomes a rule that blocks."""
    from . import research
    r = research.Research(hb)
    if args.command == "proposals":
        print(r.proposals())
        return 0
    g = r.k.g
    try:
        with g.tx():
            g.approve(args.what, args.name, actor="user")
            for old in args.retire:
                g.retire_rule(old, actor="user")
    except HandbookError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"{args.what} {args.name} approved" + "".join(f"; {o} retired" for o in args.retire))
    return 0

