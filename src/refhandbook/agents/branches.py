"""A run's branches (docs/agents.md "Branches").

Every git repository inside a read-write mount of a run's policy is given to the run's agents as a worktree on a
branch of the run's own (`run/<hex>`, RHB_RUN_BRANCH), made from the repository's HEAD before the run's first
command. When the run ends done, what the agents changed there is committed on that branch and merged into the
branch the repository has checked out; the person's checkout changes only at that merge, and runs side by side
work on branches side by side. A merge that conflicts, or that would overwrite changes the person has not
committed, is undone (`git merge --abort`) and leaves the branch for them; so does a run that ends cancelled or
failed (its work committed on the branch, nothing merged). A branch that gained nothing is deleted. Files of a
mount outside every repository are written in place, as before.

Which repositories: the mount itself when it holds a `.git` directory; otherwise the directories under it, down
to RHB_RUN_BRANCH_DEPTH levels (2), that hold one — not descending into a repository, a hidden directory or a
symbolic link. A mount that is a part of a repository (its `.git` above the mount) is not branched, nor a
repository whose `.git` is a file (a submodule, another worktree). A branch holds what git tracks: untracked and
ignored files (node_modules, .venv, data) are not in the worktree.

Where things are. The worktree is the runner's (`<run dir>/branches/<n>-<slug>`, removed when the run ends).
Inside the sandbox it is bound over the repository's place in the mount, and the repository's git directory at
`/git/<slug>`, which is where the worktree's `.git` points — so git works for the agents as in any worktree.
Every git command on a repository runs in the sandbox, under the run's policy (its commands and layers, without
the network): an agent can write a repository's config, attributes and hooks, and none of that may run outside the
sandbox. The runner only finds the repositories (reading directories, following no link), makes and removes its
own directories, removes the worktree's registration (opening each directory without following links), and reads
what the sandboxed git printed. Each bind carries the (device, inode) its source had when it was looked at, so a
source swapped for a link before the bind is refused (sandbox.Spec.bind_ids).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

GIT = "/git"  # inside the sandbox: each repository's git directory, at /git/<slug>
TREE = ".tree"  # …and, for the merge only, its own checkout at /git/<slug>.tree
BRANCH = os.environ.get("RHB_RUN_BRANCH") or "run/{run}"
DEPTH = int(os.environ.get("RHB_RUN_BRANCH_DEPTH") or 2)
MARK = "@@rhb"  # the line the sandboxed scripts print before what they say of one repository
SAID = 2000  # characters kept of what git said about one repository

# (bind source on the host, path inside), and the (device, inode) each source had when it was looked at
Binds = list[tuple[str, str]]
Ids = dict[str, list[int]]
# runs a script in the sandbox with these read-write binds only: (exit status, stdout)
Launch = Callable[[Binds, Ids, str, dict[str, str]], tuple[int, str]]


class BranchError(Exception):
    pass


@dataclass
class Repo:
    src: str  # the mount's source on the host (its staged path)
    rel: str  # the repository's path under it ('' = the mount itself)
    inside: str  # where the repository is inside the sandbox (the mount's target + rel)
    slug: str  # its git directory inside: /git/<slug>
    worktree: str = ""  # the run's checkout (the runner's directory)
    name: str = ""  # the worktree's registration: <git dir>/worktrees/<name>
    base: str = ""  # the commit the branch started from
    state: str = "open"  # open | failed | merged | kept | unchanged | lost
    why: str = ""
    files: int = 0

    @property
    def root(self) -> str:
        return os.path.join(self.src, self.rel) if self.rel else self.src


@dataclass
class Manifest:
    branch: str = ""
    made: bool = False  # the repositories were looked for (once, before the run's first command)
    why: str = ""  # why there are none, when that is worth saying (the policy offers no git)
    ended: bool = False
    repos: list[Repo] = field(default_factory=list)


def branch_name(run: str) -> str:
    return BRANCH.format(run=run.split(":", 1)[-1])


def _is_repo(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(os.path.join(path, ".git")).st_mode)
    except OSError:
        return False


def _slug(root: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(root.rstrip("/")) or "repo").strip("-.")[:40] or "repo"
    return f"{name}-{hashlib.sha256(root.encode()).hexdigest()[:8]}"


def find(src: str, target: str, depth: int = DEPTH) -> list[Repo]:
    """The repositories a read-write mount (src on the host, target inside) gives a run."""
    if _is_repo(src):
        return [Repo(src, "", target, _slug(src))]
    out: list[Repo] = []
    level = [("", target)]
    for _ in range(max(0, depth)):
        deeper = []
        for rel, inside in level:
            try:
                entries = sorted(os.scandir(os.path.join(src, rel) if rel else src), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                if e.name.startswith(".") or "\n" in e.name or not e.is_dir(follow_symlinks=False):
                    continue
                r, i = (f"{rel}/{e.name}" if rel else e.name), f"{inside.rstrip('/')}/{e.name}"
                if _is_repo(e.path):
                    out.append(Repo(src, r, i, _slug(e.path)))
                else:
                    deeper.append((r, i))
        level = deeper
    return out


def _ids(path: str, follow: bool = False) -> list[int]:
    st = os.stat(path) if follow else os.lstat(path)
    return [st.st_dev, st.st_ino]


def _q(s: str) -> str:
    return shlex.quote(s)


# ── the scripts (sh and git only; every path quoted; what a repository's git says follows its mark) ──────────

PRELUDE = """set -u
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0
g() { git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c commit.gpgSign=false "$@"; }
"""


def create_script(repos: list[Repo], branch: str) -> str:
    """Each repository's worktree at its place inside, on the run's branch from HEAD; prints each one's base."""
    lines = [PRELUDE]
    for i, r in enumerate(repos):
        gd = f"{GIT}/{r.slug}"
        lines.append(
            f"if out=$(g --git-dir={_q(gd)} worktree add --quiet -b {_q(branch)} {_q(r.inside)} HEAD 2>&1); then\n"
            f"  printf '%s {i} open %s\\n' {MARK} \"$(g --git-dir={_q(gd)} rev-parse HEAD)\"\n"
            f"else\n  printf '%s {i} failed\\n%s\\n' {MARK} \"$out\"\nfi")
    return "\n".join(lines) + "\n"


