"""Install or update the whole site from one file: `sudo deploy/install.sh [site.toml]`.

Everything the site needs is derived from the site file and the realm (portal/facts.py) and
rendered from deploy/templates: nothing on the host is named by hand. Run it again after any change
(to the code, the site file or the templates); every step is idempotent.

    users      one system user per role that runs as itself (facts.ROLES, RUNS_AS): <name>-portal,
               -sso, -apps, -handbook (the runner runs as the handbook's)
    code       the repository copied to <code> (default /opt/<name>-site); its virtualenv in .venv,
               made by `uv sync --frozen` from uv.lock with the system's Python
    site file  /etc/<name>/site.toml (the one the services read: PORTAL_SITE), and site.local.toml
               beside it when the site file has one (the host's own keys, kept out of the repository)
    units      <name>-<role>.service for every role, from deploy/templates/<role>.service
    nginx      sites-available/<domain>.conf (enabled), snippets/<name>-{proxy,apps,apps-map}.conf;
               with a `router` in [site], plain HTTP for it, and /etc/<name>/router/<domain>.conf:
               the router's side, for its admin to merge
    directory  /etc/<name>/directory/{kadm5.acl,slapd-acl.ldif}: the KDC's and slapd's side, rendered with
               this site's realm, DNs and current admins, for the directory's admin to merge
    once       /etc/<unit>/<role>.env (secrets and local overrides; never overwritten), the SSO's token
               key pair, the handbook's agent key pair
    then       nginx -t, daemon-reload, enable, restart, the sandbox check; and what only an admin can
               do (the Kerberos keytabs), with the exact commands

A host on an older layout is moved to the derived names (LEGACY): the old units are stopped and
removed, and their /etc, /var/lib and /var/log carried over; units of services the site no longer
has are removed (RETIRED); what is left behind is listed for removal.

Standard library only: it runs before the virtualenv exists.
"""

from __future__ import annotations

import argparse
import grp
import os
import pwd
import secrets
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from . import site as site_mod
from .facts import ROLES, RUNS_AS, SIGNIN, Facts, facts, local_file

REPO = Path(__file__).resolve().parents[2]  # src/portal/deploy.py
TEMPLATES = REPO / "deploy" / "templates"
USERS = tuple(r for r in ROLES if r not in RUNS_AS)  # roles that run as their own system user
# What earlier versions installed, by role: the one list of old unit names, for the move to derived ones.
LEGACY = {"portal": "ldap-portal", "handbook": "refhandbook", "runner": "refhandbook-runner"}
# Left behind by earlier versions ({name} = the site's name): listed for removal, never removed here.
LEFTOVERS = ("opt/ldap-portal", "etc/{name}-site", "opt/{name}-portal", "opt/refhandbook", "opt/refhandbook-venv",
             "opt/refhandbook-python", "etc/pam.d/refhandbook")
LEFTOVER_USERS = ("refhandbook",)
# Files an earlier version kept in a role's /etc that nothing reads any more (after the move above).
UNREAD = {"handbook": ("env", "ldap-bindpw")}
# Per-role env files (deploy/templates/<role>.env): made once, never overwritten; a secret where the
# role needs one (the services refuse one shorter than 32).
ENV_FILES = {"portal": "PORTAL_SESSION_SECRET", "sso": "PORTAL_SSO_SECRET", "handbook": None}
# Units of services the site no longer runs ({unit} = a derived name): stopped and removed.
RETIRED = ("dav-homes.service", "dav-homes.timer", "{name}-dav-homes.service", "{name}-dav-homes.timer")
SKIP = {".git", ".venv", "__pycache__", ".pytest_cache", "ldap_portal.egg-info", "node_modules", "dist"}  # (apps publish their builds with --app)

Run = Callable[[list[str]], int]


# units besides the roles': root's, with no user or port of their own (<name>-<unit>)
HELPERS = ("mounts.service", "mounts.timer")

# [site] keys the router's side takes (site.local.toml: they are this host's); unset, a placeholder
ROUTER_KEYS = {"router_address": "<this host's address as the router reaches it>",
               "router_cert": "<the certificate's fullchain.pem on the router>",
               "router_key": "<its privkey.pem on the router>"}


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.run(cmd).returncode


# ── rendering: pure, into any root ──────────────────────────────────────


