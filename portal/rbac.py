"""Who may do what. This is the app-level check; kadm5.acl and slapd olcAccess are the backstop
that still holds if the portal itself is compromised."""
from dataclasses import dataclass

from .config import Settings
from .directory import User

# action -> roles allowed
PERMISSIONS = {
    "view_users": {"helpdesk", "admin"},
    "reset_password": {"helpdesk", "admin"},
    "unlock": {"helpdesk", "admin"},
    "create_user": {"admin"},
    "set_enabled": {"admin"},
    "manage_groups": {"admin"},
    "review_requests": {"admin"},
}
# Actions that would let you lock yourself (or the last admin) out.
NOT_ON_SELF = {"set_enabled", "manage_groups", "reset_password"}


@dataclass
class Actor:
    user: User
    roles: set[str]

    @property
    def uid(self) -> str:
        return self.user.uid


def roles_for(user: User, s: Settings) -> set[str]:
    roles = {"user"}
    if s.admin_group in user.groups:
        roles.add("admin")
    if s.helpdesk_group in user.groups:
        roles.add("helpdesk")
    return roles


def can(actor: Actor, action: str, s: Settings, target: User | None = None) -> bool:
    if not actor.roles & PERMISSIONS[action]:
        return False
    if target is None:
        return True
    if target.uid == actor.uid and action in NOT_ON_SELF:
        return False
    # Helpdesk can never touch admins or members of protected groups.
    if "admin" not in actor.roles and set(target.groups) & (set(s.protected_groups) | {s.admin_group}):
        return False
    return True
