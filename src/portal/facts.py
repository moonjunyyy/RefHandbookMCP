"""Every fact about the site, derived from as little as possible.

One fact is the system's own: the Kerberos realm, from krb5.conf's `default_realm`. Everything else
derives from it, unless the site file ([site] in site.toml, then in site.local.toml beside it) or
the environment (PORTAL_*) says otherwise, in that order of precedence: environment, site file,
derivation.

    realm         M00NNY.KR               krb5.conf [libdefaults] default_realm
    name          m00nny                  the realm's first label, lowercased
    domain        www.m00nny.kr           www.<realm, lowercased>
    base_dn       dc=m00nny,dc=kr         the realm's labels
    users_ou      ou=Users,<base_dn>
    groups_ou     ou=Groups,<base_dn>
    projects_ou   ou=Projects,<groups_ou>  the groups people make themselves (docs/projects.md)
    ldap_uri      ldaps://ldap.<realm, lowercased>
    issuer        https://<domain>
    http_service  HTTP@<domain>
    code          /opt/<name>-site        the installed code and its virtualenv (both packages)
    portal_root   /account                where the account portal is served
    title         <realm>                 the site's name as every page shows it (M00NNY.KR)
    admin_group   admin                   the POSIX group of the site's administrators
    helpdesk_group helpdesk               the group that may reset passwords and unlock accounts
    router        (none)                  a TLS-terminating proxy in front (IP or CIDR, or a list of
                                          them): nginx then serves plain HTTP on `listen` (80) to it
    router_address, router_cert, router_key   the router's side (deploy.ROUTER_KEYS): this host's
                                          address as the router reaches it, the certificate there

Each service is named after the site and its role, and that name is everything systemd keys on:
the unit, its system user, /etc/<unit>, /var/lib/<unit> and /var/log/<unit>.

    portal    <name>-portal    :8080     the account portal
    sso       <name>-sso       :8090     the site sign-in, at SIGNIN (/auth)
    apps      <name>-apps      :8100     each user's storage for the hosted apps
    handbook  <name>-handbook  :8765     the reference handbook (MCP)
    runner    <name>-runner              the handbook's sandbox runner: the handbook's user and data

Standard library only: the installer reads these before any virtualenv exists.
"""

from __future__ import annotations

import ipaddress
import os
import re
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

KRB5_CONF = os.environ.get("KRB5_CONFIG", "/etc/krb5.conf").split(":")[0]
ROLES = {"portal": 8080, "sso": 8090, "apps": 8100, "handbook": 8765, "runner": 0}
# A role that runs as another role's user, in its directories (the runner works on the handbook's data).
RUNS_AS = {"runner": "handbook"}
# Where the site sign-in lives (portal/sso.py): its pages, its check for nginx, its stylesheet.
SIGNIN = "/auth"
USED = {"realm", "name", "base_dn", "domain", "users_ou", "groups_ou", "projects_ou", "ldap_uri", "sso_issuer", "http_service",
        "code", "ports", "aliases", "router", "listen", "portal_root", "title", "admin_group", "helpdesk_group"}


class FactError(ValueError):
    pass


def krb5_default_realm(path: str = KRB5_CONF) -> str:
    try:
        text = Path(path).read_text()
    except OSError:
        return ""
    section = ""
    for line in text.splitlines():
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        if line.startswith("["):
            section = line.strip("[]").strip()
        elif section == "libdefaults" and "=" in line:
            k, v = (x.strip() for x in line.split("=", 1))
            if k == "default_realm":
                return v
    return ""


