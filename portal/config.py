"""Settings, read from PORTAL_* environment variables (see deploy/portal.env.example)."""
import os
from dataclasses import dataclass, field

from .facts import facts, running_dir


def _env(name: str, default: str) -> str:
    return os.environ.get(f"PORTAL_{name}", default)


def _secret(name: str) -> str:
    """PORTAL_<NAME>_FILE (a root-provisioned file) wins over PORTAL_<NAME>."""
    path = _env(f"{name}_FILE", "")
    if path:
        with open(path) as f:
            return f.read().strip()
    return _env(name, "")


def _env_list(name: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in _env(name, default).split(",") if x.strip())


_SITES: dict = {}


def _f():  # noqa: ANN202 — the site's facts (portal/facts.py), read when a default is needed
    return facts()


def _conf(role: str, name: str) -> str:
    """A file in the running unit's configuration directory (systemd's CONFIGURATION_DIRECTORY),
    else in /etc/<the role's unit>."""
    return running_dir("CONFIGURATION_DIRECTORY", _f().conf_dir(role)) + "/" + name


@dataclass(frozen=True)
class Settings:
    # Site facts derive from the Kerberos realm (portal/facts.py); PORTAL_<NAME> overrides any of them.
    realm: str = field(default_factory=lambda: _env("REALM", _f().realm))
    ldap_uri: str = field(default_factory=lambda: _env("LDAP_URI", _f().ldap_uri))
    ldap_ca_file: str = field(default_factory=lambda: _env("LDAP_CA_FILE", "/etc/ldap/ca.crt"))
    base_dn: str = field(default_factory=lambda: _env("BASE_DN", _f().base_dn))
    users_ou: str = field(default_factory=lambda: _env("USERS_OU", _f().users_ou))
    groups_ou: str = field(default_factory=lambda: _env("GROUPS_OU", _f().groups_ou))

    # Matches the existing layout: canonical "alice/user@REALM" with alias "alice@REALM".
    principal_format: str = field(default_factory=lambda: _env("PRINCIPAL_FORMAT", "{uid}/user"))
    principal_alias_format: str = field(default_factory=lambda: _env("PRINCIPAL_ALIAS_FORMAT", "{uid}"))
    kadmin_policy: str = field(default_factory=lambda: _env("KADMIN_POLICY", "users"))
    # Write userPassword: {SASL}principal so LDAP simple binds pass through saslauthd to Kerberos.
    sasl_userpassword: bool = field(default_factory=lambda: _env("SASL_USERPASSWORD", "0") == "1")

    # Service identity. Must NOT match "*/admin" (default kadm5.acl grants those everything).
    service_principal: str = field(default_factory=lambda: _env("SERVICE_PRINCIPAL", f"portal/service@{_f().realm}"))
    service_keytab: str = field(default_factory=lambda: _env("SERVICE_KEYTAB", _conf("portal", "portal.keytab")))
    # Used to prove the KDC is genuine when verifying a login password.
    http_service: str = field(default_factory=lambda: _env("HTTP_SERVICE", _f().http_service))
    http_keytab: str = field(default_factory=lambda: _env("HTTP_KEYTAB", _conf("portal", "http.keytab")))

    default_group: str = field(default_factory=lambda: _env("DEFAULT_GROUP", "user"))
    admin_group: str = field(default_factory=lambda: _env("ADMIN_GROUP", "admin"))
    helpdesk_group: str = field(default_factory=lambda: _env("HELPDESK_GROUP", "helpdesk"))
    # Members of these groups can only be changed by portal admins, never by helpdesk.
    protected_groups: tuple[str, ...] = field(default_factory=lambda: _env_list("PROTECTED_GROUPS", "admin"))

    uid_min: int = field(default_factory=lambda: int(_env("UID_MIN", "10001")))
    uid_max: int = field(default_factory=lambda: int(_env("UID_MAX", "59999")))
    home_format: str = field(default_factory=lambda: _env("HOME_FORMAT", "/home/{uid}"))
    allowed_shells: tuple[str, ...] = field(
        default_factory=lambda: _env_list("ALLOWED_SHELLS", "/bin/bash,/bin/zsh,/bin/sh,/usr/bin/fish"))

    session_secret: str = field(default_factory=lambda: _env("SESSION_SECRET", ""))
    session_max_age: int = field(default_factory=lambda: int(_env("SESSION_MAX_AGE", "3600")))
    cookie_secure: bool = field(default_factory=lambda: _env("COOKIE_SECURE", "1") == "1")
    audit_log: str = field(default_factory=lambda: _env(
        "AUDIT_LOG", running_dir("LOGS_DIRECTORY", _f().log_dir("portal")) + "/audit.log"))
    # Sub-path the portal is served under behind nginx, e.g. "/account" (no trailing slash; "" = root).
    root_path: str = field(default_factory=lambda: _env("ROOT_PATH", "").rstrip("/"))

    # Account requests ("사용 신청"): anyone may ask for an account; an admin approves or rejects.
    requests_enabled: bool = field(default_factory=lambda: _env("REQUESTS", "1") == "1")
    requests_db: str = field(default_factory=lambda: _env(
        "REQUESTS_DB", running_dir("STATE_DIRECTORY", _f().state_dir("portal")) + "/requests.db"))
    # Unanswered requests (and the personal data in them) are deleted after this many days.
    request_ttl_days: int = field(default_factory=lambda: int(_env("REQUEST_TTL_DAYS", "30")))
    request_max_pending: int = field(default_factory=lambda: int(_env("REQUEST_MAX_PENDING", "100")))
    # Who applicants contact about their personal data (shown in the consent notice).
    privacy_contact: str = field(default_factory=lambda: _env("PRIVACY_CONTACT", ""))
    # gecos is world-readable through NSS (getent passwd), so names are not copied into it by default.
    write_gecos: bool = field(default_factory=lambda: _env("WRITE_GECOS", "0") == "1")

    # Behind the SSO (portal/sso.py) and nginx auth_request: "sso" takes the user from the signed
    # X-Auth-Token (see portal/tokens.py), verified with the SSO's public key. "local": the portal's
    # own sign-in page, as before.
    auth_mode: str = field(default_factory=lambda: _env("AUTH", "local"))
    login_url: str = field(default_factory=lambda: _env("LOGIN_URL", "/auth/login"))
    sso_issuer: str = field(default_factory=lambda: _env("SSO_ISSUER", _f().issuer))
    sso_public_key_file: str = field(default_factory=lambda: _env(
        "SSO_PUBLIC_KEY_FILE", _f().conf_dir("sso") + "/sso-public.pem"))
    token_audience: str = field(default_factory=lambda: _env("TOKEN_AUDIENCE", "account"))
    # The site file (deploy/site.toml, installed as /etc/<name>/site.toml): the portal links its apps
    # with a menu label, and the SSO mints tokens for their audiences too. "" = no apps.
    site_file: str = field(default_factory=lambda: _env("SITE", ""))

    # SSO service (portal/sso.py): one sign-in for the site, a cookie for browsers.
    sso_secret: str = field(default_factory=lambda: _secret("SSO_SECRET"))  # signs the SSO cookie
    sso_signing_key_file: str = field(default_factory=lambda: _env("SSO_SIGNING_KEY_FILE", _conf("sso", "sso-signing.pem")))
    # Backends the SSO mints tokens for (nginx names one per location in X-Auth-Audience).
    sso_audiences: tuple[str, ...] = field(default_factory=lambda: _env_list("SSO_AUDIENCES", "account"))
    token_ttl: int = field(default_factory=lambda: int(_env("TOKEN_TTL", "60")))
    sso_cookie: str = field(default_factory=lambda: _env("SSO_COOKIE", f"{_f().name}_sso"))
    sso_max_age: int = field(default_factory=lambda: int(_env("SSO_MAX_AGE", "28800")))  # absolute, from sign-in

    def __post_init__(self):
        if self.auth_mode not in ("local", "sso"):
            raise ValueError("PORTAL_AUTH must be local or sso")
        if self.root_path and not self.root_path.startswith("/"):
            raise ValueError("PORTAL_ROOT_PATH must start with '/', e.g. /account")

    def site(self):  # noqa: ANN201 — portal.site.Site
        """The declared services (empty when PORTAL_SITE is unset). Read once per process."""
        from . import site

        cached = _SITES.get(self.site_file)
        if cached is None:
            cached = _SITES[self.site_file] = site.load(self.site_file) if self.site_file else site.Site()
        return cached

    @property
    def site_name(self) -> str:
        return _f().name

    def audiences(self) -> tuple[str, ...]:
        """What the SSO may mint tokens for: PORTAL_SSO_AUDIENCES and every audience of the site file."""
        return tuple(sorted(set(self.sso_audiences) | set(self.site().audiences)))

    def principal(self, uid: str) -> str:
        return f"{self.principal_format.format(uid=uid)}@{self.realm}"

    def principal_alias(self, uid: str) -> str | None:
        if not self.principal_alias_format:
            return None
        return f"{self.principal_alias_format.format(uid=uid)}@{self.realm}"

    def user_dn(self, uid: str) -> str:
        return f"uid={uid},{self.users_ou}"

    def group_dn(self, cn: str) -> str:
        return f"cn={cn},{self.groups_ou}"
