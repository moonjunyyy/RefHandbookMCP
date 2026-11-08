"""LDAP side, bound as the portal service principal over LDAPS + SASL/GSSAPI.

The portal never writes krb* attributes itself; kadmind owns those (kldap backend). It writes an
account's SMB side (docs/smb.md): the sambaSamAccount class, the NT hash of a password it has just set
in Kerberos, the disabled flag."""
import ssl
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from ldap3 import (BASE, KERBEROS, LEVEL, MODIFY_ADD, MODIFY_DELETE, MODIFY_REPLACE, NO_ATTRIBUTES, SASL,
                   SUBTREE, Connection, Server, Tls)
from ldap3.core.exceptions import LDAPException, LDAPNoSuchObjectResult
from ldap3.utils.conv import escape_filter_chars

from . import ntlm
from .config import Settings

DISALLOW_ALL_TIX = 0x40
SMB_ATTRS = ["objectClass", "uidNumber", "sambaSID", "sambaAcctFlags"]
USER_ATTRS = ["uid", "cn", "givenName", "sn", "displayName", "mail", "loginShell", "uidNumber",
              "gidNumber", "homeDirectory", "krbPrincipalName", "krbTicketFlags", "krbLoginFailedCount",
              "krbLastPwdChange", "krbPasswordExpiration"]
SELF_EDITABLE = {"displayName", "mail", "loginShell"}
PROJECT_ATTRS = ["cn", "gidNumber", "memberUid", "description"]


class DirectoryError(Exception):
    pass


@dataclass
class User:
    uid: str
    dn: str
    cn: str = ""
    given_name: str = ""
    sn: str = ""
    display_name: str = ""
    mail: str = ""
    login_shell: str = ""
    uid_number: int = 0
    gid_number: int = 0
    home: str = ""
    principals: list[str] = field(default_factory=list)
    disabled: bool = False
    failed_logins: int = 0
    last_pwd_change: str = ""
    groups: list[str] = field(default_factory=list)


@dataclass
class Project:
    """A group people made themselves (portal/projects.py): a posixGroup under the projects' OU."""
    cn: str
    dn: str = ""
    gid_number: int = 0
    members: list[str] = field(default_factory=list)
    description: str = ""


def _first(entry, attr, default=""):
    v = entry.get(attr)
    if isinstance(v, list):
        return v[0] if v else default
    return default if v is None else v


def has_smb(entry: dict) -> bool:
    return ntlm.ACCOUNT_CLASS.lower() in {str(c).lower() for c in entry.get("objectClass") or []}


def smb_password_mods(entry: dict, sid: str | None, hashed: str, now: int) -> dict:
    """The modification that makes `hashed` an entry's SMB password: the account class and its SID when
    the entry has none yet (`sid`), the hash and the time it was set, normal flags when there are none;
    a LanMan hash goes (lanman auth stays off)."""
    mods: dict = {}
    if not has_smb(entry):
        if not sid:
            raise DirectoryError("an entry without an SMB account needs a SID")
        mods["objectClass"] = [(MODIFY_ADD, [ntlm.ACCOUNT_CLASS])]
        mods["sambaSID"] = [(MODIFY_REPLACE, [sid])]
    if not _first(entry, "sambaAcctFlags"):
        mods["sambaAcctFlags"] = [(MODIFY_REPLACE, [ntlm.encode_flags({ntlm.NORMAL})])]
    mods |= own_password_mods(hashed, now)
    return mods


def own_password_mods(hashed: str, now: int) -> dict:
    """What a person may write on their own entry: the hash, when it was set, no LanMan hash."""
    return {"sambaNTPassword": [(MODIFY_REPLACE, [hashed])], "sambaPwdLastSet": [(MODIFY_REPLACE, [str(now)])],
            "sambaLMPassword": [(MODIFY_REPLACE, [])]}