@dataclass(frozen=True)
class Facts:
    realm: str
    name: str
    domain: str
    aliases: tuple[str, ...]
    base_dn: str
    users_ou: str
    groups_ou: str
    ldap_uri: str
    issuer: str
    http_service: str
    code: str
    ports: dict
    extra: dict  # the other string keys of [site]: placeholders and options
    router: tuple[str, ...] = ()  # TLS ends there; empty = nginx holds the certificate itself
    listen: int = 80  # the plain-HTTP port the router connects to
    portal_root: str = "/account"
    title: str = ""  # the site's name on every page; the realm unless [site] title says otherwise
    admin_group: str = "admin"
    helpdesk_group: str = "helpdesk"
    projects_ou: str = ""  # the groups people make themselves (projects), one level under the groups' OU

    def unit(self, role: str) -> str:
        return f"{self.name}-{role}"

    def user(self, role: str) -> str:
        """The system user a role's unit runs as (and owns its directories)."""
        return self.unit(RUNS_AS.get(role, role))

    def conf_dir(self, role: str) -> str:
        return f"/etc/{self.unit(role)}"

    def state_dir(self, role: str) -> str:
        return f"/var/lib/{self.unit(role)}"

    def log_dir(self, role: str) -> str:
        return f"/var/log/{self.unit(role)}"

    def upstream(self, role: str) -> str:
        return f"http://127.0.0.1:{self.ports[role]}"

    @property
    def apps_root(self) -> str:
        """Where the built files of the apps the site hosts live (/apps/<id>/ is <apps_root>/<id>)."""
        return f"/var/www/{self.name}/apps"

    @property
    def site_file(self) -> str:
        return f"/etc/{self.name}/site.toml"

    def substitute(self, text: str, extra: dict | None = None) -> str:
        """@@key@@ in a template or a site-file string: a fact (@@domain@@), a role's unit, user, port
        or upstream (@@unit:sso@@, @@user:runner@@, @@port:portal@@, @@upstream:portal@@), or a key of
        `extra`."""
        extra = extra or {}

        def one(m: re.Match) -> str:
            key = m.group(1)
            kind, _, role = key.partition(":")
            if role:
                if role not in self.ports:
                    raise FactError(f"@@{key}@@: no role {role!r} (roles: {', '.join(self.ports)})")
                return {"unit": self.unit, "user": self.user, "port": lambda r: str(self.ports[r]),
                        "upstream": self.upstream}[kind](role)
            if key in extra:
                return str(extra[key])
            if key in self.extra:
                return str(self.extra[key])
            v = getattr(self, key, None)
            if not isinstance(v, str):
                raise FactError(f"unknown placeholder @@{key}@@")
            return v
        return re.sub(r"@@([a-z_]+(?::[a-z-]+)?)@@", one, text)


def local_file(site_file: str | Path) -> Path:
    """The host's own [site] keys beside the site file (site.toml -> site.local.toml), kept out of
    the repository: addresses and the like. Its keys win over the site file's."""
    p = Path(site_file)
    return p.with_name(f"{p.stem}.local{p.suffix}")


def _site_section(site_file: str | None) -> dict:
    if not site_file:
        return {}
    given = {}
    for p in (Path(site_file), local_file(site_file)):
        try:
            given |= tomllib.loads(p.read_text()).get("site", {})
        except FileNotFoundError:
            pass
    return given


@cache
def facts(site_file: str | None = None) -> Facts:
    """The site's facts: PORTAL_<KEY> wins, then [site] in the site file, then the derivation."""
    site_file = site_file or os.environ.get("PORTAL_SITE") or None
    given = _site_section(site_file)

    def get(key: str, derived: str) -> str:
        return os.environ.get(f"PORTAL_{key.upper()}") or given.get(key) or derived

    realm = get("realm", krb5_default_realm())
    if not realm:
        raise FactError("no Kerberos realm: set default_realm in krb5.conf, realm in [site], or PORTAL_REALM")
    lower = realm.lower()
    labels = lower.split(".")
    name = get("name", labels[0])
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", name):
        raise FactError(f"site name {name!r}: lowercase letters, digits and - (it names units and users)")
    base_dn = get("base_dn", ",".join(f"dc={x}" for x in labels))
    domain = get("domain", f"www.{lower}")
    router = given.get("router") or ()
    router = (router,) if isinstance(router, str) else tuple(router)
    for net in router:
        try:
            ipaddress.ip_network(net, strict=False)
        except ValueError:
            raise FactError(f"router {net!r}: an IP address or a CIDR") from None
    ports = dict(ROLES)
    for role, port in (given.get("ports") or {}).items():
        ports[role] = int(port)
    groups_ou = get("groups_ou", f"ou=Groups,{base_dn}")
    return Facts(
        realm=realm, name=name, domain=domain, aliases=tuple(given.get("aliases", ())),
        base_dn=base_dn, users_ou=get("users_ou", f"ou=Users,{base_dn}"),
        groups_ou=groups_ou, ldap_uri=get("ldap_uri", f"ldaps://ldap.{lower}"),
        issuer=get("sso_issuer", f"https://{domain}"), http_service=get("http_service", f"HTTP@{domain}"),
        code=given.get("code") or f"/opt/{name}-site", ports=ports,
        extra={k: v for k, v in given.items() if isinstance(v, str) and k not in USED},
        router=router, listen=int(given.get("listen", 80)),
        portal_root=get("portal_root", Facts.portal_root).rstrip("/"), title=get("title", realm),
        admin_group=get("admin_group", Facts.admin_group), helpdesk_group=get("helpdesk_group", Facts.helpdesk_group),
        projects_ou=get("projects_ou", f"ou=Projects,{groups_ou}"))


def running_dir(kind: str, fallback: str) -> str:
    """systemd's own directory for the running unit (CONFIGURATION_DIRECTORY, STATE_DIRECTORY,
    LOGS_DIRECTORY), else the fallback."""
    v = os.environ.get(kind, "")
    return v.split(":")[0] if v else fallback