def rendered(f: Facts, site_file: Path) -> dict[str, tuple[str, int]]:
    """Every generated file: absolute path → (content, mode)."""
    site = site_mod.load(site_file, f)
    extra = {"generated": f"Generated from {f.site_file} by portal/deploy.py: edit that and rerun the installer.",
             "aliases_sp": "".join(f" {a}" for a in f.aliases), "port": str(f.listen), "signin": SIGNIN,
             "sso_public_key": f"{f.conf_dir('sso')}/sso-public.pem",
             "handbook_audience": _audience(site, f, "handbook")} | _front(f)
    admin_group = os.environ.get("PORTAL_ADMIN_GROUP", "admin")
    admins = _admins(admin_group)
    extra |= {"admin_group": admin_group,
              "admin_lines": "\n".join(f"portal/service@{f.realm}  ADMCILSP  {p}@{f.realm}"
                                       for u in admins for p in (f"{u}/user", u))
              or f"# (no members of {admin_group} were found when this was rendered)",
              "kdc_dn": _kdc_conf("ldap_kdc_dn") or "<ldap_kdc_dn of kdc.conf>",
              "kadmin_dn": _kdc_conf("ldap_kadmind_dn") or "<ldap_kadmind_dn of kdc.conf>",
              "portal_dn": "<the DN ldapwhoami prints for portal/service>"}
    extra |= {k: f.extra.get(k, default) for k, default in ROUTER_KEYS.items()}

    def t(name: str) -> str:
        return f.substitute((TEMPLATES / name).read_text(), extra)

    out = {
        **{f"/etc/systemd/system/{f.unit(role)}.service": (t(f"{role}.service"), 0o644) for role in ROLES},
        **{f"/etc/systemd/system/{f.name}-{h}": (t(h), 0o644) for h in HELPERS},
        f"/etc/nginx/sites-available/{f.domain}.conf": (t("site.conf"), 0o644),
        f"/etc/nginx/snippets/{f.name}-proxy.conf": (t("proxy.conf"), 0o644),
        f"/etc/nginx/snippets/{f.name}-apps-map.conf": (site_mod.render_map(site, f.name), 0o644),
        f"/etc/nginx/snippets/{f.name}-apps.conf": (site_mod.render_locations(site, f.name), 0o644),
        f.site_file: (site_file.read_text(), 0o644),
        **({str(local_file(f.site_file)): (local_file(site_file).read_text(), 0o644)}
           if local_file(site_file).exists() else {}),
        # the directory's side, applied by its admin on the KDC and the LDAP server (printed at the end)
        f"/etc/{f.name}/directory/kadm5.acl": (t("kadm5.acl"), 0o644),
        f"/etc/{f.name}/directory/slapd-acl.ldif": (t("slapd-acl.ldif"), 0o644),
    }
    if f.router:
        out[f"/etc/{f.name}/router/{f.domain}.conf"] = (t("router.conf"), 0o644)
    return out


def _audience(site, f: Facts, role: str) -> str:  # noqa: ANN001 — site: portal.site.Site
    """The audience the sign-in mints for `role`'s backend: that of the site file's apps whose routes
    reach it. They must agree (the backend checks one); with none, the role's name."""
    found = {a.audience for a in site.apps if a.audience
             and f.upstream(role) in {a.upstream, *(r.upstream for r in a.routes)}}
    if len(found) > 1:
        raise site_mod.SiteError(f"the apps that reach {role} ({f.upstream(role)}) disagree on its audience: "
                                 f"{sorted(found)}")
    return found.pop() if found else role  # no app reaches it: nginx routes nothing there


