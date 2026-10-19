"""Kerberos side: login verification, self password change (kpasswd) and admin actions (kadmin).

Passwords never appear on a command line: kpasswd/kadmin are driven through a pty with pexpect
and every child runs with a private in-memory credential cache.
"""
import enum
import os
import re

import pexpect

from .config import Settings

# kadmin error lines look like: 'add_principal: Principal or policy already exists while creating "x".'
_KADMIN_ERROR = re.compile(r"^[a-z_]+: .+ while .+$", re.MULTILINE)
_KRB5KDC_ERR_KEY_EXP = -1765328361        # password expired / +needchange
_KRB5KDC_ERR_CLIENT_REVOKED = -1765328366  # disabled or locked out


class KerberosError(Exception):
    pass


class LoginResult(enum.Enum):
    OK = "ok"
    BAD = "bad"
    EXPIRED = "expired"
    REVOKED = "revoked"


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "KRB5_CONFIG")}
    env["KRB5CCNAME"] = "MEMORY:"
    env["LC_ALL"] = "C"  # stable, English prompts to match against
    return env


class Kerberos:
    def __init__(self, settings: Settings):
        self.s = settings

    def verify_password(self, principal: str, password: str) -> LoginResult:
        """Get a TGT with the password, then a ticket for our own HTTP service and decrypt it with
        our keytab. The second step proves the answer came from the real KDC (no KDC spoofing)."""
        import gssapi
        from gssapi.raw import acquire_cred_with_password

        name = gssapi.Name(principal, gssapi.NameType.kerberos_principal)
        try:
            acquired = acquire_cred_with_password(name, password.encode(), usage="initiate")
        except gssapi.exceptions.GSSError as e:
            if e.min_code == _KRB5KDC_ERR_KEY_EXP:
                return LoginResult.EXPIRED
            if e.min_code == _KRB5KDC_ERR_CLIENT_REVOKED:
                return LoginResult.REVOKED
            return LoginResult.BAD
        try:
            target = gssapi.Name(self.s.http_service, gssapi.NameType.hostbased_service)
            initiator = gssapi.SecurityContext(name=target, creds=gssapi.Credentials(acquired.creds),
                                               usage="initiate")
            acceptor = gssapi.SecurityContext(
                creds=gssapi.Credentials(usage="accept", store={"keytab": self.s.http_keytab}),
                usage="accept")
            acceptor.step(initiator.step())
        except gssapi.exceptions.GSSError as e:
            raise KerberosError(f"KDC verification against {self.s.http_service} failed: {e}") from e
        if not acceptor.complete or str(acceptor.initiator_name) != principal:
            return LoginResult.BAD
        return LoginResult.OK

    def change_own_password(self, principal: str, old: str, new: str) -> None:
        """kpasswd with the user's old password. Needs no admin rights and works for expired passwords."""
        child = pexpect.spawn("kpasswd", [principal], env=_child_env(), encoding="utf-8", timeout=20)
        try:
            child.expect(r"(?i)password for .*:")
            child.sendline(old)
            i = child.expect([r"(?i)enter new password:", r"(?i)(incorrect|failed|error).*", pexpect.EOF])
            if i != 0:
                raise KerberosError("Current password is incorrect.")
            child.sendline(new)
            child.expect(r"(?i)enter it again:")
            child.sendline(new)
            child.expect(pexpect.EOF)
            out = child.before or ""
        except pexpect.TIMEOUT as e:
            raise KerberosError("Password service did not respond.") from e
        finally:
            child.close()
        if "Password changed" not in out:
            # e.g. "Password change rejected: Password is too short."
            msg = out.strip().splitlines()[-1] if out.strip() else "Password change failed."
            raise KerberosError(msg.replace("\r", ""))


class KAdmin:
    """Runs single kadmin queries as the portal service principal.

    What this principal may do is limited by kadm5.acl on the KDC (see deploy/kadm5.acl), so a
    compromised portal still cannot touch */admin, krbtgt or kadmin principals."""

    def __init__(self, settings: Settings):
        self.s = settings

    def _run(self, query: str, passwords: tuple[str, ...] = ()) -> str:
        args = ["-k", "-t", self.s.service_keytab, "-p", self.s.service_principal, "-r", self.s.realm, "-q", query]
        child = pexpect.spawn("kadmin", args, env=_child_env(), encoding="utf-8", timeout=30)
        try:
            for pw in passwords:
                child.expect(r"(?i)password for principal .*:")
                child.sendline(pw)
            child.expect(pexpect.EOF)
            out = child.before or ""
        except pexpect.TIMEOUT as e:
            raise KerberosError("kadmin timed out.") from e
        finally:
            child.close()
        err = _KADMIN_ERROR.search(out)
        if err or child.exitstatus not in (0, None):
            raise KerberosError(err.group(0).strip() if err else f"kadmin failed ({query.split()[0]}).")
        return out

    def create_principal(self, principal: str, dn: str, password: str, alias: str | None) -> None:
        policy = f"-policy {self.s.kadmin_policy} " if self.s.kadmin_policy else ""
        # -x dn= attaches the principal to the existing LDAP user entry (kldap backend).
        self._run(f'addprinc {policy}+needchange -x "dn={dn}" {principal}', (password, password))
        if alias:
            try:
                self._run(f"add_alias {alias} {principal}")
            except KerberosError:
                self.delete_principal(principal)  # only ever deletes the principal created just above
                raise

    def delete_principal(self, principal: str) -> None:
        self._run(f"delprinc -force {principal}")

    def reset_password(self, principal: str, password: str) -> None:
        self._run(f"cpw {principal}", (password, password))
        self._run(f"modprinc +needchange {principal}")

    def unlock(self, principal: str) -> None:
        self._run(f"modprinc -unlock {principal}")

    def set_enabled(self, principal: str, enabled: bool) -> None:
        self._run(f"modprinc {'+' if enabled else '-'}allow_tix {principal}")
