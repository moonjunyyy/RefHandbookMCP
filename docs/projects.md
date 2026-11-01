# Projects: groups people make themselves (src/portal/projects.py)

A person is a group of one — every account already has its private group (`cn=<uid>`, gid = uid).
A project is a group of more than one, made by its members through the portal. Everything a
project gets afterwards is what a group gets: a storage root, a share, a vault, a calendar; a
person's own are those of their private group. So the site adds one thing, the life of a group
people make, and the rest hangs off it:

| of a group G | a person (G = their private group) | a project |
|---|---|---|
| storage root | their own data directory (`/data/<uid>`) | `<projects_root>/<cn>` (its sibling; the provisioner, below) |
| SMB share | `[homes]`, as today | `[<cn>]`, `valid users = @<cn>` (the provisioner) |
| vault (markdown) | a directory of their storage, which Obsidian opens | a directory of the project's |
| calendar | theirs | the project's |

The directory holds what every other system must see — the group, its gid, its members — and the
portal holds what only it decides: who owns a project, how one joins it, whether it is listed, the
join requests and the invitation links. A project is archived (reversible) or deleted for good.

## The group

`cn=<cn>,<projects_ou>` is a `posixGroup` (cn, gidNumber, memberUid, description) under
`ou=Projects,<groups_ou>` (`projects_ou`, in `[site]` or `PORTAL_PROJECTS_OU`). Under the groups'
OU, so NSS (nslcd's `base group`, sssd's search base; scope sub, the default) sees project groups as
any group and the file server, SMB and the sandbox resolve membership with nothing more; one level
below it, so the portal's role groups (`admin`, `helpdesk`, `user`, the private groups: a one-level
search) are never a project and a project is never a role. The gid comes from its own range,
`PORTAL_PROJECT_GID_MIN`–`MAX` (30000–39999: after the admins' 10000s and the users' 20000s, where
uid = gid), so it never takes a number a user would get. A name is unique across users and groups
(the directory refuses one that is taken), lowercase (`[a-z][a-z0-9_-]{1,31}`), not a reserved word
(a role group, an SMB section name such as `homes` or `global`), and cannot change: it names the
group, the share and the path.

The OU itself is made once by the directory's admin: the installer renders
`/etc/<name>/directory/projects.ldif` and the rules the portal needs into `slapd-acl.ldif` (the
portal may add entries under the OU and write their `cn`, `gidNumber`, `memberUid`, `description`,
nothing else, nowhere else).

## The record (PORTAL_PROJECTS_DB)

SQLite under `/var/lib/<name>-portal`, mode 0600, as the account requests and invitations: `projects`
(title, description, `join_policy`, `listed`, created, by, archived), `owners`, `requests`,
`invites` (the token's hash alone, as `portal/invites.py`). Owners are not in the directory because
`posixGroup` has no owner attribute, and mixing in `groupOfNames` would make these groups unlike
every other; membership is the directory's, policy is the portal's.

## Who may do what

| | user | member | owner | admin |
|---|---|---|---|---|
| make a project (`PORTAL_PROJECT_CREATE=user`, the default; `admin`: admins only) | ✓ | | | ✓ |
| see the listed ones; see one's own | ✓ | ✓ | ✓ | ✓, every one |
| join: at once (`open`), by a request an owner answers (`request`), by a link alone (`invite`) | ✓ | | | |
| leave | | ✓ | ✓ (not the last owner) | |
| add and remove members, answer requests, make and revoke links | | | ✓ | ✓ |
| change the title, description, policy, listing; make and unmake owners; archive, restore | | | ✓ | ✓ |
| delete, typing the name again (`DELETE projects/<cn>?confirm=<cn>`) | | | ✓ | ✓ |

An owner is a member who manages the project; there is always one (the last cannot leave, be
removed or step down: make another owner, or archive). A site admin manages every project and is a
member of none unless added. An archived project keeps its group and its members (their files stay
readable, and `getent group` still shows it) but takes no change and no new member until it is
restored; the provisioner withdraws its share. A deleted project is gone for good — its group (so
every membership), its record, its requests and links — except one thing the portal keeps: that its
gid was used, so no later project gets it and the files left with that gid belong to no one (as a
deleted account's files keep its uid). The name is free again. The same answer, "no such project",
goes to whoever may not see one. Every change is in the audit log (`project_create`,
`project_member_add`, `project_delete`, …).

Pages: `/projects` (mine, the listed others, a new one), `/projects/<cn>`, `/projects/join/<token>`
(an invitation link: the signed-in person joins). API: `/account/api/v1/projects` (`src/portal/projects_api.py`
lists the calls). Tests: `tests/portal/test_projects.py`.

## What comes next (not yet built)

1. **The provisioner** `<name>-provision`: a root reconciler shaped like `<name>-mounts` (oneshot +
   path + timer, `agents/mounts.py`) that reads the project groups and the record and makes the
   difference true: the storage root (a ZFS dataset `<projects_dataset>/<cn>` at
   `<projects_root>/<cn>`, or a directory; `root:<cn> 2770`; no quota unless `project_quota`),
   the SMB share (`/etc/samba/<name>-projects.conf`, one `[<cn>]` section each with `valid users =
   @<cn>`, `force group`, `create mask 0660`, `directory mask 2770`; reloaded only when it changed;
   `include`d once from `smb.conf` by the host's admin), optionally the NFS export. SMB
   authentication is not the portal's and stays as it is. `RHB_SANDBOX_MOUNTS` gains
   `<projects_root>/{group}=project`: `{group}` expands to each project of the user, and a mount is
   theirs when the directory is theirs or their group's.
2. **The vault** `<name>-vault` — built for a person's own storage (docs/vault.md: a web view and
   editor over a markdown directory, the same files Obsidian opens over SMB, with an index for
   search and links, staged idmapped for the service). A project's vault (a directory of the
   project's storage, for its members) waits for the provisioner's storage root; git history and
   the handbook's `files` reaching a vault through the policy mounts are not there yet.
3. **The calendar** `<name>-calendar` — built (docs/calendar.md: a calendar for a person and one for
   each of their projects, iCalendar events with repeats, an ICS feed for phones, the members'
   free/busy). Agents' schedules shown beside the events are not there yet.