def _front(f: Facts) -> dict[str, str]:
    """What differs between nginx holding the certificate and a router in front that does: the
    http-level lines before the site's server block (`front`) and its listen lines (`listen`)."""
    if not f.router:
        return {"front": f"server {{\n    listen 80;\n    server_name {f.domain}{''.join(f' {a}' for a in f.aliases)};\n"
                         f"    return 301 https://{f.domain}$request_uri;\n}}\n",
                "listen": f"    listen 443 ssl;\n    http2 on;\n"
                          f"    ssl_certificate     /etc/letsencrypt/live/{f.domain}/fullchain.pem;\n"
                          f"    ssl_certificate_key /etc/letsencrypt/live/{f.domain}/privkey.pem;\n"
                          f"    ssl_protocols TLSv1.2 TLSv1.3;"}
    var = f"${f.name.replace('-', '_')}_via_router"
    front = [f"# TLS ends at the router ({', '.join(f.router)}): it alone may connect, and the client is",
             "# the address it puts in X-Forwarded-For (the limits and the audit log key on it).",
             f"geo $realip_remote_addr {var} {{", "    default 0;", "    127.0.0.1 1;", "    ::1 1;",
             *[f"    {net} 1;" for net in f.router], "}"]
    if f.aliases:
        front += ["server {", f"    listen {f.listen};", f"    server_name {' '.join(f.aliases)};",
                  f"    return 301 https://{f.domain}$request_uri;", "}"]
    listen = [f"    listen {f.listen};", *[f"    set_real_ip_from {net};" for net in f.router],
              "    real_ip_header X-Forwarded-For;", f"    if ({var} = 0) {{ return 403; }}"]
    return {"front": "\n".join(front) + "\n", "listen": "\n".join(listen)}


def _admins(group: str) -> list[str]:
    try:
        return sorted(grp.getgrnam(group).gr_mem)
    except KeyError:
        return []


def _kdc_conf(key: str, path: str = "/etc/krb5kdc/kdc.conf") -> str:
    try:
        for line in Path(path).read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip()
    except OSError:
        pass
    return ""


def write_rendered(files: dict[str, tuple[str, int]], root: Path) -> None:
    for path, (content, mode) in files.items():
        p = root / path.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".new")
        tmp.write_text(content)
        tmp.chmod(mode)
        tmp.replace(p)


# ── installing ───────────────────────────────────────────────────────────


def _ids(user: str) -> tuple[int, int]:
    try:
        return pwd.getpwnam(user).pw_uid, grp.getgrnam(user).gr_gid
    except KeyError:
        return -1, -1


def _chown(p: Path, user: str, real: bool) -> None:
    uid, gid = _ids(user)
    if real and uid >= 0:
        os.chown(p, 0, gid)


