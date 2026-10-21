# Autonomous agents

Status: partly built. The sandbox, the workspace it shares with Chat sessions (policies, scripts,
layers and mounts as capability records, jobs and the runner) are built and tested; see
`docs/kernel.md` ("Capabilities", "The sandbox workspace"). The agents themselves (`team.py`,
`providers.py`, `keys.py`) are first implementations without tests, and run on the research
ledger as `agent` sessions (`research_begin(role="agent")`), which answer only for what they open.

A user who has registered their own API keys (Anthropic, OpenAI, Google) asks for a **run**: a goal,
a grant (how many agents, how deep, how much), and a pruning policy. On the remote server, a
**runner** spawns agents for it. Each agent is an LLM loop that may use a **sandbox**, the
user's store, and the other agents. The agents pass knowledge to each other, share it, split work,
and clone themselves. The run ends when the kernel's gates let it close, not when a model says it
is done.

The philosophy is the one the handbook already follows:

| Principle (today) | Here |
|---|---|
| State lives in the store, not in the model's context | An agent is a scope node. Its knowledge is note nodes, its messages are packet nodes, and its transcript is a file the node points to. A killed runner resumes every agent from the store. |
| Gates decide the end (`research_end` refuses) | `finish` closes the agent's scope, so it runs the `close` rules. A run closes only when its own rules pass. |
| The server decides the actor | Every write that follows from a model's tool call is `model`, which means `proposed`. Grants, slots and tickets are written by `user`, and only from the approval page. |
| Model origin taints | Each note records the agent, provider and model that wrote it. A note is `verified` only by a different agent. |
| Limits are data | The number of agents is the number of slot and ticket nodes the user sealed. A rule, not code, refuses the next spawn. |
| Cards, found by symptom | Agent procedures are `ag-*` cards (lead, worker, verifier, abnormal). An agent stuck on a symptom calls `lookup`. |

## 1. Processes

```
                     internet
                        │  TLS (nginx / Caddy)
                        ▼
 ┌──────────────────────────────────────────┐      ┌─────────────────────────────────────────────┐
 │ refhandbook.service            (exists)   │      │ refhandbook-runner.service             (new) │
 │  MCP tools, OAuth, /login                 │      │  scheduler (asyncio), one task per agent     │
 │  + agent_run tool (request/status/cancel) │      │  provider adapters: anthropic|openai|gemini  │
 │  + /agents pages: keys, approve, runs     │      │  context compiler (pruning)                  │
 │  holds the PUBLIC key for API keys only   │      │  holds the PRIVATE key (LoadCredential)      │
 └───────────────┬──────────────────────────┘      │  spawns the sandbox  ─────────────┐          │
                 │                                 └──────────────┬────────────────────│──────────┘
                 │   both open users/<uid>.db (WAL), CAS writes   │                    ▼
                 └──────────────► /var/lib/refhandbook ◄──────────┘     ┌─────────────────────────┐
                                  users/<uid>.db                        │ sandbox (per tool call)  │
                                  runs/<uid>/<run>/…                    │ userns+mntns+pidns+netns │
                                  auth.db (+ api_keys, ciphertext)      │ Landlock, seccomp, cgroup│
                                                                        │ no network, no keys      │
                                                                        └─────────────────────────┘
```

- **The runner is a separate unit.** The MCP service keeps its current hardening
  (`RestrictNamespaces=yes`, `@system-service`), which a sandbox launcher cannot run under. The
  runner unit is the only one that may create namespaces, the only one that holds decrypted API
  keys, and the only one that speaks to the providers. Its configuration is in §7.
- **The two processes share only the store.** A run request is a node. The runner finds open
  runs that have a grant and takes a lease on each agent (`attrs.lease = runner id + expiry`,
  written by compare-and-swap). If the runner dies, the lease expires and the next runner resumes
  the agent at its last completed step.
- **Prerequisite: the store becomes multi-process.** `Handbook` opens SQLite in the default rollback
  journal (`store.py:132`). It needs to move to `journal_mode=WAL` and `busy_timeout`, and the
  runner keeps its write transactions short: it never holds one across an LLM call or a sandbox
  exec. The in-process `_CALLS` lock (`server.py:45`) is untouched by the runner, and replacing it
  with a per-store lock (`docs/kernel.md`, Next 2) still helps the MCP side.