def finish_script(repos: list[Repo], branch: str, outcome: str) -> str:
    """Commit what each worktree holds on the run's branch; when the run ended done, merge the branch into the
    repository's checked-out branch (undone when it conflicts or would overwrite uncommitted changes). The commit
    message is $MSG. Prints each one's state: unchanged | merged <files> | kept <files> and what git said."""
    lines = [PRELUDE]
    for i, r in enumerate(repos):
        gd, tree, wt, base, b = _q(f"{GIT}/{r.slug}"), _q(f"{GIT}/{r.slug}{TREE}"), _q(r.inside), _q(r.base), _q(branch)
        lines.append(f"""(
  cd {wt} && g add -A && {{ g diff --cached --quiet || g commit -q -m "$MSG"; }} || {{ printf '%s {i} kept 0\\n' {MARK}; printf 'the work could not be committed\\n'; exit 0; }}
  g checkout -q --detach  # the branch no longer checked out here: it can be merged and deleted
  n=$(g --git-dir={gd} diff --name-only {base} {b} | {{ c=0; while IFS= read -r _; do c=$((c+1)); done; echo $c; }})
  if [ "$(g --git-dir={gd} rev-list --count {base}..{b})" = 0 ]; then
    g --git-dir={gd} branch -q -D {b}; printf '%s {i} unchanged 0\\n' {MARK}
  elif [ {_q(outcome)} != done ]; then
    printf '%s {i} kept %s\\n' {MARK} "$n"; printf 'the run ended %s\\n' {_q(outcome)}
  else
    cd {tree} || {{ printf '%s {i} kept %s\\n' {MARK} "$n"; exit 0; }}
    if out=$(g merge --no-edit -q {b} 2>&1); then
      g branch -q -d {b}; printf '%s {i} merged %s\\n' {MARK} "$n"
    else
      printf '%s {i} kept %s\\n' {MARK} "$n"
      u=$(g diff --name-only --diff-filter=U)
      if [ -n "$u" ]; then printf 'conflicts:\\n%s\\n' "$u"; else printf '%s\\n' "$out"; fi
      [ -f {gd}/MERGE_HEAD ] && g merge --abort
    fi
  fi
)""")
    return "\n".join(lines) + "\n"