def _sync_code(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    dst.mkdir(parents=True, exist_ok=True)
    keep = set()
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        rel = Path(dirpath).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        keep.add(rel)
        for name in filenames:
            shutil.copy2(Path(dirpath) / name, dst / rel / name)
            keep.add(rel / name)
    for dirpath, dirnames, filenames in os.walk(dst, topdown=False):  # files the repository no longer has
        rel = Path(dirpath).relative_to(dst)
        if rel.parts and rel.parts[0] in SKIP:
            continue
        for name in filenames:
            if rel / name not in keep and not any(part in SKIP for part in (rel / name).parts):
                (dst / rel / name).unlink()


def _migrate(f: Facts, root: Path, sh: Run, notes: list[str]) -> None:
    """Move a host from the old fixed names to the derived ones, and retire what the site dropped."""
    units = root / "etc/systemd/system"
    for name in RETIRED:
        u = units / name.format(name=f.name)
        if u.exists():
            sh(["systemctl", "disable", "--now", u.name])
            u.unlink()
            notes.append(f"unit {u.name} removed (the site no longer serves WebDAV; its files stay where they are)")
    for role, old in LEGACY.items():
        new = f.unit(role)
        if old == new:
            continue
        found = [u for u in (units / f"{old}.service", units / f"{old}.timer") if u.exists()]
        if not found:
            continue
        for u in found:
            sh(["systemctl", "disable", "--now", u.name])
            u.unlink()
        for base in ("etc", "var/lib", "var/log"):
            a, b = root / base / old, root / base / new
            if a.is_dir() and not b.exists():
                shutil.move(str(a), str(b))
                notes.append(f"moved /{base}/{old} to /{base}/{new}")
        for env in (root / "etc" / new).glob("*.env"):  # paths the old env file spelled out move with it
            text = env.read_text()
            moved = text
            for base in ("etc", "var/lib", "var/log"):
                moved = moved.replace(f"/{base}/{old}/", f"/{base}/{new}/")
            if moved != text:
                env.write_text(moved)
                notes.append(f"{env.relative_to(root)}: paths under {old} now under {new}")
        notes.append(f"unit {old} replaced by {new}")
        for name in UNREAD.get(role, ()):
            if (root / "etc" / new / name).exists():
                notes.append(f"/etc/{new}/{name} is not read any more: carry any override you need into "
                             f"/etc/{new}/{role}.env (its settings now come from the site's facts), then remove it")
    for leftover in LEFTOVERS:
        path = leftover.format(name=f.name)
        if (root / path).exists() and path != f.code.lstrip("/"):
            notes.append(f"/{path} is no longer used: remove it when the new units run")
    for user in LEFTOVER_USERS:
        if _ids(user)[0] >= 0 and user not in {f.user(r) for r in ROLES}:
            notes.append(f"the system user {user} is no longer used: userdel {user} when the new units run")


def _fill_secret(env: Path, key: str) -> bool:
    """Give `key` a fresh value if the file has it empty or too short (the service would not start);
    a good one, or one read from a file (<key>_FILE), is left alone."""
    lines = env.read_text().splitlines()
    if any(ln.startswith(f"{key}_FILE=") and ln.split("=", 1)[1].strip() for ln in lines):
        return False
    found = [i for i, ln in enumerate(lines) if ln.startswith(f"{key}=")]
    if found and len(lines[found[-1]].split("=", 1)[1].strip()) >= 32:
        return False
    line = f"{key}={secrets.token_urlsafe(48)}"
    if found:
        lines[found[-1]] = line
    else:
        lines.append(line)
    env.write_text("\n".join(lines) + "\n")
    return True


def _key_pair(module: str, directory: Path, private: str, public: str, sh: Run, python: Path, notes: list[str],
              owner: tuple[int, int] | None) -> None:
    """A key pair made once by `python -m <module> ... <directory>` (portal.tokens, the agent keys); the
    private half 0400 (owned by `owner`, else root's), the public half 0644."""
    if not (directory / private).exists():
        verb = "genkey" if module == "portal.tokens" else "gen"
        if sh([str(python), "-m", module, verb, str(directory)]) == 0:
            notes.append(f"made the key pair {private}, {public} in /{directory.relative_to(directory.anchor)}")
        else:
            notes.append(f"could not make {private} in {directory}: rerun the installer")
    if (directory / private).exists():
        if owner is not None:
            os.chown(directory / private, *owner)
        (directory / private).chmod(0o400)
    if (directory / public).exists():
        (directory / public).chmod(0o644)


def _secrets(f: Facts, root: Path, sh: Run, real: bool, notes: list[str]) -> None:
    """The files made once: each role's env file (with its secret), the SSO's token keys, the agent keys."""
    for role, secret_key in ENV_FILES.items():
        d = root / "etc" / f.unit(role)
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o755)  # as systemd keeps a ConfigurationDirectory: the secrets carry their own modes
        env = d / f"{role}.env"
        if not env.exists():
            env.write_text(f.substitute((TEMPLATES / f"{role}.env").read_text(), {"secret": secrets.token_urlsafe(48)}))
            notes.append(f"made {env.relative_to(root)}" + (" with a fresh secret" if secret_key else ""))
        elif secret_key and _fill_secret(env, secret_key):  # a hand-made file with the secret left empty
            notes.append(f"{env.relative_to(root)}: {secret_key} was empty or short, now a fresh secret")
        env.chmod(0o640)  # every time: a file made by hand may have been left world-readable
        _chown(env, f.user(role), real)
    python = root / f.code.lstrip("/") / ".venv/bin/python"
    sso_ids = _ids(f.user("sso"))
    _key_pair("portal.tokens", root / "etc" / f.unit("sso"), "sso-signing.pem", "sso-public.pem", sh, python, notes,
              sso_ids if real and sso_ids[0] >= 0 else None)  # the SSO signs; every backend reads the public half
    # the runner's credential (LoadCredential reads it as root); the server holds the public half
    _key_pair("refhandbook.agents.keys", root / "etc" / f.unit("handbook"), "agent-keys", "agent-keys.pub", sh,
              python, notes, None)


def _admin_principal(f: Facts) -> str:
    out = subprocess.run(["klist"], capture_output=True, text=True) if shutil.which("klist") else None
    for line in (out.stdout.splitlines() if out and out.returncode == 0 else []):
        if line.startswith("Default principal:"):
            return line.split(":", 1)[1].strip()
    return f"<your-admin>/admin@{f.realm}"


