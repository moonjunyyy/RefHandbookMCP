"""The directories users mount into their sandbox, staged by root (docs/kernel.md "Mounts").

A user picks what to mount in a sandbox policy: a directory of their own, by its real path
(/data/moon/workspace), at a path inside the sandbox (/mnt/ws), read-only unless `rw`. The
administrator only says where users may pick from (RHB_SANDBOX_MOUNTS, below).

The sandbox runs as the handbook's service user, and the user's files are the user's: a plain bind
would let the sandbox read only what the world may and write nothing. So root stages each picked
directory as an idmapped bind mount: through it the user's uid and gid read as the service's, and
what the sandbox writes lands as the user's own. Nothing else is mapped.

    <stage>/<user>/<key>            the picked directory (key: a digest of its path), idmapped
    <stage>/<user>/.status.json     per picked path: "ok", or why it was not staged

`refhandbook mounts` does it, as root, from <name>-mounts.service: started when a policy is saved
(the handbook writes <data>/mount-requests, which <name>-mounts.path watches) and every minute by
<name>-mounts.timer. It reads each user's policies from their store, read-only. The stage is root's
(/run/<name>-mounts), never under the service's own directory.

What is staged: for users with a store whose account has a uid of at least UID_MIN (login.defs) and is
in RHB_REQUIRE_GROUP if one is set, each directory a policy of theirs names that lies, symlinks
resolved, under one of their offered roots and belongs to them.

RHB_SANDBOX_MOUNTS, comma-separated, each FROM[=NAME][:ro]:
    FROM   a directory users may pick inside ({user} and {uid} name the user), e.g. /data/{user}
    NAME   a short name for it, so a source may also be written NAME/sub/path (optional)
    :ro    never mounted read-write
Unset: /home/{user}.

Standard library only: this runs as root before anything else of the handbook is needed.
"""

from __future__ import annotations

import grp
import hashlib
import json
import os
import pwd
import re
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
UID_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,63}$")
STATE = ".staged.json"
STATUS = ".status.json"
DEFAULT = "/home/{user}"
REQUESTS = "mount-requests"  # in the handbook's data directory: written when a policy is saved


class MountError(ValueError):
    pass


@dataclass(frozen=True)
class Offer:
    """One entry of RHB_SANDBOX_MOUNTS: where users may pick from (FROM), its optional NAME."""
    template: str
    name: str = ""
    ro: bool = False


def parse(text: str) -> list[Offer]:
    """RHB_SANDBOX_MOUNTS: comma-separated FROM[=NAME][:ro]."""
    out: list[Offer] = []
    for entry in filter(None, (x.strip() for x in text.split(","))):
        ro = entry.endswith(":ro")
        body = entry[:-3] if ro else entry
        frm, sep, name = body.partition("=")
        frm, name = frm.strip(), name.strip().strip("/")
        if not frm.startswith("/") or (sep and not NAME_RE.match(name)) or ":" in name:
            raise MountError(f"RHB_SANDBOX_MOUNTS: {entry!r} is not FROM[=NAME][:ro] (FROM an absolute path, NAME "
                             "letters, digits, . _ -)")
        if name and any(o.name == name for o in out):
            raise MountError(f"RHB_SANDBOX_MOUNTS: the name {name!r} is used twice")
        out.append(Offer(frm, name, ro))
    return out


def offers(var: str = "RHB_SANDBOX_MOUNTS") -> list[Offer]:
    return parse(os.environ.get(var) or DEFAULT)


def stage_root() -> Path | None:
    """Where the staged mounts are (RHB_SANDBOX_MOUNT_STAGE, set in the handbook's units); None: no
    staging (a local server), the sandbox binds the directory itself."""
    v = os.environ.get("RHB_SANDBOX_MOUNT_STAGE", "")
    return Path(v) if v else None


def expand(template: str, user: str, uid: int) -> str:
    try:
        return os.path.normpath(template.format(user=user, uid=uid))
    except (KeyError, IndexError, ValueError) as e:
        raise MountError(f"RHB_SANDBOX_MOUNTS: bad template {template!r}: {e}") from e


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def source_path(source: str, offered: list[Offer], user: str, uid: int) -> tuple[str, Offer]:
    """A policy's mount source as a host path (lexically: no file is looked at), and the offered root
    it lies under. A source is a path (/data/moon/ws) or NAME/sub/path of a named offer."""
    try:
        s = source.strip().format_map({"user": user, "uid": uid}) if "{" in source else source.strip()
    except (KeyError, IndexError, ValueError) as e:
        raise MountError(f"{source}: {e}") from e
    if not s:
        raise MountError("an empty mount source")
    if s.startswith("/"):
        if ".." in s.split("/"):
            raise MountError(f"{source}: no '..'")
        host = os.path.normpath(s)
        for o in offered:
            if _under(host, expand(o.template, user, uid)):
                return host, o
        where = ", ".join(expand(o.template, user, uid) for o in offered) or "nowhere"
        raise MountError(f"{source} is not in a directory you may mount from ({where})")
    name, _, sub = s.partition("/")
    o = next((x for x in offered if x.name and x.name == name), None)
    if o is None:
        where = ", ".join(expand(x.template, user, uid) for x in offered) or "nowhere"
        raise MountError(f"{source}: write the directory's path, inside {where}")
    if ".." in sub.split("/"):
        raise MountError(f"{source}: no '..'")
    root = expand(o.template, user, uid)
    return (os.path.normpath(os.path.join(root, sub)) if sub else root), o