def said(out: str) -> dict[int, tuple[list[str], str]]:
    """What a script printed, by repository: (the words of its mark line, what followed it)."""
    got: dict[int, tuple[list[str], str]] = {}
    cur, buf = None, []
    for line in out.splitlines():
        if line.startswith(MARK + " "):
            if cur is not None:
                got[cur] = (got[cur][0], "\n".join(buf).strip()[:SAID])
            words = line.split()[1:]
            cur = int(words[0]) if words and words[0].isdigit() else None
            buf = []
            if cur is not None:
                got[cur] = (words[1:], "")
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        got[cur] = (got[cur][0], "\n".join(buf).strip()[:SAID])
    return got


# ── one run's branches ────────────────────────────────────────────────────────────────────────────────────


class Branches:
    """The branches of one run: its manifest (`<run dir>/branches.json`, the runner's) and its worktrees. Every
    change happens under a file lock, so the job runners of two processes never make the worktrees twice."""

    def __init__(self, rdir: Path, run: str):
        self.rdir, self.run = Path(rdir), run
        self.path = self.rdir / "branches.json"

    @contextmanager
    def _locked(self) -> Iterator[Manifest]:
        self.rdir.mkdir(parents=True, exist_ok=True)
        with open(self.rdir / "branches.lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            m = self.load()
            yield m
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({**asdict(m), "repos": [asdict(r) for r in m.repos]}, ensure_ascii=False))
            tmp.replace(self.path)

    def load(self) -> Manifest:
        try:
            d = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return Manifest(branch=branch_name(self.run))
        return Manifest(branch=d.get("branch", ""), made=d.get("made", False), why=d.get("why", ""), ended=d.get("ended", False),
                        repos=[Repo(**r) for r in d.get("repos", [])])

    def listing(self) -> dict:
        """What the run's page shows: the branch, each repository's place inside, its state, what was said."""
        return self._listing(self.load())

    @staticmethod
    def _listing(m: Manifest) -> dict:
        return {"branch": m.branch, "why": m.why, "repos": [
            {"repo": r.inside, "state": r.state, "files": r.files, "why": r.why} for r in m.repos]}

    @staticmethod
    def _agent_binds(repos: list[Repo]) -> tuple[Binds, Ids]:
        binds: Binds = []
        ids: Ids = {}
        for r in sorted(repos, key=lambda r: r.inside.count("/")):
            binds += [(r.worktree, r.inside), (os.path.join(r.root, ".git"), f"{GIT}/{r.slug}")]
            ids[r.inside] = _ids(r.worktree)
            ids[f"{GIT}/{r.slug}"] = _ids(os.path.join(r.root, ".git"))
        return binds, ids

    def views(self, mounts: list[tuple[str, str]], launch: Launch, git_ok: str = "") -> tuple[Binds, Ids]:
        """The binds that put the run's worktrees over its repositories, for one of the run's commands (read-write
        mounts given as (source, target)); before the run's first command, the worktrees are made. `git_ok`: why
        the run cannot have branches (its policy offers no git), or ''."""
        with self._locked() as m:
            if not m.made:
                m.made, m.branch = True, branch_name(self.run)
                found = [r for src, target in mounts for r in find(src, target)]
                if found and git_ok:
                    m.why = git_ok
                elif found:
                    self._make(m, found, launch)
            live = [r for r in m.repos if r.state == "open" and os.path.isdir(r.worktree) and _is_repo(r.root)]
            return self._agent_binds(live)

    def _make(self, m: Manifest, found: list[Repo], launch: Launch) -> None:
        d = self.rdir / "branches"
        d.mkdir(parents=True, exist_ok=True)
        binds: Binds = []
        ids: Ids = {}
        for i, r in enumerate(found):
            r.worktree = str(d / f"{i}-{r.slug}")
            os.makedirs(r.worktree, exist_ok=True)
            binds += [(r.worktree, r.inside), (os.path.join(r.root, ".git"), f"{GIT}/{r.slug}")]
            ids[r.inside] = _ids(r.worktree)
            ids[f"{GIT}/{r.slug}"] = _ids(os.path.join(r.root, ".git"))
        try:
            code, out = launch(binds, ids, create_script(found, m.branch), {})
        except BranchError as e:
            code, out = 1, ""
            for r in found:
                r.state, r.why = "failed", str(e)
        got = said(out)
        for i, r in enumerate(found):
            words, text = got.get(i, ([], ""))
            if words[:1] == ["open"] and len(words) > 1 and re.fullmatch(r"[0-9a-f]{40,64}", words[1]):
                r.base = words[1]
                r.name = self._name_of(r.worktree)
                if not r.name:
                    r.state, r.why = "failed", "the worktree's .git is not what git writes"
            else:
                r.state = "failed"
                r.why = r.why or text or (f"git exited {code}" if code else "git said nothing")
            if r.state == "failed":
                shutil.rmtree(r.worktree, ignore_errors=True)
        m.repos = found

    @staticmethod
    def _name_of(worktree: str) -> str:
        try:
            line = Path(worktree, ".git").read_text(errors="replace").strip()
        except OSError:
            return ""
        mm = re.fullmatch(r"gitdir: .*/worktrees/([^/\s]+)", line)
        return mm.group(1) if mm else ""

    def finish(self, outcome: str, message: str, launch: Launch) -> dict:
        """At the run's end: commit each worktree on the branch, merge it when the run ended done, remove the
        worktrees and their registrations. Returns what the run's page shows of each repository."""
        with self._locked() as m:
            if m.ended:
                return self._listing(m)
            m.ended = True
            live = [r for r in m.repos if r.state == "open"]
            for r in live:
                if not os.path.isdir(r.worktree) or not _is_repo(r.root):
                    r.state, r.why = "lost", "the worktree or the repository is no longer there"
            live = [r for r in live if r.state == "open"]
            if live:
                binds, ids = self._agent_binds(live)
                for r in live:  # the checkout the merge goes into
                    binds.append((r.root, f"{GIT}/{r.slug}{TREE}"))
                    ids[f"{GIT}/{r.slug}{TREE}"] = _ids(r.root)
                try:
                    code, out = launch(binds, ids, finish_script(live, m.branch, outcome), {"MSG": message})
                except BranchError as e:
                    code, out = 1, ""
                    for r in live:
                        r.why = f"{e}; the branch {m.branch} is left as it was"
                got = said(out)
                for i, r in enumerate(live):
                    words, text = got.get(i, ([], ""))
                    if words[:1] and words[0] in ("merged", "kept", "unchanged"):
                        r.state = words[0]
                        r.files = int(words[1]) if len(words) > 1 and words[1].isdigit() else 0
                        r.why = text
                    else:
                        r.state = "kept"
                        r.why = r.why or text or f"git exited {code}; the branch {m.branch} is left as it was"
            for r in m.repos:
                if r.name:
                    _unregister(r)
                if r.worktree:
                    shutil.rmtree(r.worktree, ignore_errors=True)
            return self._listing(m)


def _unregister(r: Repo) -> None:
    """Remove <git dir>/worktrees/<name>, opening every directory from the mount's source down without following a
    link (an agent could have put one anywhere under the repository)."""
    fds: list[int] = []
    try:
        fd = os.open(r.src, os.O_RDONLY | os.O_DIRECTORY)
        fds.append(fd)
        for part in [p for p in r.rel.split("/") if p] + [".git", "worktrees"]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            fds.append(fd)
        if "/" not in r.name and r.name not in ("", ".", ".."):
            shutil.rmtree(r.name, dir_fd=fd)
    except OSError:
        pass  # gone already, or not a directory any more: nothing of ours to remove
    finally:
        for fd in reversed(fds):
            os.close(fd)