def _keytabs(f: Facts, root: Path) -> list[str]:
    """What only an admin can do: the keytabs, with the exact commands. The HTTP key goes to the SSO
    alone (the installed portal runs behind it and never checks a password): each ktadd makes a new
    key, so extracting it a second time elsewhere would break the first copy."""
    todo, admin = [], _admin_principal(f)
    host = f.domain
    need = [(f.unit("portal"), "portal.keytab", f"portal/service@{f.realm}", "the portal's kadmin identity"),
            (f.unit("sso"), "http.keytab", f"HTTP/{host}@{f.realm}", "proves the KDC on the site sign-in")]
    for unit, name, princ, why in need:
        p = root / "etc" / unit / name
        if not p.exists():
            todo.append(f"# {why}\nkadmin -p {admin} -q 'ktadd -k /etc/{unit}/{name} {princ}' "
                        f"&& chown root:{unit} /etc/{unit}/{name} && chmod 0440 /etc/{unit}/{name}")
    return todo


def _sync_venv(code: Path, venv: Path, sh: Run) -> int:
    """The virtualenv from uv.lock (`uv sync --frozen`), with the Python this installer runs on (the
    system's: the service users can reach it). python-gssapi builds against the Kerberos headers; they
    are installed and the sync retried once if it fails where apt-get exists."""
    uv = shutil.which("uv")
    if uv is None:
        print("uv is required (https://docs.astral.sh/uv/): install it, then rerun", file=sys.stderr)
        return 1
    sync = ["env", f"UV_PROJECT_ENVIRONMENT={venv}", "UV_PYTHON_DOWNLOADS=never", uv, "sync", "--frozen", "--no-dev",
            "--extra", "kerberos", "--project", str(code), "--python", sys.executable]
    if sh(sync) == 0:
        return 0
    if shutil.which("apt-get"):
        sh(["apt-get", "install", "-y", "-q", "libkrb5-dev", "gcc"])
        if sh(sync) == 0:
            return 0
    print("uv could not build the virtualenv (see above; the Kerberos headers, libkrb5-dev or krb5-devel, and a "
          "C compiler are needed): the units were not touched", file=sys.stderr)
    return 1


def install(site_file: Path, root: Path = Path("/"), sh: Run = _run, src: Path = REPO) -> int:
    real = root == Path("/")
    if real and os.geteuid() != 0:
        print("run as root: sudo deploy/install.sh", file=sys.stderr)
        return 1
    f = facts(str(site_file))
    notes: list[str] = []
    print(f"site {f.name}: realm {f.realm}, domain {f.domain}, code {f.code}")
    _migrate(f, root, sh, notes)
    for role in USERS:
        if _ids(f.user(role))[0] < 0:
            sh(["useradd", "--system", "--no-create-home", "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin",
                f.user(role)])
    code = root / f.code.lstrip("/")
    _sync_code(src, code)
    venv = code / ".venv"
    if _sync_venv(code, venv, sh) != 0:
        return 1
    write_rendered(rendered(f, site_file), root)
    (root / f.apps_root.lstrip("/")).mkdir(parents=True, exist_ok=True)
    if not local_file(site_file).exists():  # dropped from the source: the installed copy goes too
        (root / str(local_file(f.site_file)).lstrip("/")).unlink(missing_ok=True)
    enabled = root / "etc/nginx/sites-enabled" / f"{f.domain}.conf"
    enabled.parent.mkdir(parents=True, exist_ok=True)
    if not enabled.is_symlink():
        enabled.unlink(missing_ok=True)
        enabled.symlink_to(f"../sites-available/{f.domain}.conf")
    _secrets(f, root, sh, real, notes)
    if shutil.which("nginx") and sh(["nginx", "-t"]) != 0:
        print("nginx -t failed: nothing restarted", file=sys.stderr)
        return 1
    units = [f"{f.unit(role)}.service" for role in ROLES]
    sh(["systemctl", "daemon-reload"])
    # the mounts first: the handbook's units see the staged directories from their start
    sh(["systemctl", "enable", "--now", f"{f.name}-mounts.timer"])
    sh(["systemctl", "enable", f"{f.name}-mounts.service"])
    sh(["systemctl", "restart", f"{f.name}-mounts.service"])
    sh(["systemctl", "enable", *units])
    sh(["systemctl", "restart", *units])
    sh(["systemctl", "reload", "nginx"])
    if sh([str(venv / "bin/refhandbook"), "sandbox-check"]) != 0:
        notes.append(f"the handbook's sandbox is not fully available here (above): {f.unit('runner')} needs user "
                     "namespaces and seccomp")
    for n in notes:
        print("·", n)
    print(f"\nThe directory's side, for its admin to merge (on the KDC, and the LDAP server):\n"
          f"  /etc/{f.name}/directory/kadm5.acl       into /etc/krb5kdc/kadm5.acl, then restart krb5-admin-server\n"
          f"  /etc/{f.name}/directory/slapd-acl.ldif  merge with the current olcAccess (instructions inside)")
    if f.router:
        print(f"\nThe router's side, for its admin to merge (TLS ends there; this host serves plain HTTP on "
              f":{f.listen} to {', '.join(f.router)} only):\n  /etc/{f.name}/router/{f.domain}.conf")
        unset = [k for k in ROUTER_KEYS if k not in f.extra]
        if unset:
            print(f"  still placeholders in it: set {', '.join(unset)} in [site] of {local_file(f.site_file)}")
    print(f"\nThe handbook's shared layers (Python, Node, Rust; uses the network once):\n"
          f"  sudo -u {f.user('handbook')} {venv}/bin/refhandbook layers build --data-dir /var/lib/{f.unit('handbook')}")
    todo = _keytabs(f, root)
    if todo:
        print("\nOnly an admin can do these (then: systemctl restart "
              f"{f.unit('portal')} {f.unit('sso')}):\n\n" + "\n\n".join(todo))
    return 0


