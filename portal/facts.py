"""Every fact about the site, derived from as little as possible.

One fact is the system's own: the Kerberos realm, from krb5.conf's `default_realm`. Everything else
derives from it, unless the site file ([site] in site.toml) or the environment (PORTAL_*) says
otherwise, in that order of precedence: environment, site file, derivation.

    realm         M00NNY.KR               krb5.conf [libdefaults] default_realm
    name          m00nny                  the realm's first label, lowercased
    domain        www.m00nny.kr           www.<realm, lowercased>
    base_dn       dc=m00nny,dc=kr         the realm's labels
    users_ou      ou=Users,<base_dn>
    groups_ou     ou=Groups,<base_dn>
    ldap_uri      ldaps://ldap.<realm, lowercased>
    issuer        https://<domain>
    http_service  HTTP@<domain>
    code          /opt/<name>-portal      the installed code and its virtualenv

Each service is named after the site and its role, and that name is everything systemd keys on:
the unit, its system user, /etc/<unit>, /var/lib/<unit> and /var/log/<unit>.

    portal  <name>-portal   :8080        sso  <name>-sso   :8090        dav  <name>-dav-homes

Standard library only: the installer reads these before any virtualenv exists.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

KRB5_CONF = os.environ.get("KRB5_CONFIG", "/etc/krb5.conf").split(":")[0]
ROLES = {"portal": 8080, "sso": 8090, "dav-homes": 0}
USED = {"realm", "name", "base_dn", "domain", "users_ou", "groups_ou", "ldap_uri", "sso_issuer", "http_service",
        "code", "ports", "aliases"}


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
    extra: dict  # the other string keys of [site] (portal_root, dav_root, …): placeholders and options

    def unit(self, role: str) -> str:
        return f"{self.name}-{role}"

    def conf_dir(self, role: str) -> str:
        return f"/etc/{self.unit(role)}"

    def state_dir(self, role: str) -> str:
        return f"/var/lib/{self.unit(role)}"

    def log_dir(self, role: str) -> str:
        return f"/var/log/{self.unit(role)}"

    def upstream(self, role: str) -> str:
        return f"http://127.0.0.1:{self.ports[role]}"

    @property
    def webroot(self) -> str:
        return f"/var/www/{self.name}"

    @property
    def site_file(self) -> str:
        return f"/etc/{self.name}/site.toml"

    def substitute(self, text: str, extra: dict | None = None) -> str:
        """@@key@@ in a template or a site-file string: a fact (@@domain@@), a role's unit, port or
        upstream (@@unit:sso@@, @@port:portal@@, @@upstream:portal@@), or a key of `extra`."""
        extra = extra or {}

        def one(m: re.Match) -> str:
            key = m.group(1)
            kind, _, role = key.partition(":")
            if role:
                if role not in self.ports:
                    raise FactError(f"@@{key}@@: no role {role!r} (roles: {', '.join(self.ports)})")
                return {"unit": self.unit, "port": lambda r: str(self.ports[r]), "upstream": self.upstream}[kind](role)
            if key in extra:
                return str(extra[key])
            if key in self.extra:
                return str(self.extra[key])
            v = getattr(self, key, None)
            if not isinstance(v, str):
                raise FactError(f"unknown placeholder @@{key}@@")
            return v
        return re.sub(r"@@([a-z_]+(?::[a-z-]+)?)@@", one, text)


def _site_section(site_file: str | None) -> dict:
    if not site_file:
        return {}
    try:
        return tomllib.loads(Path(site_file).read_text()).get("site", {})
    except FileNotFoundError:
        return {}


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
    ports = dict(ROLES)
    for role, port in (given.get("ports") or {}).items():
        ports[role] = int(port)
    return Facts(
        realm=realm, name=name, domain=domain, aliases=tuple(given.get("aliases", ())),
        base_dn=base_dn, users_ou=get("users_ou", f"ou=Users,{base_dn}"),
        groups_ou=get("groups_ou", f"ou=Groups,{base_dn}"), ldap_uri=get("ldap_uri", f"ldaps://ldap.{lower}"),
        issuer=get("sso_issuer", f"https://{domain}"), http_service=get("http_service", f"HTTP@{domain}"),
        code=given.get("code") or f"/opt/{name}-portal", ports=ports,
        extra={k: v for k, v in given.items() if isinstance(v, str) and k not in USED})


def running_dir(kind: str, fallback: str) -> str:
    """systemd's own directory for the running unit (CONFIGURATION_DIRECTORY, STATE_DIRECTORY,
    LOGS_DIRECTORY), else the fallback."""
    v = os.environ.get(kind, "")
    return v.split(":")[0] if v else fallback
