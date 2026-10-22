"""The offered mount directories, staged for the sandbox (docs/kernel.md "Mounts").

The sandbox runs as the handbook's service user, and a user's files belong to the user: a plain bind
would let the sandbox read only what the world may read and write nothing. So root stages each offered
directory, for each user of the handbook, as an idmapped bind mount: through it the user's uid and gid
read as the service user's, and what the sandbox writes lands as the user's own. Nothing else is
mapped: files of anyone else keep only their "other" permissions.

    <stage>/<user>/<NAME>   the user's FROM (RHB_SANDBOX_MOUNTS: FROM=NAME[:ro]), idmapped user ↔ service

`refhandbook mounts` does it, as root, from <name>-mounts.service (a timer runs it every few minutes,
so a new user's directories appear without anyone acting). The stage is root's (/run/<name>-mounts),
never under the service's own data directory, where the service could swap a path for a symlink
between root's checks and root's mount.

Who is staged: users with a handbook store (<data>/users/<uid>.db) whose account has a uid of at least
UID_MIN (login.defs), is in RHB_REQUIRE_GROUP if one is set, and owns the directory FROM resolves to.
The store names come from the service's directory, so each is checked against the account database.

Standard library only: this runs as root before anything else of the handbook is needed.
"""

from __future__ import annotations

import grp
import json
import os
import pwd
import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
UID_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,63}$")
STATE = ".staged.json"


class MountError(ValueError):
    pass


@dataclass(frozen=True)
class Offer:
    """One entry of RHB_SANDBOX_MOUNTS: the host directory template FROM, offered as NAME."""
    template: str
    name: str
    ro: bool = False


def parse(text: str) -> list[Offer]:
    """RHB_SANDBOX_MOUNTS: comma-separated FROM=NAME[:ro]."""
    out: list[Offer] = []
    for entry in filter(None, (x.strip() for x in text.split(","))):
        frm, sep, to = entry.partition("=")
        name, _, mode = to.partition(":")
        name = name.strip().strip("/")
        if not sep or not frm.strip().startswith("/") or not NAME_RE.match(name) or mode not in ("", "ro"):
            raise MountError(f"RHB_SANDBOX_MOUNTS: {entry!r} is not FROM=NAME[:ro] (FROM an absolute path, NAME "
                             "letters, digits, . _ -)")
        if any(o.name == name for o in out):
            raise MountError(f"RHB_SANDBOX_MOUNTS: the name {name!r} is used twice")
        out.append(Offer(frm.strip(), name, mode == "ro"))
    return out


def offers() -> list[Offer]:
    return parse(os.environ.get("RHB_SANDBOX_MOUNTS", ""))


def stage_root() -> Path | None:
    """Where the staged mounts are (RHB_SANDBOX_MOUNT_STAGE, set in the handbook's units); None: no
    staging (a local server), the sandbox binds FROM itself."""
    v = os.environ.get("RHB_SANDBOX_MOUNT_STAGE", "")
    return Path(v) if v else None


def expand(template: str, user: str, uid: int) -> str:
    try:
        return os.path.realpath(template.format(user=user, uid=uid))
    except (KeyError, IndexError, ValueError) as e:
        raise MountError(f"RHB_SANDBOX_MOUNTS: bad template {template!r}: {e}") from e


def uid_min(path: str = "/etc/login.defs") -> int:
    try:
        for line in Path(path).read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "UID_MIN":
                return int(parts[1])
    except (OSError, ValueError):
        pass
    return 1000


@dataclass(frozen=True)
class Stage:
    user: str
    uid: int
    gid: int
    host: str
    target: str
    ro: bool


def _in_group(pw: pwd.struct_passwd, group: str) -> bool:
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        return False
    return pw.pw_gid == gid or gid in os.getgrouplist(pw.pw_name, pw.pw_gid)