def install_app(f: Facts, site_file: Path, app_id: str, dist: Path, root: Path = Path("/")) -> int:
    """Publish an app's built files (its `dist`) at /apps/<id>/: copied into <apps_root>/<id>, replacing
    what was there. The app must be in the site file with `static = true`."""
    app = next((a for a in site_mod.load(site_file, f).apps if a.id == app_id), None)
    if app is None or app.static is not True:
        print(f"{app_id}: no app with `static = true` in {site_file}", file=sys.stderr)
        return 1
    if not (dist / "index.html").is_file():
        print(f"{dist}: no index.html (build the app first)", file=sys.stderr)
        return 1
    target = root / f.apps_root.lstrip("/") / app_id
    new = target.with_name(f".{app_id}.new")
    shutil.rmtree(new, ignore_errors=True)
    shutil.copytree(dist, new)
    for p in [new, *new.rglob("*")]:
        p.chmod(0o755 if p.is_dir() else 0o644)  # nginx's to read, whatever the build left
    old = target.with_name(f".{app_id}.old")
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    new.rename(target)
    shutil.rmtree(old, ignore_errors=True)
    print(f"published {dist} at /apps/{app_id}/ ({target})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deploy/install.sh", description=__doc__.split("\n")[0])
    p.add_argument("site", nargs="?", default=str(REPO / "deploy" / "site.toml"))
    p.add_argument("--render-into", metavar="DIR", help="only render every file under DIR (nothing installed)")
    p.add_argument("--check", action="store_true", help="print the derived facts and the services, and exit")
    p.add_argument("--app", nargs=2, metavar=("ID", "DIST"),
                   help="publish an app's built files at /apps/ID/ (an app of the site file with static = true)")
    a = p.parse_args(argv)
    site_file = Path(a.site)
    f = facts(str(site_file))
    if a.check:
        for k in ("realm", "name", "domain", "base_dn", "users_ou", "groups_ou", "ldap_uri", "issuer", "http_service",
                  "code"):
            print(f"{k:13} {getattr(f, k)}")
        print(f"{'tls':13} " + (f"at the router ({', '.join(f.router)}), plain HTTP on :{f.listen}" if f.router
                                 else f"nginx (/etc/letsencrypt/live/{f.domain})"))
        for role in ROLES:
            print(f"{'unit':13} {f.unit(role)}")
        for app in site_mod.load(site_file, f).apps:
            print(f"{'app':13} {app.id} ({app.audience or '-'}, {len(app.routes)} routes)")
        return 0
    if a.app:
        if os.geteuid() != 0:
            print("run as root: sudo deploy/install.sh --app ID DIST", file=sys.stderr)
            return 1
        return install_app(f, site_file, a.app[0], Path(a.app[1]))
    if a.render_into:
        write_rendered(rendered(f, site_file), Path(a.render_into))
        print(f"rendered into {a.render_into}")
        return 0
    return install(site_file)


if __name__ == "__main__":
    sys.exit(main())