def key(host: str) -> str:
    return hashlib.sha256(host.encode()).hexdigest()[:16]


def staged_path(stage: Path, user: str, host: str) -> Path:
    return stage / user / key(host)


def status_of(stage: Path, user: str) -> dict[str, str]:
    """What root said of each path the user picked: "ok", or why it is not staged."""
    try:
        return json.loads((stage / user / STATUS).read_text())
    except (OSError, ValueError):
        return {}


def request(data_dir: Path) -> None:
    """Ask root to stage again now (the handbook, when a policy is saved): <name>-mounts.path watches
    this file. Best effort: the timer comes by within a minute anyway."""
    import time

    try:
        (data_dir / REQUESTS).write_text(f"{time.time()}\n")
    except OSError:
        pass


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


@dataclass
class Plan:
    stages: list[Stage] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # whole users, and why
    status: dict[str, dict[str, str]] = field(default_factory=dict)  # user → picked path → "ok" | why


def _in_group(pw: pwd.struct_passwd, group: str) -> bool:
    try:
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        return False
    return pw.pw_gid == gid or gid in os.getgrouplist(pw.pw_name, pw.pw_gid)


def picked(db: Path) -> list[tuple[str, bool]]:
    """The mount sources the store's policies name (source, rw), read-only."""
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute("SELECT attrs FROM k_nodes WHERE type = 'policy'").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    out = []
    for (attrs,) in rows:
        try:
            for m in json.loads(attrs).get("mounts") or []:
                if isinstance(m, dict) and isinstance(m.get("source"), str):
                    out.append((m["source"], bool(m.get("rw"))))
        except ValueError:
            continue
    return out


Picks = list[tuple[str, list[tuple[str, bool]]]]  # (user, [(source, rw)]) — what each user asked to have staged


def handbook_picks(data_dir: Path, sources: Callable[[Path], list[tuple[str, bool]]] = picked) -> Picks:
    """What the handbook's users picked in their policies: one store per user under <data>/users/."""
    return [(db.stem, sources(db)) for db in sorted(p for p in (data_dir / "users").glob("*.db") if not p.name.startswith("._"))]


def vault_picks(data_dir: Path) -> Picks:
    """What people registered as vaults (portal/vault.py: <data>/vault.db), each read-write."""
    db = data_dir / "vault.db"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute("SELECT uid, path FROM vaults ORDER BY uid, path").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    by: dict[str, list[tuple[str, bool]]] = {}
    for uid, path in rows:
        by.setdefault(uid, []).append((path, True))
    return sorted(by.items())


PICKS: dict[str, Callable[[Path], Picks]] = {"handbook": handbook_picks, "vault": vault_picks}


def plan(data_dir: Path, stage: Path, service_uid: int, offered: list[Offer], *, min_uid: int | None = None,
         group: str | None = None, getpw: Callable[[str], pwd.struct_passwd] = pwd.getpwnam,
         in_group: Callable[[pwd.struct_passwd, str], bool] = _in_group,
         sources: Callable[[Path], list[tuple[str, bool]]] = picked,
         picks: Callable[[Path], Picks] | None = None) -> Plan:
    """What should be staged now: every directory a user picked (a policy's mounts, a registered vault)
    that is theirs to pick."""
    min_uid = uid_min() if min_uid is None else min_uid
    out = Plan()
    for user, wanted in (picks(data_dir) if picks else handbook_picks(data_dir, sources)):
        if not UID_RE.match(user):
            out.skipped.append(f"{user}: not an account name")
            continue
        try:
            pw = getpw(user)
        except KeyError:
            out.skipped.append(f"{user}: no such account")
            continue
        if pw.pw_uid < min_uid or pw.pw_uid == service_uid:
            out.skipped.append(f"{user}: uid {pw.pw_uid} is a system account's")
            continue
        if group and not in_group(pw, group):
            out.skipped.append(f"{user}: not in {group}")
            continue
        status: dict[str, str] = {}
        for source, rw in wanted:
            try:
                host, offer = source_path(source, offered, user, pw.pw_uid)
            except MountError as e:
                status[source] = str(e)
                continue
            if host in status:
                continue
            real = os.path.realpath(host)
            root = os.path.realpath(expand(offer.template, user, pw.pw_uid))
            if not _under(real, root):  # a symlink inside leads out
                status[host] = f"{host} leads outside {expand(offer.template, user, pw.pw_uid)}"
                continue
            try:
                st = os.stat(real)
            except OSError:
                status[host] = f"{host} does not exist"
                continue
            if not os.path.isdir(real):
                status[host] = f"{host} is not a directory"
            elif st.st_uid != pw.pw_uid:
                status[host] = f"{host} is not yours (it belongs to uid {st.st_uid})"
            elif rw and offer.ro:
                status[host] = f"{host} may only be mounted read-only"
            else:
                status[host] = "ok"
                out.stages.append(Stage(user, pw.pw_uid, pw.pw_gid, real, str(staged_path(stage, user, host)),
                                        offer.ro))
        out.status[user] = status
    return out


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
    """The user's uid and gid read as the service's through the mount, and the service's writes land as
    the user's. The kernel looks a file's owner on disk up in the mapping's first column and shows the
    second (map_id_down over the mount's user namespace, whose uid_map util-linux writes as given), so
    the user's id comes first: u:<on disk>:<seen in the mount>:1. (mount(8) names the columns the other
    way round; the other order leaves every file of the user unmapped, as nobody.)"""
    return f"u:{s.uid}:{service_uid}:1 g:{s.gid}:{service_gid}:1"