def plan(data_dir: Path, stage: Path, service_uid: int, offered: list[Offer], *, min_uid: int | None = None,
         group: str | None = None, getpw: Callable[[str], pwd.struct_passwd] = pwd.getpwnam,
         in_group: Callable[[pwd.struct_passwd, str], bool] = _in_group) -> tuple[list[Stage], list[str]]:
    """What should be staged now, and why anything was left out."""
    min_uid = uid_min() if min_uid is None else min_uid
    stages, skipped = [], []
    users = sorted(p.stem for p in (data_dir / "users").glob("*.db") if not p.name.startswith("._"))
    for user in users:
        if not UID_RE.match(user):
            skipped.append(f"{user}: not an account name")
            continue
        try:
            pw = getpw(user)
        except KeyError:
            skipped.append(f"{user}: no such account")
            continue
        if pw.pw_uid < min_uid or pw.pw_uid == service_uid:
            skipped.append(f"{user}: uid {pw.pw_uid} is a system account's")
            continue
        if group and not in_group(pw, group):
            skipped.append(f"{user}: not in {group}")
            continue
        for o in offered:
            host = expand(o.template, user, pw.pw_uid)
            try:
                st = os.stat(host)
            except OSError:
                continue  # this user has no such directory: nothing to offer
            if not os.path.isdir(host):
                skipped.append(f"{user}/{o.name}: {host} is not a directory")
            elif st.st_uid != pw.pw_uid:
                skipped.append(f"{user}/{o.name}: {host} belongs to uid {st.st_uid}, not {user}")
            else:
                stages.append(Stage(user, pw.pw_uid, pw.pw_gid, host, str(stage / user / o.name), o.ro))
    return stages, skipped


def mounted(under: Path, mountinfo: str = "/proc/self/mountinfo") -> set[str]:
    """The mount points at or below `under`."""
    out = set()
    root = str(under).rstrip("/")
    for line in Path(mountinfo).read_text().splitlines():
        parts = line.split()
        if len(parts) > 4:
            point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[4])
            if point == root or point.startswith(root + "/"):
                out.add(point)
    return out


def idmap(s: Stage, service_uid: int, service_gid: int) -> str:
    """The user's uid and gid read as the service's through the mount (u:<in mount>:<on disk>:1)."""
    return f"u:{service_uid}:{s.uid}:1 g:{service_gid}:{s.gid}:1"


def apply(stages: list[Stage], stage: Path, service_uid: int, service_gid: int,
          run: Callable[[list[str]], int] = lambda c: subprocess.run(c).returncode,
          mountinfo: str = "/proc/self/mountinfo") -> list[str]:
    """Make the stage match the plan: mount what is missing or changed, unmount what is no longer
    offered. Returns what it did."""
    stage.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chmod(stage, 0o755)
    state_file = stage / STATE
    try:
        before = json.loads(state_file.read_text())
    except (OSError, ValueError):
        before = {}
    now = mounted(stage, mountinfo)
    want = {s.target: s for s in stages}
    done, after = [], {}
    for target in sorted(now - {str(stage)}, key=len, reverse=True):
        rec = want.get(target)
        if rec is None or before.get(target) != asdict(rec):
            if run(["umount", "--lazy", target]) == 0:
                done.append(f"unmounted {target}")
                now.discard(target)
    for target, s in want.items():
        if target in now:
            after[target] = asdict(s)
            continue
        user_dir = Path(target).parent
        user_dir.mkdir(mode=0o755, exist_ok=True)
        Path(target).mkdir(mode=0o755, exist_ok=True)
        opts = f"X-mount.idmap={idmap(s, service_uid, service_gid)}" + (",ro" if s.ro else "")
        if run(["mount", "--bind", "-o", opts, s.host, target]) == 0:
            done.append(f"mounted {s.host} at {target}" + (" (ro)" if s.ro else ""))
            after[target] = asdict(s)
        else:
            done.append(f"could not mount {s.host} at {target}")
    for d in sorted(stage.iterdir()) if stage.exists() else []:  # empty leftovers of users no longer staged
        if d.is_dir() and not d.is_symlink():
            for t in sorted(d.iterdir()):
                if t.is_dir() and str(t) not in after and str(t) not in now:
                    t.rmdir()
            if not any(d.iterdir()):
                d.rmdir()
    tmp = state_file.with_suffix(".new")
    tmp.write_text(json.dumps(after, indent=1, sort_keys=True))
    tmp.replace(state_file)
    return done


def main(data_dir: str, service_user: str, stage: str, check: bool = False) -> int:
    """`refhandbook mounts`: stage the offered directories (root), or with --check print the plan."""
    pw = pwd.getpwnam(service_user)
    try:
        offered = offers()
    except MountError as e:
        print(f"error: {e}")
        return 2
    stages, skipped = plan(Path(data_dir), Path(stage), pw.pw_uid, offered,
                           group=os.environ.get("RHB_REQUIRE_GROUP") or None)
    for line in skipped:
        print(f"skipped {line}")
    if check:
        for s in stages:
            print(f"{s.host} -> {s.target} as {s.user} ({idmap(s, pw.pw_uid, pw.pw_gid)}){' ro' if s.ro else ''}")
        return 0
    if os.geteuid() != 0:
        print("error: staging mounts needs root (or run with --check)")
        return 1
    for line in apply(stages, Path(stage), pw.pw_uid, pw.pw_gid):
        print(line)
    return 0