class Directory:
    def __init__(self, settings: Settings):
        self.s = settings
        tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=settings.ldap_ca_file,
                  version=ssl.PROTOCOL_TLS_CLIENT)
        self.server = Server(settings.ldap_uri, tls=tls, connect_timeout=10)
        self._id_lock = threading.Lock()

    @contextmanager
    def _conn(self, creds=None):
        """Bound as the portal (its keytab), or as whoever `creds` are (gssapi credentials)."""
        import gssapi
        creds = creds or gssapi.Credentials(
            name=gssapi.Name(self.s.service_principal, gssapi.NameType.kerberos_principal),
            usage="initiate",
            store={"client_keytab": self.s.service_keytab, "ccache": "MEMORY:portal"})
        conn = Connection(self.server, authentication=SASL, sasl_mechanism=KERBEROS,
                          sasl_credentials=(None, None, creds), raise_exceptions=True, read_only=False)
        try:
            if self.server.ssl is False:
                conn.open()
                conn.start_tls()
            conn.bind()
            yield conn
        except LDAPException as e:
            raise DirectoryError(str(e)) from e
        finally:
            conn.unbind()

    # ---- reads -------------------------------------------------------------------------------

    def _to_user(self, conn, dn: str, a: dict) -> User:
        flags = int(_first(a, "krbTicketFlags", 0) or 0)
        u = User(uid=_first(a, "uid"), dn=dn, cn=_first(a, "cn"), given_name=_first(a, "givenName"),
                 sn=_first(a, "sn"), display_name=_first(a, "displayName"), mail=_first(a, "mail"),
                 login_shell=_first(a, "loginShell"), uid_number=int(_first(a, "uidNumber", 0) or 0),
                 gid_number=int(_first(a, "gidNumber", 0) or 0), home=_first(a, "homeDirectory"),
                 principals=list(a.get("krbPrincipalName") or []), disabled=bool(flags & DISALLOW_ALL_TIX),
                 failed_logins=int(_first(a, "krbLoginFailedCount", 0) or 0),
                 last_pwd_change=str(_first(a, "krbLastPwdChange", "")))
        u.groups = self._groups_of(conn, u.uid)
        return u

    def _groups_of(self, conn, uid: str) -> list[str]:
        conn.search(self.s.groups_ou, f"(&(objectClass=posixGroup)(memberUid={escape_filter_chars(uid)}))",
                    LEVEL, attributes=["cn"])
        return sorted(_first(e.entry_attributes_as_dict, "cn") for e in conn.entries)

    def get_user(self, uid: str) -> User | None:
        with self._conn() as conn:
            try:
                conn.search(self.s.user_dn(uid), "(objectClass=posixAccount)", BASE, attributes=USER_ATTRS)
            except LDAPNoSuchObjectResult:
                return None
            if not conn.response:
                return None
            r = conn.response[0]
            return self._to_user(conn, r["dn"], r["attributes"])

    def search_users(self, query: str, limit: int = 200) -> list[User]:
        q = escape_filter_chars(query.strip())
        flt = "(objectClass=posixAccount)"
        if q:
            flt = f"(&{flt}(|(uid=*{q}*)(cn=*{q}*)(displayName=*{q}*)(mail=*{q}*)))"
        with self._conn() as conn:
            conn.search(self.s.users_ou, flt, LEVEL, attributes=USER_ATTRS)
            entries = [r for r in conn.response if r.get("type") == "searchResEntry"][:limit]
            users = [self._to_user(conn, r["dn"], r["attributes"]) for r in entries]
        return sorted(users, key=lambda u: u.uid)

    def list_groups(self) -> list[tuple[str, int]]:
        with self._conn() as conn:
            conn.search(self.s.groups_ou, "(objectClass=posixGroup)", LEVEL, attributes=["cn", "gidNumber"])
            return sorted((_first(e.entry_attributes_as_dict, "cn"), int(_first(e.entry_attributes_as_dict, "gidNumber", 0)))
                          for e in conn.entries)

    # ---- writes ------------------------------------------------------------------------------

    def update_self(self, uid: str, changes: dict[str, str]) -> None:
        bad = set(changes) - SELF_EDITABLE
        if bad:
            raise DirectoryError(f"Not editable: {', '.join(sorted(bad))}")
        mods = {k: [(MODIFY_REPLACE, [v] if v else [])] for k, v in changes.items()}
        with self._conn() as conn:
            conn.modify(self.s.user_dn(uid), mods)

    def _next_id(self, conn) -> int:
        """Smallest free number usable as both uidNumber and the private group's gidNumber.
        Also enable slapo-unique on uidNumber/gidNumber; this lock only covers one process."""
        used: set[int] = set()
        for flt, attr in (("(objectClass=posixAccount)", "uidNumber"), ("(objectClass=posixGroup)", "gidNumber")):
            for r in conn.extend.standard.paged_search(self.s.base_dn, flt, SUBTREE, attributes=[attr],
                                                       paged_size=500, generator=True):
                if r.get("type") == "searchResEntry" and _first(r["attributes"], attr, None) is not None:
                    used.add(int(_first(r["attributes"], attr)))
        for n in range(self.s.uid_min, self.s.uid_max + 1):
            if n not in used:
                return n
        raise DirectoryError("No free uidNumber left in the configured range.")

    def create_user(self, uid: str, name: str, mail: str, shell: str) -> User:
        """Creates the private group, the user entry and default-group membership.
        Kerberos keys are added afterwards by kadmin (addprinc -x dn=...).

        The name is optional. inetOrgPerson requires cn and sn, so without one they hold the uid."""
        with self._id_lock, self._conn() as conn:
            conn.search(self.s.base_dn, f"(|(uid={escape_filter_chars(uid)})(&(objectClass=posixGroup)(cn={escape_filter_chars(uid)})))",
                        SUBTREE, attributes=[NO_ATTRIBUTES])
            if any(r.get("type") == "searchResEntry" for r in conn.response):
                raise DirectoryError(f"'{uid}' already exists (as a user or group).")
            num = self._next_id(conn)
            conn.add(self.s.group_dn(uid), ["posixGroup"], {"cn": uid, "gidNumber": num, "memberUid": uid})
            attrs = {
                "uid": uid, "cn": name or uid, "sn": name or uid,
                "uidNumber": num, "gidNumber": num, "homeDirectory": self.s.home_format.format(uid=uid),
                "loginShell": shell,
            }
            if name:
                attrs["displayName"] = name
            if mail:
                attrs["mail"] = mail
            # gecos is world-readable through NSS (getent passwd), unlike the ACL-protected name attributes.
            if self.s.write_gecos and name and name.isascii():
                attrs["gecos"] = name  # IA5String: ASCII only
            if self.s.sasl_userpassword:
                attrs["userPassword"] = "{SASL}" + self.s.principal(uid)
            try:
                conn.add(self.s.user_dn(uid), ["inetOrgPerson", "posixAccount", "shadowAccount"], attrs)
                if self.s.default_group:
                    conn.modify(self.s.group_dn(self.s.default_group), {"memberUid": [(MODIFY_ADD, [uid])]})
            except LDAPException:
                self._delete_entries(conn, uid)
                raise
        return self.get_user(uid)

    def _delete_entries(self, conn, uid: str) -> None:
        for dn in (self.s.user_dn(uid), self.s.group_dn(uid)):
            try:
                conn.delete(dn)
            except LDAPException:
                pass
        if self.s.default_group:
            try:
                conn.modify(self.s.group_dn(self.s.default_group), {"memberUid": [(MODIFY_DELETE, [uid])]})
            except LDAPException:
                pass

    def delete_user(self, uid: str) -> None:
        """Remove the account: its entry (the kldap backend keeps the Kerberos principal and alias in it,
        so they go too), its private group, and its name from every group it was in."""
        with self._conn() as conn:
            for g in self._groups_of(conn, uid):
                if g != uid:
                    conn.modify(self.s.group_dn(g), {"memberUid": [(MODIFY_DELETE, [uid])]})
            for dn in (self.s.user_dn(uid), self.s.group_dn(uid)):
                try:
                    conn.delete(dn)
                except LDAPNoSuchObjectResult:
                    pass  # half made (a create that failed midway): what is there goes

    def rollback_user(self, uid: str) -> None:
        with self._conn() as conn:
            self._delete_entries(conn, uid)

    def set_membership(self, group: str, uid: str, member: bool) -> None:
        with self._conn() as conn:
            conn.modify(self.s.group_dn(group), {"memberUid": [(MODIFY_ADD if member else MODIFY_DELETE, [uid])]})

    # ---- SMB (docs/smb.md): what Samba's ldapsam reads of an account -------------------------------

    def _smb_entry(self, conn, uid: str) -> dict:
        try:
            conn.search(self.s.user_dn(uid), "(objectClass=posixAccount)", BASE, attributes=SMB_ATTRS)
        except LDAPNoSuchObjectResult:
            raise DirectoryError(f"{uid}: no such account") from None
        if not conn.response:
            raise DirectoryError(f"{uid}: no such account")
        return conn.response[0]["attributes"]

    def _new_sid(self, conn, entry: dict) -> str:
        """The SID Samba's algorithmic mapping gives the entry's uid, under the domain entry's SID; one
        another entry holds already is refused."""
        dn = self.s.samba_domain_dn
        try:
            conn.search(dn, f"(objectClass={ntlm.DOMAIN_CLASS})", BASE,
                        attributes=["sambaSID", "sambaAlgorithmicRidBase"])
            domain = conn.response[0]["attributes"] if conn.response else {}
        except LDAPNoSuchObjectResult:
            domain = {}
        base = _first(domain, "sambaAlgorithmicRidBase", None)
        if not _first(domain, "sambaSID") or base is None:
            raise DirectoryError(f"{dn}: no Samba domain entry with its SID and algorithmic RID base "
                                 "(the installer renders samba.ldif; docs/smb.md)")
        sid = f"{_first(domain, 'sambaSID')}-{ntlm.user_rid(int(_first(entry, 'uidNumber')), int(base))}"
        conn.search(self.s.base_dn, f"(sambaSID={escape_filter_chars(sid)})", SUBTREE, attributes=[NO_ATTRIBUTES])
        held = [r["dn"] for r in conn.response if r.get("type") == "searchResEntry"]
        if held:
            raise DirectoryError(f"the SID {sid} is held by {held[0]}")
        return sid

    def set_smb_password(self, uid: str, password: str) -> None:
        """The account's SMB password, as the portal: its NT hash, and the account class and SID first
        when the entry has no SMB account yet."""
        hashed = ntlm.nt_hash(password)
        with self._conn() as conn:
            entry = self._smb_entry(conn, uid)
            sid = None if has_smb(entry) else self._new_sid(conn, entry)
            conn.modify(self.s.user_dn(uid), smb_password_mods(entry, sid, hashed, int(time.time())))

    def set_own_smb_password(self, uid: str, password: str) -> None:
        """The account's SMB password, as the person: the site sign-in has no LDAP identity of its own, so
        it binds with a ticket from the password just set and writes the person's own hash. The entry must
        have its SMB account already (the portal adds it when it makes the account or sets a password)."""
        import gssapi
        from gssapi.raw import acquire_cred_with_password

        hashed = ntlm.nt_hash(password)
        name = gssapi.Name(self.s.principal(uid), gssapi.NameType.kerberos_principal)
        try:
            creds = gssapi.Credentials(acquire_cred_with_password(name, password.encode(), usage="initiate").creds)
        except gssapi.exceptions.GSSError as e:
            raise DirectoryError(f"no ticket for {uid} with the new password: {e}") from e
        with self._conn(creds) as conn:
            conn.modify(self.s.user_dn(uid), own_password_mods(hashed, int(time.time())))

    def set_smb_enabled(self, uid: str, enabled: bool) -> None:
        """The disabled flag of the account's SMB side; nothing when it has none."""
        with self._conn() as conn:
            entry = self._smb_entry(conn, uid)
            if has_smb(entry):
                flags = ntlm.flags_with(str(_first(entry, "sambaAcctFlags")), disabled=not enabled)
                conn.modify(self.s.user_dn(uid), {"sambaAcctFlags": [(MODIFY_REPLACE, [flags])]})

    # ---- projects: the groups people make themselves, under the projects' OU (portal/projects.py) ----

    def _to_project(self, dn: str, a: dict) -> Project:
        return Project(cn=_first(a, "cn"), dn=dn, gid_number=int(_first(a, "gidNumber", 0) or 0),
                       members=sorted(a.get("memberUid") or []), description=_first(a, "description"))

    def list_projects(self) -> list[Project]:
        with self._conn() as conn:
            try:
                conn.search(self.s.projects_ou, "(objectClass=posixGroup)", LEVEL, attributes=PROJECT_ATTRS)
            except LDAPNoSuchObjectResult:
                return []  # the OU is not made yet: no projects
            return sorted((self._to_project(r["dn"], r["attributes"]) for r in conn.response
                           if r.get("type") == "searchResEntry"), key=lambda p: p.cn)

    def get_project(self, cn: str) -> Project | None:
        with self._conn() as conn:
            try:
                conn.search(self.s.project_dn(cn), "(objectClass=posixGroup)", BASE, attributes=PROJECT_ATTRS)
            except LDAPNoSuchObjectResult:
                return None
            if not conn.response:
                return None
            r = conn.response[0]
            return self._to_project(r["dn"], r["attributes"])

    def projects_of(self, uid: str) -> list[str]:
        with self._conn() as conn:
            try:
                conn.search(self.s.projects_ou, f"(&(objectClass=posixGroup)(memberUid={escape_filter_chars(uid)}))",
                            LEVEL, attributes=["cn"])
            except LDAPNoSuchObjectResult:
                return []
            return sorted(_first(e.entry_attributes_as_dict, "cn") for e in conn.entries)

    def _next_gid(self, conn, spent: set[int]) -> int:
        """Smallest free gidNumber in the projects' range (the users' private groups have theirs: uid = gid),
        never one `spent` by a deleted project (the portal remembers those: files keep their gid)."""
        used: set[int] = set(spent)
        for r in conn.extend.standard.paged_search(self.s.base_dn, "(objectClass=posixGroup)", SUBTREE,
                                                   attributes=["gidNumber"], paged_size=500, generator=True):
            if r.get("type") == "searchResEntry" and _first(r["attributes"], "gidNumber", None) is not None:
                used.add(int(_first(r["attributes"], "gidNumber")))
        for n in range(self.s.project_gid_min, self.s.project_gid_max + 1):
            if n not in used:
                return n
        raise DirectoryError("No free gidNumber left in the projects' range.")

    def create_project(self, cn: str, description: str, members: list[str], spent: set[int] = frozenset()) -> Project:
        """The group, with its first members. The name must be free among users and groups alike:
        it names the share and the path too."""
        with self._id_lock, self._conn() as conn:
            name = escape_filter_chars(cn)
            conn.search(self.s.base_dn, f"(|(uid={name})(&(objectClass=posixGroup)(cn={name})))", SUBTREE,
                        attributes=[NO_ATTRIBUTES])
            if any(r.get("type") == "searchResEntry" for r in conn.response):
                raise DirectoryError(f"'{cn}' already exists (as a user or group).")
            attrs: dict = {"cn": cn, "gidNumber": self._next_gid(conn, set(spent)), "memberUid": list(members)}
            if description:
                attrs["description"] = description
            try:
                conn.add(self.s.project_dn(cn), ["posixGroup"], attrs)
            except LDAPNoSuchObjectResult as e:
                raise DirectoryError(f"{self.s.projects_ou} does not exist: the directory's admin makes it "
                                     "(the installer renders projects.ldif)") from e
        return self.get_project(cn)

    def delete_project(self, cn: str) -> None:
        """The group goes, and with it every membership; files it owned keep its gid."""
        with self._conn() as conn:
            try:
                conn.delete(self.s.project_dn(cn))
            except LDAPNoSuchObjectResult:
                pass

    def set_project_member(self, cn: str, uid: str, member: bool) -> None:
        with self._conn() as conn:
            conn.modify(self.s.project_dn(cn), {"memberUid": [(MODIFY_ADD if member else MODIFY_DELETE, [uid])]})

    def set_project_description(self, cn: str, description: str) -> None:
        with self._conn() as conn:
            conn.modify(self.s.project_dn(cn), {"description": [(MODIFY_REPLACE, [description] if description else [])]})
