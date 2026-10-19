"""P0: the sandbox holds. Each test runs a real sandbox (skipped where user namespaces are not
available) and tries one way out. The boundary is the namespaces, Landlock and seccomp; the command
view and noexec mounts decide what can run inside it."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from refhandbook.agents import sandbox

USERNS = dict((n, ok) for n, ok, _ in sandbox.check()).get("user namespaces", False)
pytestmark = pytest.mark.skipif(not USERNS, reason="user namespaces are not available here")


def run(tmp_path, argv, timeout=30, **spec):
    root, work = tmp_path / "root", tmp_path / "work"
    root.mkdir(exist_ok=True)
    work.mkdir(exist_ok=True)
    s = sandbox.Spec(argv=argv, root=str(root), work=str(work), timeout=timeout, **spec)
    path = tmp_path / "spec.json"
    path.write_text(s.to_json())
    p = subprocess.run(sandbox.command(str(path)), capture_output=True, text=True, timeout=timeout + 30)
    return p.returncode, p.stdout, p.stderr


def sh(tmp_path, script, **spec):
    return run(tmp_path, ["/bin/sh", "-c", script], **spec)


PROBE = r"""
import ctypes, errno, json, os, socket
libc = ctypes.CDLL(None, use_errno=True)
libc.syscall.restype = ctypes.c_long
def call(nr, *a):
    r = libc.syscall(nr, *[ctypes.c_long(x) for x in a])
    return "ok" if r >= 0 else errno.errorcode.get(ctypes.get_errno(), str(ctypes.get_errno()))
out = {
    "unshare_user": call(272, 0x10000000), "setns": call(308, 0, 0), "mount": call(165, 0, 0, 0, 0, 0),
    "ptrace_traceme": call(101, 0), "bpf": call(321, 0, 0, 0), "io_uring_setup": call(425, 1, 0),
    "keyctl": call(250, 0), "open_by_handle_at": call(304, 0, 0, 0), "init_module": call(175, 0, 0, 0),
    "clone_newns": call(56, 0x00020000 | 17, 0, 0, 0, 0), "unknown_500": call(500), "uid": os.getuid(),
}
try:
    socket.create_connection(("1.1.1.1", 80), timeout=2); out["net"] = "connected"
except OSError as e:
    out["net"] = type(e).__name__
print(json.dumps(out))
"""


def test_the_dangerous_syscalls_are_refused_and_unknown_ones_unjudged(tmp_path):
    code, out, err = run(tmp_path, ["/usr/bin/python3", "-I", "-c", PROBE], commands=["python3"])
    assert code == 0, err
    r = json.loads(out)
    for name in ("unshare_user", "setns", "mount", "ptrace_traceme", "bpf", "io_uring_setup", "keyctl",
                 "open_by_handle_at", "init_module", "clone_newns"):
        assert r[name] == "EPERM", (name, r[name])
    assert r["unknown_500"] == "ENOSYS"  # a syscall newer than the table is refused, not allowed
    assert r["uid"] == 1000
    assert r["net"] != "connected"


def test_the_host_filesystem_is_out_of_reach(tmp_path):
    secret = tmp_path / "other-user"
    secret.mkdir()
    (secret / "notes").write_text("private")
    code, out, err = sh(tmp_path, f"""
        echo ok > /work/mine && echo work-ok
        touch /usr/x 2>/dev/null || echo usr-ro
        touch /etc/x 2>/dev/null || echo etc-ro
        touch /x 2>/dev/null || echo root-ro
        test -e /home || echo no-home
        test -e /sys/kernel || echo no-sys
        test -e {secret} || echo no-sibling
        test -e /root/.claude || echo no-host-root
        ls /proc | grep -c '^[0-9]'
    """)
    assert code == 0, err
    for line in ("work-ok", "usr-ro", "etc-ro", "root-ro", "no-home", "no-sys", "no-sibling", "no-host-root"):
        assert line in out.splitlines(), (line, out)
    assert int(out.split()[-1]) <= 4  # only this sandbox's processes
    assert (tmp_path / "work" / "mine").read_text() == "ok\n"


def test_nothing_written_runs_as_code(tmp_path):
    loader = next(p for p in ("/lib64/ld-linux-x86-64.so.2", "/lib/ld-linux-aarch64.so.1") if os.path.exists(p))
    code, out, err = sh(tmp_path, f"""
        cp /bin/true /work/t && chmod +x /work/t && /work/t 2>/dev/null; echo work=$?
        cp /bin/true /tmp/t && chmod +x /tmp/t && /tmp/t 2>/dev/null; echo tmp=$?
        {loader} /work/t 2>/dev/null; echo loader=$?
    """)
    assert code == 0, err
    assert "work=126" in out and "tmp=126" in out
    assert "loader=0" not in out


def test_the_command_view_is_the_vocabulary(tmp_path):
    code, out, err = run(tmp_path, ["/usr/bin/sh", "-c", "ls /usr/bin; command -v curl rm python3 || echo missing"],
                         commands=["sh", "ls", "cat"])
    assert code == 0, err
    assert out.split()[:3] == ["cat", "ls", "sh"] and "missing" in out


def test_an_unknown_command_is_refused_before_anything_runs(tmp_path):
    code, _, err = run(tmp_path, ["/usr/bin/sh", "-c", "true"], commands=["sh", "no-such-command-xyz"])
    assert code == 125 and "not installed on the host" in err


def test_a_runaway_command_is_killed_with_everything_it_started(tmp_path):
    code, _, err = sh(tmp_path, "sleep 30 & sleep 30", timeout=1)
    assert code == 124 and "killed after 1s" in err


@pytest.mark.skipif(os.geteuid() != 0, reason="mapping another outside uid needs CAP_SETUID")
def test_a_per_user_outside_uid(tmp_path):
    # the outside uid must reach the sandbox's directories, as the runner lays them out (0711 parents)
    for d in [tmp_path, *tmp_path.parents][:3]:
        d.chmod(0o711)
    work = tmp_path / "work"
    work.mkdir()
    os.chown(work, 231072, 231072)
    code, out, err = sh(tmp_path, "id -u; echo x > /work/f", outside_uid=231072, outside_gid=231072)
    assert code == 0, err
    assert out.strip() == "1000"
    st = (work / "f").stat()
    assert (st.st_uid, st.st_gid) == (231072, 231072)


def test_the_capability_report_finds_user_namespaces():
    assert USERNS
