"""What a signed-in person can do to accounts, once, for the pages and the API alike.

Every operation checks who may do it (rbac), validates what it is given (validators), does it
(directory, kerberos, kadmin, the request and invitation stores) and records it (audit). The pages
render the result and the API returns it as JSON; neither repeats any of this.

Refusals: Forbidden (not allowed, or nothing there), ValidationError (a value the person can fix).
A failure of a backend (DirectoryError, KerberosError) propagates as it is: the caller shows a
reference and the audit log keeps the words.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import audit, validators
from .config import Settings
from .directory import DirectoryError, User
from .invites import InviteError, InviteStore
from .kerberos import KerberosError
from .rbac import Actor, can, roles_for
from .requests import RequestStore
from .security import Throttle
from .validators import ValidationError


class Forbidden(Exception):
    """Not allowed, not enabled here, or not there (the same answer: it tells no one what exists)."""


@dataclass
class Accounts:
    s: Settings
    directory: Any
    kerberos: Any
    kadmin: Any
    requests: RequestStore | None
    invites: InviteStore | None
    throttle: Throttle

    # ── who ──────────────────────────────────────────────────────────────

    def actor(self, uid: str | None) -> Actor | None:
        """The signed-in person, re-read every time: a disabled account or a lost role counts at once."""
        if not uid:
            return None
        user = self.directory.get_user(uid)
        if user is None or user.disabled:
            return None
        return Actor(user=user, roles=roles_for(user, self.s))

    def require(self, actor: Actor, action: str, target: User | None = None) -> None:
        if not can(actor, action, self.s, target):
            raise Forbidden("이 작업을 할 권한이 없습니다.")

    def may(self, actor: Actor, action: str, target: User | None = None) -> bool:
        return can(actor, action, self.s, target)

    def target(self, uid: str) -> User:
        try:
            user = self.directory.get_user(validators.uid(uid))
        except ValidationError:
            user = None
        if user is None:
            raise Forbidden("그런 사용자가 없습니다.")
        return user

    # ── oneself ──────────────────────────────────────────────────────────

    def update_profile(self, actor: Actor, values: dict[str, Any], ip: str) -> User:
        changes = {
            "displayName": validators.optional_name(str(values.get("displayName", "")), "표시 이름"),
            "mail": validators.email(str(values.get("mail", ""))),
            "loginShell": validators.shell(str(values.get("loginShell", "")), self.s.allowed_shells),
        }
        self.directory.update_self(actor.uid, changes)
        audit.record(actor.uid, "update_profile", actor.uid, True, ip, ",".join(changes))
        return self.directory.get_user(actor.uid)

    def change_password(self, actor: Actor, old: str, new: str, confirm: str, ip: str) -> None:
        """Raises Forbidden while throttled, ValidationError or KerberosError with the reason."""
        key = f"pw:{actor.uid}"
        if self.throttle.blocked(key):
            raise Forbidden("실패가 너무 많습니다. 15분 뒤 다시 시도하세요.")
        try:
            pw = validators.new_password(new, confirm)
            self.kerberos.change_own_password(self.s.principal(actor.uid), old, pw)
        except (ValidationError, KerberosError) as e:
            self.throttle.fail(key)
            audit.record(actor.uid, "change_password", actor.uid, False, ip, str(e))
            raise
        audit.record(actor.uid, "change_password", actor.uid, True, ip)

    # ── accounts ─────────────────────────────────────────────────────────

    def make_account(self, by: str, uid: str, name: str, mail: str, shell: str, password: str, needchange: bool,
                     ip: str, detail: str = "") -> User:
        """The directory entry, then the Kerberos principal; the entry is rolled back if that fails."""
        user = self.directory.create_user(uid, name, mail, shell)
        try:
            self.kadmin.create_principal(self.s.principal(uid), user.dn, password, self.s.principal_alias(uid),
                                         needchange)
        except KerberosError as e:
            self.directory.rollback_user(uid)
            audit.record(by, "create_user", uid, False, ip, str(e))
            raise
        audit.record(by, "create_user", uid, True, ip, f"uidNumber={user.uid_number}" + (f" {detail}" if detail else ""))
        return user

    def create(self, actor: Actor, values: dict[str, Any], ip: str, detail: str = "") -> tuple[User, str]:
        """An account made by an admin, with a one-time password (returned once, never kept)."""
        self.require(actor, "create_user")
        uid = validators.new_uid(str(values.get("uid", "")))
        name = validators.optional_name(str(values.get("name", "")), "이름")
        mail = validators.email(str(values.get("mail", "")))
        shell = validators.shell(str(values.get("loginShell", "")), self.s.allowed_shells)
        password = validators.temp_password()
        return self.make_account(actor.uid, uid, name, mail, shell, password, True, ip, detail), password

    def users(self, actor: Actor, q: str = "") -> list[User]:
        self.require(actor, "view_users")
        return self.directory.search_users(q[:64])

    def user(self, actor: Actor, uid: str) -> User:
        self.require(actor, "view_users")
        return self.target(uid)

    def groups(self, actor: Actor) -> list[tuple[str, int]]:
        self.require(actor, "view_users")
        return self.directory.list_groups()

    def reset_password(self, actor: Actor, uid: str, ip: str) -> tuple[User, str]:
        target = self.target(uid)
        self.require(actor, "reset_password", target)
        password = validators.temp_password()
        self.kadmin.reset_password(self.s.principal(target.uid), password)
        audit.record(actor.uid, "reset_password", target.uid, True, ip)
        return target, password

    def unlock(self, actor: Actor, uid: str, ip: str) -> User:
        target = self.target(uid)
        self.require(actor, "unlock", target)
        self.kadmin.unlock(self.s.principal(target.uid))
        audit.record(actor.uid, "unlock", target.uid, True, ip)
        return target

    def set_enabled(self, actor: Actor, uid: str, enabled: bool, ip: str) -> User:
        target = self.target(uid)
        self.require(actor, "set_enabled", target)
        self.kadmin.set_enabled(self.s.principal(target.uid), enabled)
        audit.record(actor.uid, "enable" if enabled else "disable", target.uid, True, ip)
        return self.directory.get_user(target.uid)

    def set_group(self, actor: Actor, uid: str, group: str, member: bool, ip: str) -> User:
        target = self.target(uid)
        self.require(actor, "manage_groups", target)
        try:
            group = validators.group(group)
        except ValidationError as e:
            raise Forbidden(str(e)) from e
        if group == target.uid or group not in {g for g, _ in self.directory.list_groups()}:
            raise Forbidden("이 그룹은 여기서 바꿀 수 없습니다.")
        self.directory.set_membership(group, target.uid, member)
        audit.record(actor.uid, "group_add" if member else "group_remove", target.uid, True, ip, group)
        return self.directory.get_user(target.uid)

    def delete(self, actor: Actor, uid: str, confirm: str, ip: str) -> User:
        """Delete an account for good: its directory entry (the kldap backend keeps the Kerberos
        principal and its alias in it, so they go with it), its private group and its memberships.
        `confirm` is the username typed again. Files it owns stay."""
        target = self.target(uid)
        self.require(actor, "delete_user", target)
        if confirm.strip() != target.uid:
            raise ValidationError(f"계정을 지우려면 사용자명({target.uid})을 그대로 입력하세요.")
        self.directory.delete_user(target.uid)
        audit.record(actor.uid, "delete_user", target.uid, True, ip,
                     f"uidNumber={target.uid_number} groups={','.join(target.groups)}")
        return target

    # ── account requests and invitations ─────────────────────────────────

    def _requests(self) -> RequestStore:
        if self.requests is None:
            raise Forbidden("이 사이트는 사용 신청을 받지 않습니다.")
        return self.requests

    def _invites(self) -> InviteStore:
        if self.invites is None:
            raise Forbidden("이 사이트는 초대 링크를 쓰지 않습니다.")
        return self.invites

    def pending_requests(self, actor: Actor) -> list[Any]:
        self.require(actor, "review_requests")
        return self._requests().list()

    def _pending(self, rid: str) -> Any:
        r = self._requests().get(rid[:32])
        if r is None:
            raise Forbidden("그 신청은 더 이상 없습니다 (승인·거절되었거나 기한이 지났습니다).")
        return r

    def approve_request(self, actor: Actor, rid: str, shell: str, ip: str) -> tuple[User, str]:
        self.require(actor, "review_requests")
        self.require(actor, "create_user")
        r = self._pending(rid)
        try:
            uid = validators.new_uid(r.uid)
            shell = validators.shell(shell, self.s.allowed_shells)
        except ValidationError as e:
            raise Forbidden(str(e)) from e
        password = validators.temp_password()
        user = self.make_account(actor.uid, uid, r.name, r.mail, shell, password, True, ip, detail="from request")
        self._requests().delete(r.id)  # the request's copy of the personal data goes now
        return user, password

    def reject_request(self, actor: Actor, rid: str, ip: str) -> str:
        self.require(actor, "review_requests")
        r = self._pending(rid)
        self._requests().delete(r.id)
        audit.record(actor.uid, "reject_request", r.uid, True, ip)
        return r.uid

    def invitations(self, actor: Actor) -> list[Any]:
        self.require(actor, "manage_invites")
        return self._invites().list()

    def invite(self, actor: Actor, note: str, ip: str) -> tuple[Any, str]:
        """A sign-up link; returns the invitation and its token (shown once)."""
        self.require(actor, "manage_invites")
        self.require(actor, "create_user")
        note = " ".join(note.split())[:120]
        try:
            inv, token = self._invites().create(actor.uid, note)
        except InviteError as e:
            raise Forbidden(str(e)) from e
        audit.record(actor.uid, "create_invite", None, True, ip, f"id={inv.id}" + (f" {note}" if note else ""))
        return inv, token

    def revoke_invite(self, actor: Actor, iid: str, ip: str) -> bool:
        self.require(actor, "manage_invites")
        gone = self._invites().revoke(iid[:32])
        if gone:
            audit.record(actor.uid, "revoke_invite", None, True, ip, f"id={iid[:32]}")
        return gone


BACKEND_ERRORS: tuple[type[BaseException], ...] = (DirectoryError, KerberosError)