## 2. API keys: registered per user

The model never sees a key, the sandbox never holds one, and the internet-facing process cannot
decrypt one.

- **Registration** happens on the page `/agents/keys`, behind the same sign-in as `/login`:
  - `RHB_AUTH=sso`: nginx `auth_request` vouches for the user;
  - `pam` / `ldap`: each POST carries the directory password, as `/login` does, so there are
    still no cookies or sessions.

  The page takes a provider, a label and the key. It checks the key once with the provider's
  model-list call, encrypts it, and drops the plaintext.
- **Encryption** is a sealed box made from what `cryptography` already provides (pulled in by
  `pyjwt[crypto]`): an ephemeral X25519 key, then HKDF-SHA256, then AES-256-GCM.
  - The associated data is `uid | provider | label`, so a row moved to another user or provider
    fails to decrypt.
  - The web process has only `/etc/refhandbook/agent-keys.pub`.
  - The runner receives the private key through systemd `LoadCredential=`. The root file is
    `/etc/refhandbook/agent-keys` (0400), and no other unit can read the credential.
- **Storage:** an `api_keys` table in `auth.db` holding uid, provider, label, ephemeral public key,
  nonce, ciphertext, a fingerprint (`sk-…abcd`), created, last_used, and status.
- **Use:** the runner decrypts a key per call and keeps it only in local variables. Any exception
  text is scrubbed of the key before it reaches a log, a note or the model.
- **Revocation:** a key can be deleted on the page. An agent whose key is gone parks with the
  abnormal card `ag-x-key`. The MCP tool `agent_keys` lists only providers, labels and
  fingerprints.

## 3. The kernel package `agents`

Like `kernel/packages/research.py`, this package is vocabulary and rules, with no Python logic
about agents.

### Types

| type | kind | what it is |
|---|---|---|
| `run` | scope | One goal. It may sit inside a `ledger` scope, detached from the turn that asked for it, so the turn can close while the run goes on. |
| `agent` | scope | One LLM loop. Children are `contains`-attached to their parent agent. The root agent is attached to the run. |
| `grant` | node | The user's approval of a run: providers and models allowed, budgets, pruning defaults, `max_depth`. Written by `user` only. |
| `slot` | node | One unit of concurrency, reusable. Written by `user` only. |
| `ticket` | node | One spawn, consumed for good. Written by `user` only. |
| `note` | node | A unit of knowledge. States: `proposed`, `verified`, `disputed` (all live), and `retired`, `superseded` (finished). |
| `packet` | node | A message: who sent it, to whom, a digest, and the notes it carries. States: `sent`, `read`. |
| `artifact` | node | A file published from a workspace: path and sha256. |
| `transcript` | node | Points at `transcripts/<agent>.jsonl`: provider, model, bytes, tokens, and the parent prefix for a clone (§4). |
| `governed_by` | edge | run → grant |
| `occupies` | edge, kernel authority | agent → slot |
| `consumes` | edge, kernel authority | agent → ticket |
| `spawned` | edge | parent agent → child, `attrs.mode = fresh \| split \| clone` |
| `holds` | edge | agent → note: its working set, `attrs.pin` |
| `posted` | edge | note → run: shared on the run's board |
| `carries`, `to` | edge | packet → note, packet → agent |
| `derived_from` | edge | note → note, artifact |

`occupies` and `consumes` have kernel authority. A model cannot write them, so it cannot pick its
own slot.

### Limits as rows: slots and tickets

The rule language has no aggregates (`kernel/rules.py`), so "at most N live agents" cannot be a
count. Instead, the user seals N slot nodes and M ticket nodes with the grant. Opening an agent
scope claims one of each inside the same transaction, and the `pre` rules check the claim:

```
ag_pre_no_slot(A)    :- node(Self, agent, _), A = Self, not ag_has_slot(Self).
ag_has_slot(X)       :- edge(X, occupies, _).
ag_pre_slot_busy(S, B) :- edge(Self, occupies, S), edge(B, occupies, S), B != Self, node(B, agent, open).
ag_pre_ticket_used(T, B) :- edge(Self, consumes, T), edge(B, consumes, T), B != Self.
ag_pre_forged(S)     :- edge(Self, occupies, S), author(S, A), A != user.
ag_pre_foreign(S)    :- edge(Self, occupies, S), attr(S, run, R1), attr(Self, run, R2), R1 != R2.
ag_pre_too_deep(D, M) :- attr(Self, depth, D), attr(Self, run, R), edge(R, governed_by, G),
                         author(G, user), attr(G, max_depth, M), D > M.
```

- **Slots** bound concurrency. A closed agent no longer holds its slot, because
  `ag_pre_slot_busy` reads only open holders.
- **Tickets** bound the total number of spawns, because `ag_pre_ticket_used` reads holders in any
  state.
- **Forgery is impossible**, because `author(S, user)` must hold.

**Budgets are the exception.** Summing tokens and cost needs aggregation, so v1 enforces them in
the runner against the grant's numbers, which are still data. The usage counters are written
by the runner as `kernel`. If the kernel's rule language later gains `count`/`sum`, budgets move
into rules too.

### Close rules

- `agent` (Self = the agent):
  - a packet from one of its children is still `sent` (the parent has not read a child's
    result) → block;
  - no exit packet → block;
  - an open child that is neither carried nor detached is already blocked by the kernel.
- `run`:
  - the root agent is not closed → block;
  - no exit packet addressed to `user` → block;
  - a note `verified` by its own author (`attr(N, by, A), attr(N, verified_by, A)`) → block, as a
    check rule on every scope within the run.

## 4. Knowledge: transfer, share, split, clone

Knowledge moves **by reference**. A note exists once in the graph. Transferring it adds edges,
not text, and each receiver renders it to text under its own pruning level (§5). Notes are deduped
by content hash.

| operation | tool | what happens in the graph | cost |
|---|---|---|---|
| **share** | `note(…, post=true)` / `post(id)` | `posted` edge to the run. Every agent's `recall` sees it. | O(1) |
| **transfer** | `send(to, text, refs, handoff)` | `packet` → `to` agent, plus `carries` → notes. The receiver is woken. | O(refs) |
| **split** | `spawn(mode="split", parts=[{goal, give}], join="all"\|"race")` | One child per part. Each `holds` only the notes it was given and starts from a fresh transcript. | O(parts) |
| **clone** | `spawn(mode="clone", n, variants)` | Each child copies the parent's `holds` edges and starts from the parent's transcript prefix (below). | O(n), cached prefix |
| **fresh** | `spawn(mode="fresh", role, goal, give)` | A new agent, given only what is passed to it. | O(refs) |
| **join** | `wait(ids, any\|all)` | The parent sleeps without making LLM calls until child exit packets arrive. | 0 tokens while waiting |
| **verify** | `verify(note, verdict, evidence)` | `proposed` → `verified`/`disputed`. The verifier must be another agent. | |

- **Join modes:**
  - `all`: the parent resumes when every child has exited.
  - `race`: the first child whose exit passes its close rules wins, and the runner cancels the
    siblings. Each cancelled sibling writes a short digest packet first, so its findings are not
    lost.
  - A verifier agent comparing clone exits gives a vote.
- **Clone and providers:**
  - A clone **within one provider** copies the transcript by reference (`transcript.attrs.parent
    = <agent>@<offset>`), so the clone's first call shares the parent's prompt prefix. Anthropic
    serves that prefix from the cache marked with `cache_control`, and OpenAI and Gemini cache
    long prefixes on their own.
  - A clone **across providers** cannot reuse the transcript, because reasoning items, thinking
    blocks and thought signatures are provider-specific. It falls back to a digest (§5), as
    `transfer` does.
- **Handoff level** (`handoff=` on send, spawn, and the exit packet):
  - `refs`: note ids only; the receiver opens what it needs;
  - `digest`: a structured digest note (goal, done, open, decisions, refs);
  - `full`: the whole transcript, within the same provider only.

## 5. Pruning: chosen per run, overridable per agent

Pruning applies in three places. Each has its own level, and the user picks the defaults in the
grant. A spawn may override them for its child; whatever the level, the budget bounds the cost.

**(a) Context: what one LLM call sees.** The context compiler builds each call in a fixed order,
so the prefix stays stable for the provider's cache:

```
[system: ag-role card · tool schemas] [run brief · grant summary] [pinned notes, by id] [last digest] [transcript tail]
```

| level | transcript tail | when it compacts |
|---|---|---|
| `full` | everything | only when the window is nearly full (forced digest) |
| `trim` (default) | old tool outputs are replaced by a stub (`[output elided: spill/s41.txt, 3.2 KB, sha…]`) that `read` can recover. Model text is kept. | at the same forced point |
| `digest` | after N steps or T tokens, the agent writes a digest note (by card `ag-x-digest`) and its tail restarts from it | every checkpoint |
| `minimal` | only the last step. Everything else is fetched through `recall` / `open` on demand. | every step |

Compaction happens **only at checkpoints**, never a little on every call, so the cached prefix
survives between checkpoints.

**(b) Handoff:** `refs`, `digest` or `full`, as described in §4.

**(c) Retention: what remains in the store after the run closes.**

| level | kept as live notes | the rest |
|---|---|---|
| `all` | every note | |
| `verified` (default) | verified and pinned notes, and the exit packets | → `retired` (still searchable with `recall(include_retired)`) |
| `exits` | the exit packets and the notes they carry | → `retired` |
| `purge` | the exit packets only | deleted, and the workspace is removed |

Transcripts and spill files follow retention: kept under `all`, and removed under `exits` and
`purge`.

## 6. The runner loop

Each agent is one asyncio task:

```
loop:
  lease(agent)                                  # CAS on attrs.lease; lost lease → stop
  if waiting and no new packet: sleep until woken (no LLM call)
  ctx  = compile(agent, pruning)                # §5
  resp = adapter[provider].step(ctx, tools)     # one model turn
  append transcript; usage += resp.usage         # one short write transaction
  for call in resp.tool_calls:
      result = dispatch(call)                   # sandbox | knowledge | team tools
      spill large output to runs/…/spill/, return head + tail + path
  if budget low:   inject card ag-x-budget (digest, finish)
  if no progress for K steps: inject ag-x-stuck
  if finish() succeeded (close rules passed): free slot, wake parent, end
```

- **Tools offered to an agent:**
  - sandbox: `sh(cmd, timeout)`, `read(path, range)`, `write(path, text)`, `ls(path)`, and
    `publish(path)` (creates an artifact and copies it into `shared/`);
  - knowledge: `note`, `recall`, `open`, `pin`, `retire`, `verify`, and `lookup` / `open_entry`
    for handbook cards;
  - team: `spawn`, `send`, `wait`, `cancel` (its own descendants only), `checkpoint`, `finish`.
- **Scheduling:**
  - at most one model call in flight per agent;
  - per-provider concurrency limits, with backoff on 429 and 529 responses;
  - agents waiting on `wait` cost nothing;
  - a spawn while no slot is free does not fail. It records a `queued` spawn request, which
    still consumes a ticket, and the scheduler opens it when a slot frees.
- **Efficiency guidance** in the `ag-lead` card:
  - spawn for independent, context-heavy subtasks;
  - give children `refs`, not transcripts;
  - prefer cheaper models for workers;
  - use `race` only while slots are idle.
- **Provider adapters** are plain `httpx` against the three REST APIs (Anthropic Messages, OpenAI
  Responses, Gemini `generateContent`), with no SDKs; `httpx` is already present through `mcp`.
  - Each adapter maps one neutral shape (messages, tool schemas, tool calls, tool results, usage)
    onto its API.
  - The provider-native turn is stored verbatim in the transcript, so the reasoning state is passed
    back exactly as the API requires.
  - A `fake` adapter replays scripted turns for tests.
- **Crash safety:** a step is committed after the model's turn and after each tool result. A
  resumed agent re-sends its compiled context, and tool calls are not replayed.

## 7. The sandbox: Linux primitives only

The sandbox needs no Docker, bubblewrap or gVisor: only the kernel, libc (through `ctypes`) and
the Python stdlib. The launcher is `refhandbook sandbox-exec`, started by the runner for each tool
call. It is stateless. Files persist in the agent's workspace, and processes do not outlive the
call.

