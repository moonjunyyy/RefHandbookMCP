"""Who is in what, as the system sees it: NSS (the directory's posixGroups, through nslcd or sssd).

The services the sign-in fronts hold only a uid (the token's `sub`): what a person may see of a group's
things — the main page's cards, a project's calendar — they ask here, on every request, so a change in
the directory holds at once. Nothing on failure: an unknown account is in no group.

A project (docs/projects.md) is a posixGroup whose gid lies in the projects' range: that is how a
service tells a person's projects from their other groups without the directory's credentials.
"""

from __future__ import annotations

import grp
import os
import pwd


def groups_of(uid: str) -> set[str]:
    """The user's groups (names) as NSS sees them; empty for an unknown user."""
    try:
        pw = pwd.getpwnam(uid)
        return {grp.getgrgid(g).gr_name for g in os.getgrouplist(uid, pw.pw_gid)}
    except (KeyError, OSError):
        return set()


def project_groups_of(uid: str, gid_min: int, gid_max: int) -> set[str]:
    """The user's projects: their groups whose gid is in the projects' range [gid_min, gid_max]."""
    try:
        pw = pwd.getpwnam(uid)
        out = set()
        for g in os.getgrouplist(uid, pw.pw_gid):
            if gid_min <= g <= gid_max:
                out.add(grp.getgrgid(g).gr_name)
        return out
    except (KeyError, OSError):
        return set()


def members_of(group: str) -> list[str]:
    """The members of a group (names) as NSS sees it; empty for an unknown group."""
    try:
        return sorted(grp.getgrnam(group).gr_mem)
    except KeyError:
        return []