def apply(p: Plan, stage: Path, service_uid: int, service_gid: int,
          run: Callable[[list[str]], int] = lambda c: subprocess.run(c).returncode,
          mountinfo: str = "/proc/self/mountinfo") -> list[str]:
    """Make the stage match the plan: mount what is missing or changed, unmount what is no longer
    picked, and write each user's status. Returns what it did."""
    stage.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chmod(stage, 0o755)
    state_file = stage / STATE
    try:
        before = json.loads(state_file.read_text())
    except (OSError, ValueError):
        before = {}
    now = mounted(stage, mountinfo)
    want = {s.target: s for s in p.stages}

    def record(s: Stage) -> dict:  # what a mount was made with: a change of any of it mounts it again
        return {**asdict(s), "idmap": idmap(s, service_uid, service_gid)}

    done, after = [], {}
    for target in sorted(now - {str(stage)}, key=len, reverse=True):
        rec = want.get(target)
        if rec is None or before.get(target) != record(rec):
            if run(["umount", "--lazy", target]) == 0:
                done.append(f"unmounted {target}")
                now.discard(target)
    for target, s in want.items():
        if target in now:
            after[target] = record(s)
            continue
        user_dir = Path(target).parent
        user_dir.mkdir(mode=0o755, exist_ok=True)
        Path(target).mkdir(mode=0o755, exist_ok=True)
        opts = f"X-mount.idmap={idmap(s, service_uid, service_gid)}" + (",ro" if s.ro else "")
        if run(["mount", "--bind", "-o", opts, s.host, target]) == 0:
            done.append(f"mounted {s.host} at {target}" + (" (ro)" if s.ro else ""))
            after[target] = record(s)
        else:
            done.append(f"could not mount {s.host} at {target}")
            for user, st in p.status.items():
                for host, v in st.items():
                    if v == "ok" and str(staged_path(stage, user, host)) == target:
                        st[host] = "the mount failed (see the server's log)"
    for user, st in p.status.items():  # what became of each picked path, for the policy page
        d = stage / user
        d.mkdir(mode=0o755, exist_ok=True)
        tmp = d / (STATUS + ".new")
        tmp.write_text(json.dumps(st, indent=1, sort_keys=True, ensure_ascii=False))
        os.chmod(tmp, 0o644)
        tmp.replace(d / STATUS)
    for d in sorted(stage.iterdir()) if stage.exists() else []:  # empty leftovers of what is no longer picked
        if d.is_dir() and not d.is_symlink():
            for t in sorted(d.iterdir()):
                if t.is_dir() and str(t) not in after and str(t) not in now:
                    t.rmdir()
            if d.name not in p.status and not any(x for x in d.iterdir() if x.name != STATUS):
                for x in d.iterdir():
                    x.unlink()
                d.rmdir()
    tmp = state_file.with_suffix(".new")
    tmp.write_text(json.dumps(after, indent=1, sort_keys=True))
    tmp.replace(state_file)
    return done


def main(data_dir: str, service_user: str, stage: str, check: bool = False, picks: str = "handbook",
         roots_var: str = "RHB_SANDBOX_MOUNTS") -> int:
    """`refhandbook mounts`: stage what the users picked (root), or with --check print the plan. `picks`
    says whose picks: the handbook's policies, or the vault service's registrations (--picks vault, the
    offered roots then in PORTAL_VAULT_ROOTS)."""
    pw = pwd.getpwnam(service_user)
    try:
        offered = offers(roots_var)
    except MountError as e:
        print(f"error: {e}")
        return 2
    p = plan(Path(data_dir), Path(stage), pw.pw_uid, offered, group=os.environ.get("RHB_REQUIRE_GROUP") or None,
             picks=PICKS[picks])
    for line in p.skipped:
        print(f"skipped {line}")
    for user, st in p.status.items():
        for host, v in st.items():
            if v != "ok":
                print(f"{user}: not staged: {v}")
    if check:
        for s in p.stages:
            print(f"{s.host} -> {s.target} as {s.user} ({idmap(s, pw.pw_uid, pw.pw_gid)}){' ro' if s.ro else ''}")
        return 0
    if os.geteuid() != 0:
        print("error: staging mounts needs root (or run with --check)")
        return 1
    for line in apply(p, Path(stage), pw.pw_uid, pw.pw_gid):
        print(line)
    return 0
