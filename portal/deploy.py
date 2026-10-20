"""Install or update the whole site from one file: `sudo deploy/install.sh [site.toml]`.

Everything the site needs is derived from the site file and the realm (portal/facts.py) and
rendered from deploy/templates: nothing on the host is named by hand. Run it again after any change
(to the code, the site file or the templates); every step is idempotent.

    users      <name>-portal, <name>-sso (system users, no shell)
    code       the repository copied to <code> (default /opt/<name>-portal), its virtualenv in .venv
    site file  /etc/<name>/site.toml (the one the services read: PORTAL_SITE), and site.local.toml
               beside it when the site file has one (the host's own keys, kept out of the repository)
    units      <name>-portal, <name>-sso in /etc/systemd/system
    nginx      sites-available/<domain>.conf (enabled), snippets/<name>-{proxy,apps,apps-map}.conf;
               with a `router` in [site], plain HTTP for it, and /etc/<name>/router/<domain>.conf:
               the router's side, for its admin to merge
    directory  /etc/<name>/directory/{kadm5.acl,slapd-acl.ldif}: the KDC's and slapd's side, rendered with
               this site's realm, DNs and current admins, for the directory's admin to merge
    secrets    /etc/<unit>/{portal,sso}.env with fresh random secrets, and the SSO's token key pair,
               made once and never overwritten
    then       nginx -t, daemon-reload, enable, restart; and a list of what only an admin can do
               (the Kerberos keytabs), with the exact commands

A host that ran an older layout (a unit named ldap-portal) is moved to the derived names: the old
unit is stopped and removed, and its /etc, /var/lib and /var/log are carried over. Units of services
the site no longer has (the WebDAV directory timer) are stopped and removed.

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
from .facts import Facts, facts, local_file

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "deploy" / "templates"
SERVICES = ("portal", "sso")  # roles that run as their own user
# What earlier versions installed, by role: the one list of old names, for the move to derived ones.
LEGACY = {"portal": "ldap-portal"}
# Units of services the site no longer runs ({unit} = a derived name): stopped and removed.
RETIRED = ("dav-homes.service", "dav-homes.timer", "{name}-dav-homes.service", "{name}-dav-homes.timer")
SKIP = {".git", ".venv", "__pycache__", ".pytest_cache", "ldap_portal.egg-info"}

Run = Callable[[list[str]], int]


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd))
    return subprocess.run(cmd).returncode


# ── rendering: pure, into any root ──────────────────────────────────────


def rendered(f: Facts, site_file: Path) -> dict[str, tuple[str, int]]:
    """Every generated file: absolute path → (content, mode)."""
    site = site_mod.load(site_file, f)
    extra = {"generated": f"Generated from {f.site_file} by portal/deploy.py: edit that and rerun the installer.",
             "aliases_sp": "".join(f" {a}" for a in f.aliases),
             "portal_root": f.extra.get("portal_root", "/account"), "port": str(f.listen)} | _front(f)
    admin_group = os.environ.get("PORTAL_ADMIN_GROUP", "admin")
    admins = _admins(admin_group)
    extra |= {"admin_group": admin_group,
              "admin_lines": "\n".join(f"portal/service@{f.realm}  ADMCILSP  {p}@{f.realm}"
                                       for u in admins for p in (f"{u}/user", u))
              or f"# (no members of {admin_group} were found when this was rendered)",
              "kdc_dn": _kdc_conf("ldap_kdc_dn") or "<ldap_kdc_dn of kdc.conf>",
              "kadmin_dn": _kdc_conf("ldap_kadmind_dn") or "<ldap_kadmind_dn of kdc.conf>",
              "portal_dn": "<the DN ldapwhoami prints for portal/service>"}

    def t(name: str) -> str:
        return f.substitute((TEMPLATES / name).read_text(), extra)

    out = {
        f"/etc/systemd/system/{f.unit('portal')}.service": (t("portal.service"), 0o644),
        f"/etc/systemd/system/{f.unit('sso')}.service": (t("sso.service"), 0o644),
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
    for leftover in ("opt/ldap-portal", "etc/m00nny-site"):
        if (root / leftover).exists():
            notes.append(f"/{leftover} is no longer used: remove it when the new units run")


SECRET_KEYS = {"portal": "PORTAL_SESSION_SECRET", "sso": "PORTAL_SSO_SECRET"}  # the services refuse < 32


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


def _secrets(f: Facts, root: Path, sh: Run, real: bool, notes: list[str]) -> None:
    for role in ("portal", "sso"):
        d = root / "etc" / f.unit(role)
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o755)  # as systemd keeps a ConfigurationDirectory: the secrets carry their own modes
        env = d / f"{role}.env"
        if not env.exists():
            env.write_text(f.substitute((TEMPLATES / f"{role}.env").read_text(), {"secret": secrets.token_urlsafe(48)}))
            notes.append(f"made {env.relative_to(root)} with a fresh secret")
        elif _fill_secret(env, SECRET_KEYS[role]):  # a hand-made file with the secret left empty
            notes.append(f"{env.relative_to(root)}: {SECRET_KEYS[role]} was empty or short, now a fresh secret")
        env.chmod(0o640)  # every time: a file made by hand may have been left world-readable
        _chown(env, f.unit(role), real)
    sso = root / "etc" / f.unit("sso")
    if not (sso / "sso-signing.pem").exists():
        if sh([str(root / f.code.lstrip("/") / ".venv/bin/python"), "-m", "portal.tokens", "genkey", str(sso)]) == 0:
            notes.append(f"made the SSO token key pair in /etc/{f.unit('sso')}")
        else:
            notes.append(f"could not make the SSO token key pair in /etc/{f.unit('sso')}: rerun the installer")
    if (sso / "sso-signing.pem").exists():
        uid, gid = _ids(f.unit("sso"))
        if real and uid >= 0:
            os.chown(sso / "sso-signing.pem", uid, gid)
        (sso / "sso-signing.pem").chmod(0o400)
    if (sso / "sso-public.pem").exists():
        (sso / "sso-public.pem").chmod(0o644)


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


def install(site_file: Path, root: Path = Path("/"), sh: Run = _run, src: Path = REPO) -> int:
    real = root == Path("/")
    if real and os.geteuid() != 0:
        print("run as root: sudo deploy/install.sh", file=sys.stderr)
        return 1
    f = facts(str(site_file))
    notes: list[str] = []
    print(f"site {f.name}: realm {f.realm}, domain {f.domain}, code {f.code}")
    _migrate(f, root, sh, notes)
    for role in SERVICES:
        if _ids(f.unit(role))[0] < 0:
            sh(["useradd", "--system", "--no-create-home", "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin",
                f.unit(role)])
    code = root / f.code.lstrip("/")
    _sync_code(src, code)
    venv = code / ".venv"
    if not (venv / "bin/python").exists():
        sh([sys.executable, "-m", "venv", str(venv)])
    pip = [str(venv / "bin/pip"), "install", "-q", "-e", f"{code}[kerberos]"]
    if sh(pip) != 0 and shutil.which("apt-get"):  # python-gssapi builds against the Kerberos headers
        sh(["apt-get", "install", "-y", "-q", "libkrb5-dev", "gcc"])
        if sh(pip) != 0:
            print("pip could not install the portal (see above): nothing changed on the host", file=sys.stderr)
            return 1
    elif not shutil.which("apt-get") and not (venv / "bin/uvicorn").exists():
        print("pip could not install the portal: install the Kerberos headers (libkrb5-dev / krb5-devel) "
              "and a C compiler, then rerun", file=sys.stderr)
        return 1
    write_rendered(rendered(f, site_file), root)
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
    units = [f"{f.unit('portal')}.service", f"{f.unit('sso')}.service"]
    sh(["systemctl", "daemon-reload"])
    sh(["systemctl", "enable", *units])
    sh(["systemctl", "restart", *units])
    sh(["systemctl", "reload", "nginx"])
    for n in notes:
        print("·", n)
    print(f"\nThe directory's side, for its admin to merge (on the KDC, and the LDAP server):\n"
          f"  /etc/{f.name}/directory/kadm5.acl       into /etc/krb5kdc/kadm5.acl, then restart krb5-admin-server\n"
          f"  /etc/{f.name}/directory/slapd-acl.ldif  merge with the current olcAccess (instructions inside)")
    if f.router:
        print(f"\nThe router's side, for its admin to merge (TLS ends there; this host serves plain HTTP on "
              f":{f.listen} to {', '.join(f.router)} only):\n  /etc/{f.name}/router/{f.domain}.conf")
    todo = _keytabs(f, root)
    if todo:
        print("\nOnly an admin can do these (then: systemctl restart "
              f"{f.unit('portal')} {f.unit('sso')}):\n\n" + "\n\n".join(todo))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="deploy/install.sh", description=__doc__.split("\n")[0])
    p.add_argument("site", nargs="?", default=str(REPO / "deploy" / "site.toml"))
    p.add_argument("--render-into", metavar="DIR", help="only render every file under DIR (nothing installed)")
    p.add_argument("--check", action="store_true", help="print the derived facts and the services, and exit")
    a = p.parse_args(argv)
    site_file = Path(a.site)
    f = facts(str(site_file))
    if a.check:
        for k in ("realm", "name", "domain", "base_dn", "users_ou", "groups_ou", "ldap_uri", "issuer", "http_service",
                  "code"):
            print(f"{k:13} {getattr(f, k)}")
        print(f"{'tls':13} " + (f"at the router ({', '.join(f.router)}), plain HTTP on :{f.listen}" if f.router
                                 else f"nginx (/etc/letsencrypt/live/{f.domain})"))
        for role in ("portal", "sso"):
            print(f"{'unit':13} {f.unit(role)}")
        for app in site_mod.load(site_file, f).apps:
            print(f"{'app':13} {app.id} ({app.audience or '-'}, {len(app.routes)} routes)")
        return 0
    if a.render_into:
        write_rendered(rendered(f, site_file), Path(a.render_into))
        print(f"rendered into {a.render_into}")
        return 0
    return install(site_file)


if __name__ == "__main__":
    sys.exit(main())