```
runs/<uid>/<run>/
  work/<agent>/      the agent's RW tree, mounted at /work
  shared/            published artifacts, RO for every agent of the run, at /shared
  spill/             full tool outputs (the runner's; not mounted)
  transcripts/       (the runner's; not mounted)
```

Launch sequence (the child process, before `execve`):

1. **cgroup v2.** The runner unit has `Delegate=yes`, so it owns a subtree. The launcher creates
   `…/runs/<run>/<agent>/<call>`, sets `memory.max`, `memory.swap.max=0`, `pids.max` and
   `cpu.max`, and moves itself in. On timeout the runner writes `cgroup.kill`, which takes the
   whole tree. Without delegation, `setrlimit` stands in (`RLIMIT_AS`, `NPROC`, `CPU`, `FSIZE`,
   `NOFILE`), and `sandbox-check` says so.
2. **Namespaces.** `os.unshare(CLONE_NEWUSER | NEWNS | NEWPID | NEWNET | NEWIPC | NEWUTS |
   NEWCGROUP)` (Python ≥ 3.12), then the uid/gid maps (`agent` 1000 ↔ the service uid,
   `setgroups=deny`), then a fork, so the child is pid 1 of its namespace. The new network
   namespace has only a downed `lo`: **no network**.
3. **Filesystem.** A tmpfs root, with mounts made through `ctypes` `mount(2)`:
   - read-only binds of `/usr`, the `/lib*` symlinks, `/bin`, `/etc/ld.so.cache`, `/etc/ssl` and
     `/etc/alternatives`;
   - a synthesized `/etc/passwd` and `/etc/group`;
   - `/work` RW, and `/shared` RO;
   - tmpfs `/tmp` (with `size=`), a fresh `/proc`, and a minimal `/dev` (`null`, `zero`,
     `urandom`, `tty` bind-mounted).

   Then `pivot_root(2)`, unmount the old root, and remount `/` read-only. A tool directory
   (`RHB_SANDBOX_TOOLS`, prepared by root) can be mounted RO at `/opt/tools`.
4. **Landlock** (ABI ≥ 1; ABI 4+ adds TCP rules), applied as defence in depth over the mount
   namespace: write only under `/work` and `/tmp`, read-and-execute on the RO mounts, nothing
   else. The ruleset is made through `ctypes` `syscall(444–446)`.
5. **seccomp.** `PR_SET_NO_NEW_PRIVS`, then a classic-BPF deny list assembled in Python and loaded
   with `prctl(PR_SET_SECCOMP)`. It denies:
   - mounting and namespace syscalls: `mount`, `umount2`, `pivot_root`, `unshare`, `setns`, and
     namespace flags on `clone`/`clone3`;
   - `ptrace`, `process_vm_*`, `bpf`, `perf_event_open`, `userfaultfd`, `io_uring_*`;
   - `keyctl`, `add_key`, `request_key`, `kexec_*`, `*_module`, `reboot`, `swapon`/`swapoff`,
     `acct`, `quotactl`, `open_by_handle_at`.

   It also kills on a foreign architecture.
6. **Exec** with a clean environment (`PATH`, `HOME=/work`, `LANG`; nothing inherited), a
   timeout, and stdout and stderr capped. The full output goes to `spill/`.

