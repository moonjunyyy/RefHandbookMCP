"""A sandbox made of Linux primitives only: namespaces, overlayfs, Landlock, seccomp, cgroup v2 (or
rlimits), reached through the stdlib and libc (ctypes). No Docker, bubblewrap or helper binaries.

One command runs per launch:

    python -I -m refhandbook.agents.sandbox SPEC.json

The launcher (this module's `launch`) does, in order:

  1. join the cgroup leaf the runner made for this call (if any), and set rlimits;
  2. unshare user, mount, pid, ipc, uts, cgroup (and net, unless the spec allows the network) and
     map one uid: the service uid outside is `spec.uid` inside;
  3. fork: the child is pid 1 of the new pid namespace, so killing it kills everything it started;
  4. in the child, build a root on tmpfs:
       base host   — /usr is the host's, bound read-only; layers and the call's upper are
                     overlaid on /usr/local, /opt and /etc (the host's /etc is not used: a
                     prepared copy of the few files programs need is the lowest /etc layer);
       base rootfs — an imported tree; layers are overlaid on its /usr, /etc, /opt and /var;
     then /work (rw), extra binds, /tmp, /run, a minimal /dev, a fresh /proc, pivot_root, and the
     root made read-only;
  5. restrict itself with Landlock (write only where the spec gives a writable mount) and a seccomp
     deny-list (mounts, namespaces, ptrace, bpf, io_uring, keyrings, modules, …);
  6. execve the command with a clean environment.

The parent waits, enforces the timeout (SIGKILL to the child = the whole namespace), and exits with
the child's status: 124 on timeout, 125 if the sandbox could not be set up.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import glob
import json
import os
import platform
import re
import resource
import shutil
import signal
import stat
import struct
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ── constants ────────────────────────────────────────────────────────────

CLONE_NEWNS, CLONE_NEWCGROUP, CLONE_NEWUTS, CLONE_NEWIPC = 0x00020000, 0x02000000, 0x04000000, 0x08000000
CLONE_NEWUSER, CLONE_NEWPID, CLONE_NEWNET, CLONE_NEWTIME = 0x10000000, 0x20000000, 0x40000000, 0x00000080
NS_FLAGS = CLONE_NEWNS | CLONE_NEWCGROUP | CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWNET | CLONE_NEWTIME

MS_RDONLY, MS_NOSUID, MS_NODEV, MS_NOEXEC = 1, 2, 4, 8
MS_REMOUNT, MS_BIND, MS_REC, MS_PRIVATE = 32, 4096, 16384, 1 << 18
MNT_DETACH = 2
AT_FDCWD, AT_RECURSIVE = -100, 0x8000
MOUNT_ATTR_RDONLY, MOUNT_ATTR_NOSUID, MOUNT_ATTR_NODEV, MOUNT_ATTR_NOEXEC = 0x1, 0x2, 0x4, 0x8

PR_SET_PDEATHSIG, PR_SET_NO_NEW_PRIVS, PR_SET_SECCOMP, PR_SET_KEEPCAPS = 1, 38, 22, 8
SECCOMP_MODE_FILTER = 2

# Syscall numbers. x86_64 from asm/unistd_64.h; aarch64 is the asm-generic table.
_SYSCALLS = {
    "x86_64": dict(
        clone=56, ptrace=101, capget=125, capset=126, memfd_create=319, syslog=103, vhangup=153, pivot_root=155, adjtimex=159, chroot=161, acct=163,
        settimeofday=164, mount=165, umount2=166, swapon=167, swapoff=168, reboot=169, iopl=172, ioperm=173,
        init_module=175, delete_module=176, quotactl=179, lookup_dcookie=212, clock_settime=227, kexec_load=246,
        add_key=248, request_key=249, keyctl=250, unshare=272, perf_event_open=298, name_to_handle_at=303,
        open_by_handle_at=304, clock_adjtime=305, setns=308, process_vm_readv=310, process_vm_writev=311,
        finit_module=313, kexec_file_load=320, bpf=321, userfaultfd=323, io_uring_setup=425, io_uring_enter=426,
        io_uring_register=427, open_tree=428, move_mount=429, fsopen=430, fsconfig=431, fsmount=432, fspick=433,
        clone3=435, pidfd_getfd=438, mount_setattr=442, quotactl_fd=443, landlock_create_ruleset=444,
        landlock_add_rule=445, landlock_restrict_self=446, statmount=457, listmount=458, open_tree_attr=467,
    ),
    "aarch64": dict(
        lookup_dcookie=18, umount2=39, mount=40, pivot_root=41, chroot=51, vhangup=58, quotactl=60, acct=89,
        unshare=97, kexec_load=104, init_module=105, delete_module=106, clock_settime=112, syslog=116, ptrace=117,
        reboot=142, settimeofday=170, adjtimex=171, add_key=217, request_key=218, keyctl=219, clone=220, swapon=224,
        swapoff=225, capget=90, capset=91, memfd_create=279, perf_event_open=241, name_to_handle_at=264, open_by_handle_at=265, clock_adjtime=266, setns=268,
        process_vm_readv=270, process_vm_writev=271, finit_module=273, bpf=280, userfaultfd=282, kexec_file_load=294,
        io_uring_setup=425, io_uring_enter=426, io_uring_register=427, open_tree=428, move_mount=429, fsopen=430,
        fsconfig=431, fsmount=432, fspick=433, clone3=435, pidfd_getfd=438, mount_setattr=442, quotactl_fd=443,
        landlock_create_ruleset=444, landlock_add_rule=445, landlock_restrict_self=446, statmount=457, listmount=458,
        open_tree_attr=467,
    ),
}
_AUDIT_ARCH = {"x86_64": 0xC000003E, "aarch64": 0xC00000B7}
KNOWN_MAX = 467  # open_tree_attr, the newest call in both tables (Linux 6.15)

# What the sandboxed command may not call. clone is filtered on its flags; clone3 (whose flags sit
# in memory a filter cannot read) answers ENOSYS, so libc falls back to clone. A syscall numbered past
# KNOWN_MAX (one added to the kernel after this table) answers ENOSYS too: what the table has not
# judged is refused, the part of an allow-list that matters, without listing ~350 harmless calls.
DENY = (
    "mount umount2 pivot_root chroot unshare setns fsopen fsconfig fsmount fspick move_mount open_tree "
    "open_tree_attr mount_setattr statmount listmount ptrace process_vm_readv process_vm_writev pidfd_getfd bpf "
    "perf_event_open userfaultfd io_uring_setup io_uring_enter io_uring_register keyctl add_key request_key "
    "kexec_load kexec_file_load init_module finit_module delete_module reboot swapon swapoff acct quotactl "
    "quotactl_fd open_by_handle_at name_to_handle_at syslog lookup_dcookie vhangup settimeofday clock_settime "
    "adjtimex clock_adjtime iopl ioperm"
).split()

# Landlock (ABI 1..7)
LL_EXECUTE, LL_WRITE_FILE, LL_READ_FILE, LL_READ_DIR = 1, 2, 4, 8
LL_REMOVE_DIR, LL_REMOVE_FILE, LL_MAKE_CHAR, LL_MAKE_DIR = 16, 32, 64, 128
LL_MAKE_REG, LL_MAKE_SOCK, LL_MAKE_FIFO, LL_MAKE_BLOCK, LL_MAKE_SYM = 256, 512, 1024, 2048, 4096
LL_REFER, LL_TRUNCATE, LL_IOCTL_DEV = 8192, 16384, 32768
LL_NET_BIND_TCP, LL_NET_CONNECT_TCP = 1, 2
LL_SCOPE_ABSTRACT_UNIX_SOCKET, LL_SCOPE_SIGNAL = 1, 2

DEV_NODES = ("null", "zero", "full", "random", "urandom", "tty")
HOST_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
COMMAND_DIRS = ("usr/bin", "usr/sbin", "usr/local/bin", "usr/local/sbin", "bin", "sbin")
# The files of the host's /etc that programs commonly need, copied into the host base's /etc layer.
HOST_ETC = (
    "ld.so.cache", "ld.so.conf", "ld.so.conf.d", "ssl", "ca-certificates", "ca-certificates.conf", "alternatives",
    "localtime", "timezone", "nsswitch.conf", "mime.types", "protocols", "services", "os-release", "lsb-release",
    "debian_version", "bash.bashrc", "profile", "profile.d", "inputrc", "magic", "gitconfig", "pip.conf",
    "python3", "vim", "perl", "R", "texmf", "fonts", "gai.conf", "login.defs", "environment", "manpath.config",
)
# Overlay points per base kind: the directories a layer may change.
OVERLAY_POINTS = {"host": ("usr/local", "opt", "etc"), "rootfs": ("usr", "etc", "opt", "var")}


class SandboxError(RuntimeError):
    pass


# ── spec ─────────────────────────────────────────────────────────────────


@dataclass
class Limits:
    memory_mb: int = 2048
    pids: int = 512
    cpus: float = 2.0
    fsize_mb: int = 1024
    nofile: int = 1024
    tmp_mb: int = 512
    address_space: bool = False  # RLIMIT_AS = memory_mb when no cgroup is available (breaks some runtimes)


@dataclass
class Spec:
    """One sandboxed command. Paths are host paths; none may contain ':' or ',' (overlay syntax)."""

    argv: list[str]
    root: str  # an empty directory the launcher mounts the new root on
    work: str  # bound read-write at /work
    base: str = "host"  # "host", or the path of an imported rootfs tree
    layers: list[str] = field(default_factory=list)  # layer trees, top first
    upper: str | None = None  # where this sandbox's changes to the overlay points persist (None: discarded)
    hostetc: str | None = None  # the host base's prepared /etc (prepare_hostetc)
    binds_ro: list[tuple[str, str]] = field(default_factory=list)  # (host path, path inside)
    binds_rw: list[tuple[str, str]] = field(default_factory=list)
    network: bool = False
    uid: int = 1000
    gid: int = 1000
    cwd: str = "/work"
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = 120.0
    limits: Limits = field(default_factory=Limits)
    cgroup: str | None = None  # a cgroup leaf the runner created; the launcher joins it
    hostname: str = "sandbox"
    # The command view: None shows the host's command directories; a list shows only these commands
    # (host base), each found on the host's PATH and bound at /usr/bin/<name>. The other command
    # directories are empty. What a script can call is what this list put there.
    commands: list[str] | None = None
    # The uid/gid outside the sandbox (a per-user subordinate id). None maps the runner's own uid.
    # Another id needs a runner with CAP_SETUID/CAP_SETGID (the parent writes the child's map).
    outside_uid: int | None = None
    outside_gid: int | None = None
    # With the network: the TCP ports a connection may go to (None: any). A list keeps the host's
    # loopback services (the MCP server, LDAP, the KDC's TCP side) out of reach; UDP is not limited.
    ports: list[int] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str) -> Spec:
        d = json.loads(text)
        d["limits"] = Limits(**d.get("limits", {}))
        d["binds_ro"] = [tuple(b) for b in d.get("binds_ro", [])]
        d["binds_rw"] = [tuple(b) for b in d.get("binds_rw", [])]
        return cls(**d)

    def overlay_points(self) -> tuple[str, ...]:
        return OVERLAY_POINTS["host" if self.base == "host" else "rootfs"]

    def resolved_commands(self) -> dict[str, str]:
        """name → the host file it runs (resolved on the host before the root is built)."""
        out = {}
        for name in self.commands or []:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name):
                raise SandboxError(f"command {name!r}: a bare name (letters, digits, . _ + -)")
            path = shutil.which(name, path=HOST_PATH)
            if path is None:
                raise SandboxError(f"command {name!r} is not installed on the host")
            out[name] = os.path.realpath(path)
        return out

    def executable(self) -> list[str]:
        """Where execution is allowed. With a command view: the view and the dynamic loader only, so
        a helper binary elsewhere under /usr or /lib does not run by its path (the loader can still
        map any readable ELF: the view bounds the vocabulary, the namespaces bound the capability)."""
        if self.commands is None or self.base != "host":
            return ["/"]
        loaders = set()
        for pattern in ("/lib64/ld-linux*.so*", "/lib/ld-linux*.so*", "/lib/ld-musl*.so*", "/usr/lib/*/ld-linux*.so*"):
            for p in glob.glob(pattern):
                loaders.add(os.path.realpath(p))
        out = ["/usr/bin", *sorted(loaders)]
        if self.upper is not None:  # a layer build installs tools that must run
            out += ["/" + p for p in self.overlay_points()]
        return out

    def writable(self) -> list[str]:
        """Paths inside the sandbox the command may write under."""
        out = ["/work", "/tmp", "/run", "/dev/shm", "/dev/null", "/dev/zero", "/dev/full", "/dev/tty"] \
            + [d for _, d in self.binds_rw]
        out += ["/" + p for p in self.overlay_points()]
        return out


def _check_path(p: str) -> str:
    if not p or ":" in p or "," in p or "\n" in p:
        raise SandboxError(f"unusable path {p!r} (empty, or contains ':' ',' or a newline)")
    return p


# ── libc ─────────────────────────────────────────────────────────────────

_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
_libc.syscall.restype = ctypes.c_long
_libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p]
_libc.umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
_libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]


def _arch() -> str:
    m = platform.machine()
    if m not in _SYSCALLS:
        raise SandboxError(f"unsupported architecture {m!r} (x86_64 and aarch64 are)")
    return m


def _nr(name: str) -> int:
    return _SYSCALLS[_arch()][name]


def _err(what: str) -> SandboxError:
    e = ctypes.get_errno()
    return SandboxError(f"{what}: {os.strerror(e)} (errno {e})")


def _b(s: str | None) -> bytes | None:
    return None if s is None else os.fsencode(s)


def mount(src: str | None, target: str, fstype: str | None, flags: int = 0, data: str | None = None) -> None:
    if _libc.mount(_b(src), _b(target), _b(fstype), flags, _b(data)) != 0:
        raise _err(f"mount {fstype or src} on {target}")


def umount(target: str, flags: int = 0) -> None:
    if _libc.umount2(_b(target), flags) != 0:
        raise _err(f"umount {target}")


def mount_setattr(path: str, set_: int, recursive: bool = True) -> None:
    attr = struct.pack("QQQQ", set_, 0, 0, 0)
    buf = ctypes.create_string_buffer(attr, len(attr))
    r = _libc.syscall(_nr("mount_setattr"), ctypes.c_int(AT_FDCWD), _b(path),
                      ctypes.c_uint(AT_RECURSIVE if recursive else 0), buf, ctypes.c_size_t(len(attr)))
    if r != 0:
        raise _err(f"mount_setattr {path}")


def pivot_root(new: str, old: str) -> None:
    if _libc.syscall(_nr("pivot_root"), _b(new), _b(old)) != 0:
        raise _err("pivot_root")


def prctl(option: int, a: int = 0, b: int = 0, c: int = 0, d: int = 0) -> None:
    if _libc.prctl(option, a, b, c, d) != 0:
        raise _err(f"prctl {option}")


# ── Landlock ─────────────────────────────────────────────────────────────


def landlock_abi() -> int:
    try:
        r = _libc.syscall(_nr("landlock_create_ruleset"), None, ctypes.c_size_t(0), ctypes.c_uint(1))
    except SandboxError:
        return 0
    return max(int(r), 0)


def _ll_fs_rights(abi: int) -> int:
    rights = (1 << 13) - 1  # EXECUTE .. MAKE_SYM
    if abi >= 2:
        rights |= LL_REFER
    if abi >= 3:
        rights |= LL_TRUNCATE
    if abi >= 5:
        rights |= LL_IOCTL_DEV
    return rights


def landlock_restrict(read_paths: list[str], write_paths: list[str], *, deny_tcp: bool,
                      exec_paths: list[str] | None = None, tcp_ports: list[int] | None = None) -> int:
    """Allow reading beneath `read_paths`, executing beneath `exec_paths` (default: the read paths),
    every change but execution beneath `write_paths`, nothing else. TCP (ABI 4+): with `deny_tcp` no
    bind or connect; with `tcp_ports` connect to those ports only, and no bind. With ABI 6+ no signals
    or abstract unix sockets beyond this sandbox. Returns the ABI used (0: Landlock is not available,
    nothing done)."""
    abi = landlock_abi()
    if abi <= 0:
        if tcp_ports is not None:
            raise SandboxError("a port-limited network needs Landlock ABI 4 or later")
        return 0
    if tcp_ports is not None and abi < 4:
        raise SandboxError(f"a port-limited network needs Landlock ABI 4 (this kernel has {abi})")
    fs = _ll_fs_rights(abi)
    net = (LL_NET_BIND_TCP | LL_NET_CONNECT_TCP) if (abi >= 4 and (deny_tcp or tcp_ports is not None)) else 0
    scoped = (LL_SCOPE_ABSTRACT_UNIX_SOCKET | LL_SCOPE_SIGNAL) if abi >= 6 else 0
    if abi >= 6:
        attr = struct.pack("QQQ", fs, net, scoped)
    elif abi >= 4:
        attr = struct.pack("QQ", fs, net)
    else:
        attr = struct.pack("Q", fs)
    buf = ctypes.create_string_buffer(attr, len(attr))
    fd = _libc.syscall(_nr("landlock_create_ruleset"), buf, ctypes.c_size_t(len(attr)), ctypes.c_uint(0))
    if fd < 0:
        raise _err("landlock_create_ruleset")
    ro = LL_READ_FILE | LL_READ_DIR
    exec_paths = read_paths if exec_paths is None else exec_paths
    try:
        for paths, rights in ((read_paths, ro), (exec_paths, ro | LL_EXECUTE), (write_paths, fs & ~LL_EXECUTE)):
            for p in paths:
                try:
                    pfd = os.open(p, os.O_PATH | os.O_CLOEXEC)
                except FileNotFoundError:
                    continue
                try:
                    is_dir = stat.S_ISDIR(os.fstat(pfd).st_mode)
                    allowed = rights if is_dir else rights & (LL_EXECUTE | LL_WRITE_FILE | LL_READ_FILE | LL_TRUNCATE | LL_IOCTL_DEV)
                    rule = struct.pack("=Qi", allowed & fs, pfd)  # landlock_path_beneath_attr is packed
                    rbuf = ctypes.create_string_buffer(rule, len(rule))
                    if _libc.syscall(_nr("landlock_add_rule"), ctypes.c_int(fd), ctypes.c_int(1), rbuf, ctypes.c_uint(0)) != 0:
                        raise _err(f"landlock_add_rule {p}")
                finally:
                    os.close(pfd)
        for port in tcp_ports or []:  # landlock_net_port_attr {u64 allowed_access; u64 port}, packed
            rule = struct.pack("=QQ", LL_NET_CONNECT_TCP, int(port))
            rbuf = ctypes.create_string_buffer(rule, len(rule))
            if _libc.syscall(_nr("landlock_add_rule"), ctypes.c_int(fd), ctypes.c_int(2), rbuf, ctypes.c_uint(0)) != 0:
                raise _err(f"landlock_add_rule tcp {port}")
        prctl(PR_SET_NO_NEW_PRIVS, 1)
        if _libc.syscall(_nr("landlock_restrict_self"), ctypes.c_int(fd), ctypes.c_uint(0)) != 0:
            raise _err("landlock_restrict_self")
    finally:
        os.close(fd)
    return abi


# ── seccomp ──────────────────────────────────────────────────────────────

_BPF_LD_W_ABS, _BPF_JEQ, _BPF_JGE, _BPF_JSET, _BPF_RET = 0x20, 0x15, 0x35, 0x45, 0x06
_RET_KILL_PROCESS, _RET_ALLOW, _RET_ERRNO = 0x80000000, 0x7FFF0000, 0x00050000


def _ins(code: int, k: int, jt: int = 0, jf: int = 0) -> bytes:
    return struct.pack("HBBI", code, jt, jf, k & 0xFFFFFFFF)


def seccomp_program(arch: str | None = None, deny_memfd: bool = False) -> bytes:
    """The deny-list as classic BPF over seccomp_data {int nr; u32 arch; u64 ip; u64 args[6]}."""
    arch = arch or _arch()
    table = _SYSCALLS[arch]
    eperm, enosys = _RET_ERRNO | errno.EPERM, _RET_ERRNO | errno.ENOSYS
    p = [_ins(_BPF_LD_W_ABS, 4), _ins(_BPF_JEQ, _AUDIT_ARCH[arch], 1, 0), _ins(_BPF_RET, _RET_KILL_PROCESS),
         _ins(_BPF_LD_W_ABS, 0)]
    if arch == "x86_64":  # the x32 ABI shares this arch value: refuse it outright
        p += [_ins(_BPF_JGE, 0x40000000, 0, 1), _ins(_BPF_RET, _RET_KILL_PROCESS)]
    p += [_ins(_BPF_JGE, KNOWN_MAX + 1, 0, 1), _ins(_BPF_RET, enosys)]  # newer than this table: unjudged
    for name in DENY + (["memfd_create"] if deny_memfd else []):
        if name in table:
            p += [_ins(_BPF_JEQ, table[name], 0, 1), _ins(_BPF_RET, eperm)]
    p += [_ins(_BPF_JEQ, table["clone3"], 0, 1), _ins(_BPF_RET, enosys)]
    # clone: refuse namespace flags (args[0], low word on little-endian)
    p += [_ins(_BPF_JEQ, table["clone"], 0, 3), _ins(_BPF_LD_W_ABS, 16), _ins(_BPF_JSET, NS_FLAGS, 0, 1),
          _ins(_BPF_RET, eperm)]
    p += [_ins(_BPF_RET, _RET_ALLOW)]
    return b"".join(p)


# Defined at import: after pivot_root the interpreter's stdlib is out of reach, so nothing the child
# runs may import lazily (ctypes.Structure does, on first definition).
class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def seccomp_install(deny_memfd: bool = False) -> None:
    prog = seccomp_program(deny_memfd=deny_memfd)
    n = len(prog) // 8
    filt = ctypes.create_string_buffer(prog, len(prog))

    fprog = _SockFprog(n, ctypes.cast(filt, ctypes.c_void_p))
    prctl(PR_SET_NO_NEW_PRIVS, 1)
    if _libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.addressof(fprog), 0, 0) != 0:
        raise _err("seccomp")


# ── cgroup v2 ────────────────────────────────────────────────────────────


class Cgroups:
    """Per-call cgroup leaves under a delegated subtree (systemd Delegate=yes).

    `prepare()` moves this process into `<own>/supervisor` (cgroup v2 allows processes only in
    leaves once controllers are enabled below), enables memory/pids/cpu for `<own>/sandboxes`, and
    returns an instance; None when the subtree is not ours to write."""

    CONTROLLERS = ("memory", "pids", "cpu")

    def __init__(self, base: Path):
        self.base = base

    @classmethod
    def own(cls) -> Path | None:
        try:
            line = next(ln for ln in Path("/proc/self/cgroup").read_text().splitlines() if ln.startswith("0::"))
        except (OSError, StopIteration):
            return None
        return Path("/sys/fs/cgroup") / line[3:].lstrip("/")

    @classmethod
    def prepare(cls, base: str | None = None) -> Cgroups | None:
        own = Path(base) if base else cls.own()
        if own is None or not os.access(own, os.W_OK) or not (own / "cgroup.procs").exists():
            return None
        try:
            sup = own / "supervisor"
            sup.mkdir(exist_ok=True)
            (sup / "cgroup.procs").write_text(str(os.getpid()))
            avail = (own / "cgroup.controllers").read_text().split()
            want = [c for c in cls.CONTROLLERS if c in avail]
            if want:
                (own / "cgroup.subtree_control").write_text(" ".join("+" + c for c in want))
            box = own / "sandboxes"
            box.mkdir(exist_ok=True)
            if want:
                (box / "cgroup.subtree_control").write_text(" ".join("+" + c for c in want))
        except OSError:
            return None
        return cls(box)

    def leaf(self, name: str, limits: Limits) -> Path:
        p = self.base / name
        p.mkdir(exist_ok=True)
        for f, v in (("memory.max", str(limits.memory_mb * 1024 * 1024)), ("memory.swap.max", "0"),
                     ("pids.max", str(limits.pids)), ("cpu.max", f"{int(limits.cpus * 100000)} 100000")):
            try:
                (p / f).write_text(v)
            except OSError:
                pass  # a controller that is not enabled
        return p

    @staticmethod
    def kill(leaf: Path) -> None:
        try:
            (leaf / "cgroup.kill").write_text("1")
        except OSError:
            pass

    @staticmethod
    def remove(leaf: Path, wait: float = 2.0) -> None:
        deadline = time.monotonic() + wait
        while True:
            try:
                leaf.rmdir()
                return
            except FileNotFoundError:
                return
            except OSError:
                if time.monotonic() > deadline:
                    return
                Cgroups.kill(leaf)
                time.sleep(0.05)


# ── host /etc layer ──────────────────────────────────────────────────────

PASSWD = "root:x:0:0:root:/root:/bin/sh\nagent:x:1000:1000:agent:/work:/bin/bash\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
GROUP = "root:x:0:\nagent:x:1000:\nnogroup:x:65534:\n"


def prepare_hostetc(dst: str | Path, src: str | Path = "/etc") -> Path:
    """Build the host base's lowest /etc: the few host files programs need (dynamic linker cache,
    certificates, alternatives, locale and time zone), and a synthetic passwd, group and hosts.
    Nothing secret: shadow, sudoers, ssh keys and service configuration are not copied."""
    dst, src = Path(dst), Path(src)
    tmp = dst.with_name(dst.name + ".new")
    _rmtree(tmp)
    tmp.mkdir(parents=True)
    for name in HOST_ETC:
        s = src / name
        try:
            if s.is_symlink():
                os.symlink(os.readlink(s), tmp / name)
            elif s.is_dir():
                shutil.copytree(s, tmp / name, symlinks=True, ignore_dangling_symlinks=True,
                                copy_function=_copy_readable)
            elif s.is_file():
                _copy_readable(s, tmp / name)
        except OSError:
            continue
    (tmp / "passwd").write_text(PASSWD)
    (tmp / "group").write_text(GROUP)
    (tmp / "hosts").write_text("127.0.0.1 localhost sandbox\n::1 localhost\n")
    (tmp / "hostname").write_text("sandbox\n")
    (tmp / "resolv.conf").write_text("")
    _rmtree(dst)
    tmp.rename(dst)
    return dst


def _copy_readable(s: Any, d: Any) -> None:
    try:
        shutil.copy2(s, d)
    except PermissionError:
        pass


def _rmtree(p: str | Path) -> None:
    """Remove a tree, including an overlay workdir (its `work` subdirectory is mode 000)."""
    p = Path(p)
    if not p.exists() and not p.is_symlink():
        return

    def fix(func: Any, path: str, _exc: Any) -> None:
        parent = os.path.dirname(path)
        os.chmod(parent, 0o700)
        if os.path.isdir(path) and not os.path.islink(path):
            os.chmod(path, 0o700)
            shutil.rmtree(path, onexc=fix)
        else:
            func(path)

    shutil.rmtree(p, onexc=fix)


rmtree = _rmtree


# ── building the root (in the child, inside the namespaces) ──────────────


def _mkdir(p: str, mode: int = 0o755) -> None:
    os.makedirs(p, mode=mode, exist_ok=True)


def _touch(p: str) -> None:
    with open(p, "a"):
        pass


def _overlay(target: str, lowers: list[str], upper: str | None, workdir: str | None) -> None:
    lowers = [_check_path(x) for x in lowers]
    if upper is None:
        if len(lowers) == 1:
            mount(lowers[0], target, None, MS_BIND | MS_REC)
            mount_setattr(target, MOUNT_ATTR_RDONLY | MOUNT_ATTR_NOSUID | MOUNT_ATTR_NODEV)
            return
        mount("overlay", target, "overlay", MS_NOSUID | MS_NODEV | MS_RDONLY,
              f"lowerdir={':'.join(lowers)},userxattr")
        return
    _check_path(upper), _check_path(workdir or "")
    if not lowers:  # nothing below: the upper alone, read-write
        mount(upper, target, None, MS_BIND)
        return
    mount("overlay", target, "overlay", MS_NOSUID | MS_NODEV,
          f"lowerdir={':'.join(lowers)},upperdir={upper},workdir={workdir},userxattr")


def _point_key(point: str) -> str:
    return point.replace("/", "_")


def _command_view(root: str, commands: dict[str, str]) -> None:
    """Empty every command directory of the root, then bind the allowed commands at /usr/bin."""
    for d in COMMAND_DIRS:
        target = f"{root}/{d}"
        if os.path.isdir(target) and not os.path.islink(target):
            mount("tmpfs", target, "tmpfs", MS_NOSUID | MS_NODEV | MS_RDONLY, "mode=0755,size=64k")
    bindir = f"{root}/usr/bin"
    mount("tmpfs", bindir, "tmpfs", MS_NOSUID | MS_NODEV, "mode=0755,size=64k")
    for name, src in commands.items():
        _touch(f"{bindir}/{name}")
        mount(src, f"{bindir}/{name}", None, MS_BIND)
    mount_setattr(bindir, MOUNT_ATTR_RDONLY | MOUNT_ATTR_NOSUID | MOUNT_ATTR_NODEV)


def build_root(spec: Spec, commands: dict[str, str] | None = None) -> None:
    """The new root. Everything writable is mounted noexec: nothing the command writes can run as
    code (not by execve, and not by mmap through the loader), only through an allowed interpreter."""
    root = _check_path(spec.root)
    mount("tmpfs", root, "tmpfs", MS_NOSUID | MS_NODEV, "mode=0755,size=16m")
    host = spec.base == "host"
    base = None if host else _check_path(spec.base)
    upper = spec.upper

    # top-level layout
    if host:
        for name in ("bin", "sbin", "lib", "lib32", "lib64", "libx32"):
            hp = "/" + name
            if os.path.islink(hp):
                os.symlink(os.readlink(hp), f"{root}/{name}")
            elif os.path.isdir(hp):
                _mkdir(f"{root}/{name}")
                mount(hp, f"{root}/{name}", None, MS_BIND | MS_REC)
                mount_setattr(f"{root}/{name}", MOUNT_ATTR_RDONLY | MOUNT_ATTR_NOSUID | MOUNT_ATTR_NODEV)
        _mkdir(f"{root}/usr")
        mount("/usr", f"{root}/usr", None, MS_BIND | MS_REC)
        mount_setattr(f"{root}/usr", MOUNT_ATTR_RDONLY | MOUNT_ATTR_NOSUID | MOUNT_ATTR_NODEV)
    else:
        assert base is not None
        for entry in os.scandir(base):
            if entry.is_symlink():
                os.symlink(os.readlink(entry.path), f"{root}/{entry.name}")

    for point in spec.overlay_points():
        target = f"{root}/{point}"
        _mkdir(target)
        lowers = [f"{lay}/{point}" for lay in spec.layers if os.path.isdir(f"{lay}/{point}")]
        if host:
            if point == "etc" and spec.hostetc:
                lowers.append(spec.hostetc)
        elif os.path.isdir(f"{base}/{point}"):
            lowers.append(f"{base}/{point}")
        if upper is not None:
            k = _point_key(point)
            up, wd = f"{upper}/{k}", f"{upper}/.work/{k}"
            _mkdir(up), _mkdir(wd)
            _overlay(target, lowers, up, wd)
        elif lowers:
            _overlay(target, lowers, None, None)

    if commands is not None and host:
        _command_view(root, commands)

    for d in ("work", "tmp", "run", "proc", "dev", "root"):
        _mkdir(f"{root}/{d}")
    mount(_check_path(spec.work), f"{root}/work", None, MS_BIND)
    mount_setattr(f"{root}/work", MOUNT_ATTR_NOSUID | MOUNT_ATTR_NODEV | MOUNT_ATTR_NOEXEC, recursive=False)
    mount("tmpfs", f"{root}/tmp", "tmpfs", MS_NOSUID | MS_NODEV | MS_NOEXEC, f"mode=1777,size={spec.limits.tmp_mb}m")
    mount("tmpfs", f"{root}/run", "tmpfs", MS_NOSUID | MS_NODEV | MS_NOEXEC, "mode=0755,size=8m")
    for src, dst, rw in [(s, d, False) for s, d in spec.binds_ro] + [(s, d, True) for s, d in spec.binds_rw]:
        target = f"{root}/{dst.lstrip('/')}"
        if os.path.isdir(src):
            _mkdir(target)
        else:
            _mkdir(os.path.dirname(target))
            _touch(target)
        mount(src, target, None, MS_BIND | MS_REC)
        mount_setattr(target, MOUNT_ATTR_NOSUID | MOUNT_ATTR_NODEV | (MOUNT_ATTR_NOEXEC if rw else MOUNT_ATTR_RDONLY))

    # /dev: a tmpfs with the harmless host nodes bound in
    mount("tmpfs", f"{root}/dev", "tmpfs", MS_NOSUID, "mode=0755,size=1m")
    for n in DEV_NODES:
        if os.path.exists(f"/dev/{n}"):
            _touch(f"{root}/dev/{n}")
            try:
                mount(f"/dev/{n}", f"{root}/dev/{n}", None, MS_BIND)
            except SandboxError:
                os.unlink(f"{root}/dev/{n}")
    for name, tgt in (("fd", "/proc/self/fd"), ("stdin", "/proc/self/fd/0"), ("stdout", "/proc/self/fd/1"),
                      ("stderr", "/proc/self/fd/2")):
        os.symlink(tgt, f"{root}/dev/{name}")
    _mkdir(f"{root}/dev/shm")
    mount("tmpfs", f"{root}/dev/shm", "tmpfs", MS_NOSUID | MS_NODEV | MS_NOEXEC, "mode=1777,size=64m")
    # /dev itself: nothing is created there, and nothing there runs (its nodes and /dev/shm are
    # their own mounts and keep their modes)
    mount_setattr(f"{root}/dev", MOUNT_ATTR_RDONLY | MOUNT_ATTR_NOSUID | MOUNT_ATTR_NOEXEC, recursive=False)
    mount("proc", f"{root}/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC)

    old = f"{root}/.oldroot"
    _mkdir(old)
    pivot_root(root, old)
    os.chdir("/")
    umount("/.oldroot", MNT_DETACH)
    os.rmdir("/.oldroot")
    mount_setattr("/", MOUNT_ATTR_RDONLY | MOUNT_ATTR_NOSUID | MOUNT_ATTR_NODEV, recursive=False)


# ── launch ───────────────────────────────────────────────────────────────


def _write(path: str, text: str) -> None:
    with open(path, "w") as f:
        f.write(text)


def _rlimits(spec: Spec) -> None:
    lim = spec.limits
    mb = 1024 * 1024
    pairs = [(resource.RLIMIT_CORE, 0), (resource.RLIMIT_NOFILE, lim.nofile), (resource.RLIMIT_FSIZE, lim.fsize_mb * mb),
             (resource.RLIMIT_CPU, int(spec.timeout * max(lim.cpus, 1.0)) + 5)]
    if spec.cgroup is None:
        # RLIMIT_NPROC counts every process of the (outside) uid, the runner's and other sandboxes'
        # too, so it is only a coarse fallback for pids.max.
        pairs.append((resource.RLIMIT_NPROC, lim.pids + 256))
        if lim.address_space:
            pairs.append((resource.RLIMIT_AS, lim.memory_mb * mb))
    for r, v in pairs:
        try:
            soft, hard = resource.getrlimit(r)
            v = v if hard == resource.RLIM_INFINITY else min(v, hard)
            resource.setrlimit(r, (v, v))
        except (ValueError, OSError):
            pass


def _memfd_noexec() -> bool:
    """Memory written by the command must not run either: vm.memfd_noexec=2 is per pid namespace
    (Linux 6.3+), and this one is ours. False when it cannot be set (then memfd_create is refused)."""
    try:
        _write("/proc/sys/vm/memfd_noexec", "2")
        return Path("/proc/sys/vm/memfd_noexec").read_text().strip() == "2"
    except OSError:
        return False


def _child(spec: Spec, commands: dict[str, str] | None) -> None:
    prctl(PR_SET_PDEATHSIG, signal.SIGKILL)
    mount(None, "/", None, MS_REC | MS_PRIVATE)
    build_root(spec, commands)
    name = spec.hostname.encode()
    _libc.sethostname(name, len(name))  # best effort: a failure leaves the host's name visible
    landlock_restrict(["/"], spec.writable(), deny_tcp=not spec.network, exec_paths=spec.executable(),
                      tcp_ports=spec.ports if spec.network else None)
    seccomp_install(deny_memfd=not _memfd_noexec())
    env = {"PATH": HOST_PATH, "HOME": "/work",
           "USER": "agent" if spec.uid else "root", "LANG": "C.UTF-8", "TERM": "dumb", "TMPDIR": "/tmp"}
    env.update(spec.env)
    os.chdir(spec.cwd)
    if (os.getuid(), os.getgid()) != (spec.uid, spec.gid):
        os.setresgid(spec.gid, spec.gid, spec.gid)
        os.setresuid(spec.uid, spec.uid, spec.uid)
    os.execvpe(spec.argv[0], spec.argv, env)


def _enter_namespaces(spec: Spec) -> None:
    """Unshare, and map spec.uid inside to the runner's uid outside, or to spec.outside_uid. A map
    to another id is written from the parent user namespace, which needs CAP_SETUID there: a helper
    forked before the unshare writes it, then lets this process go on."""
    uid, gid = os.getuid(), os.getgid()
    flags = NS_FLAGS & ~CLONE_NEWTIME & ~(CLONE_NEWNET if spec.network else 0)
    out_uid = uid if spec.outside_uid is None else spec.outside_uid
    out_gid = gid if spec.outside_gid is None else spec.outside_gid
    if (out_uid, out_gid) == (uid, gid):
        os.unshare(flags)
        _write("/proc/self/setgroups", "deny")
        _write("/proc/self/uid_map", f"{spec.uid} {uid} 1")
        _write("/proc/self/gid_map", f"{spec.gid} {gid} 1")
        return
    if os.geteuid() != 0:
        raise SandboxError("a per-user outside uid needs a runner with CAP_SETUID (run the runner as root, "
                           "or leave outside_uid unset)")
    me = os.getpid()
    go_r, go_w = os.pipe()
    done_r, done_w = os.pipe()
    helper = os.fork()
    if helper == 0:  # stays in the parent namespace
        os.close(go_w), os.close(done_r)
        ok = b"x"
        try:
            os.read(go_r, 1)
            _write(f"/proc/{me}/setgroups", "deny")
            _write(f"/proc/{me}/uid_map", f"{spec.uid} {out_uid} 1")
            _write(f"/proc/{me}/gid_map", f"{spec.gid} {out_gid} 1")
            ok = b"1"
        except OSError as e:
            os.write(2, f"sandbox: id map: {e}\n".encode())
        os.write(done_w, ok)
        os._exit(0)
    os.close(go_r), os.close(done_w)
    os.unshare(flags)
    os.write(go_w, b"1")
    ok = os.read(done_r, 1)
    os.waitpid(helper, 0)
    os.close(go_w), os.close(done_r)
    if ok != b"1":
        raise SandboxError("could not map the outside uid")
    # Unmapped inside, this process could create no file; become spec.uid, keeping the namespace's
    # capabilities that building the root needs (execve drops them, as for any non-root uid).
    prctl(PR_SET_KEEPCAPS, 1)
    os.setresgid(spec.gid, spec.gid, spec.gid)
    os.setresuid(spec.uid, spec.uid, spec.uid)
    _raise_effective_caps()


class _CapHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class _CapData(ctypes.Structure):
    _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32), ("inheritable", ctypes.c_uint32)]


def _raise_effective_caps() -> None:
    hdr, data = _CapHeader(0x20080522, 0), (_CapData * 2)()
    if _libc.syscall(_nr("capget"), ctypes.byref(hdr), data) != 0:
        raise _err("capget")
    for d in data:
        d.effective = d.permitted
    if _libc.syscall(_nr("capset"), ctypes.byref(hdr), data) != 0:
        raise _err("capset")


def launch(spec: Spec) -> int:
    if not spec.argv:
        raise SandboxError("nothing to run")
    if spec.cgroup:
        _write(os.path.join(spec.cgroup, "cgroup.procs"), str(os.getpid()))
    _rlimits(spec)
    commands = spec.resolved_commands() if spec.commands is not None else None
    _enter_namespaces(spec)
    # From here, errors in the child are reported on stderr with status 125.
    pid = os.fork()
    if pid == 0:
        try:
            _child(spec, commands)
        except BaseException as e:  # noqa: BLE001  (anything before exec is a setup failure)
            os.write(2, f"sandbox: {e}\n".encode())
            os._exit(125)
    timed_out = False

    def kill(*_: Any) -> None:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def on_alarm(*_: Any) -> None:
        nonlocal timed_out
        timed_out = True
        kill()

    signal.signal(signal.SIGTERM, kill)
    signal.signal(signal.SIGINT, kill)
    signal.signal(signal.SIGHUP, kill)
    signal.signal(signal.SIGALRM, on_alarm)
    if spec.timeout > 0:
        signal.setitimer(signal.ITIMER_REAL, spec.timeout)
    while True:
        try:
            _, status = os.waitpid(pid, 0)
            break
        except InterruptedError:
            continue
        except ChildProcessError:
            return 125
    signal.setitimer(signal.ITIMER_REAL, 0)
    if timed_out:
        os.write(2, f"sandbox: killed after {spec.timeout:g}s\n".encode())
        return 124
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return os.WEXITSTATUS(status)


def command(spec_path: str) -> list[str]:
    """The argv that runs a spec file in a fresh interpreter."""
    return [sys.executable, "-I", "-m", "refhandbook.agents.sandbox", spec_path]


# ── capability report ────────────────────────────────────────────────────


def check() -> list[tuple[str, bool, str]]:
    """(capability, ok, detail) for each primitive the sandbox uses, with the fallback if missing."""
    out: list[tuple[str, bool, str]] = []
    try:
        arch = _arch()
        out.append(("architecture", True, arch))
    except SandboxError as e:
        return [("architecture", False, str(e))]
    restrict = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    if restrict.exists() and restrict.read_text().strip() == "1":
        out.append(("userns restriction", False, "kernel.apparmor_restrict_unprivileged_userns=1 forbids "
                    "unprivileged user namespaces: set it to 0 (echo 'kernel.apparmor_restrict_unprivileged_userns=0' "
                    "> /etc/sysctl.d/60-userns.conf; sysctl --system). The sandbox uses no LSM profile."))
    r, w = os.pipe()
    uid = os.getuid()  # before the unshare: inside an unmapped namespace getuid() is the overflow id
    pid = os.fork()
    if pid == 0:
        os.close(r)
        msg = "ok"
        try:
            os.unshare(CLONE_NEWUSER | CLONE_NEWNS | CLONE_NEWNET | CLONE_NEWPID | CLONE_NEWIPC | CLONE_NEWUTS)
            _write("/proc/self/setgroups", "deny")
            _write("/proc/self/uid_map", f"0 {uid} 1")
        except OSError as e:
            msg = f"unshare: {e}"
        os.write(w, msg.encode())
        os._exit(0)
    os.close(w)
    msg = os.read(r, 4096).decode()
    os.close(r)
    os.waitpid(pid, 0)
    out.append(("user namespaces", msg == "ok", msg if msg != "ok" else "user, mount, pid, net, ipc, uts"))
    abi = landlock_abi()
    out.append(("landlock", abi > 0, f"ABI {abi}" if abi else "not available: mount namespace only"))
    out.append(("seccomp", Path("/proc/self/status").read_text().find("Seccomp:") >= 0, "filter mode"))
    own = Cgroups.own()
    deleg = own is not None and os.access(own, os.W_OK)
    out.append(("cgroup v2 delegation", deleg,
                str(own) if deleg else "not delegated: rlimits instead (no memory limit; NPROC is per uid)"))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -I -m refhandbook.agents.sandbox SPEC.json", file=sys.stderr)
        return 2
    try:
        spec = Spec.from_json(Path(argv[0]).read_text())
        return launch(spec)
    except (SandboxError, OSError, ValueError, TypeError) as e:
        print(f"sandbox: {e}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    sys.exit(main())