- **Disk:** without root, there are no filesystem quotas. `RLIMIT_FSIZE` bounds a single file, and
  the runner checks the workspace size after each call (refusing further writes past the
  grant's `disk_mb`).
- **Cloning a workspace:** `cp -a --reflink=auto`. That is instant on OpenZFS 2.2+ block cloning,
  btrfs and XFS, and a plain copy elsewhere, counted against `disk_mb`. An overlay over a parent
  that keeps writing would be undefined, so clones snapshot.

`refhandbook sandbox-check` reports each capability and the fallback it will use:

- unprivileged userns (and, if the host forbids them through Ubuntu's
  `kernel.apparmor_restrict_unprivileged_userns=1`, the sysctl that lifts it);
- the Landlock ABI;
- seccomp;
- cgroup delegation and its controllers;
- reflink.

On this development machine (WSL 6.18, Python 3.14.7), userns works, the Landlock ABI is 7, and
cgroup v2 offers `cpuset cpu io memory pids`.

### Runner unit (deploy/refhandbook-runner.service)

It differs from `refhandbook.service` in these lines:

```
ExecStart=/opt/refhandbook-venv/bin/refhandbook runner --data-dir /var/lib/refhandbook
Delegate=yes                                   # cgroup subtree for per-job limits
RestrictNamespaces=user mnt pid net ipc uts cgroup
SystemCallFilter=@system-service @mount @sandbox unshare pivot_root sethostname   # the launcher's, before its own seccomp
SystemCallErrorNumber=EPERM
RestrictAddressFamilies=AF_UNIX AF_NETLINK AF_INET AF_INET6
ReadWritePaths=/var/lib/refhandbook            # no ProtectKernelTunables: it blocks the sandbox's /proc
```

The unit uses kernel primitives and systemd only: no LSM profile, so it runs the same on WSL2 and on
distributions without AppArmor.

## 8. Threat model

| threat | answer |
|---|---|
| Model-written code tries to escape | userns with no privileges on the host, pivot_root, Landlock, seccomp, cgroup. Nothing in the sandbox runs as the service uid outside the namespace. |
| A key leaks through the sandbox | Keys are never in the sandbox: not in env, not in files, and the namespace has no network. The runner's memory is not reachable from the sandbox, a separate pid namespace. |
| A key leaks through the web process | It holds only the public key. |
| Prompt injection raises authority | A model writes `proposed` only. It cannot write grants, slots or tickets, or the `occupies`/`consumes` edges. |
| Cross-user access | A store and a run directory per uid. The runner opens a run's store by the uid in the run's path, and the launcher binds only that run's tree. |
| Runaway cost | Budget in the grant, enforced by the runner before every call, plus tickets. `ag-x-budget` forces wrap-up at 90 %. |
| Runaway resources | cgroup limits per call, `cgroup.kill` on timeout, `disk_mb`. |
| Data goes to a provider | Only to the providers the user registered and allowed in the grant. |

## 9. Surfaces

- **MCP** (for the user's interactive Claude):
  - `agent_run(action=request|status|tree|log|result|cancel, …)`. `request` creates the run and
    returns the approval URL. Nothing runs before approval.
  - `agent_keys()`: the registered providers, without key material.
- **Pages** (the approval page of `docs/kernel.md`):
  - `/agents/keys`;
  - `/agents/runs/<id>/approve`, which shows the goal, providers and models, slots, tickets,
    depth, budgets and pruning, and writes the grant, slots and tickets as `user`;
  - `/agents/runs`, the live tree, usage and cancel.
- **CLI:** `refhandbook runner`, `refhandbook sandbox-check`, `refhandbook sandbox-exec` (internal),
  and `refhandbook agent-keys gen` (makes the X25519 pair for `install.sh`).

## 10. Build order

| phase | content | tests |
|---|---|---|
| P0 | `sandbox.py` (launcher, Landlock, seccomp, cgroup, rlimit fallback), `sandbox-check` | escape attempts: write outside `/work`, network, `mount`, `ptrace`, fork bomb, memory hog, timeout kill |
| P1 | Store in WAL, multi-process CAS; the `agents` package (types, slot, ticket, close rules) | every gate fires; forged slot; slot reuse; depth |
| P2 | Provider adapters plus `fake`; context compiler with the four pruning levels | golden contexts per level; cache-stable prefix |
| P3 | Runner: leases, scheduler, tools, spawn/split/clone/race/wait, budgets, resume after a kill | scripted multi-agent runs on `fake` |
| P4 | Key sealing, `/agents` pages, `agent_run` / `agent_keys` tools, `ag-*` cards | page flows as in `test_remote.py` |
| P5 | Deploy: runner unit, `install.sh` key pair, nginx routes | `sandbox-check` on the server |

## Open choices

- **Whose uid runs the sandbox.** As designed, the sandbox runs as the service uid, mapped to
  `agent` inside a user namespace. It needs no root, and it cannot touch the user's home directory.
  Running it as the user's own POSIX uid, with their home mounted, would need a root helper
  (`systemd-run --uid`). That is left for later.
- **Network inside the sandbox.** None in v1. An allowlist (package indexes, git hosts) would need
  a proxy outside the namespace, reached through a socket bound into it.
- **Budget unit.** Tokens per provider is exact. USD needs a price table to maintain.
