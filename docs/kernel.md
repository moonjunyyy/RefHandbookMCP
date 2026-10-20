# The scope-graph kernel

Status (0.8.0): the kernel is the only judge. `research_check`, the obligations of
`research_begin` and the refusals of `research_end` come from the package's rules; there is no
second computation beside them. Writes still land in the legacy `rl_*` tables, and every write
that seals a ledger re-projects it into the graph in the same transaction, so a rollback undoes both.

## Running on a server

Opening a store runs its migrations once each, in order, and records the schema in `k_meta`:

| step | what it does |
|---|---|
| backup | the first open copies the store to `users/<uid>.db.pre-kernel` |
| schema 1 | loads the cards and every ledger into `k_*`, and checks each ledger by round trip (the export rebuilt from the graph must equal the export). A ledger that does not round-trip is **quarantined**: its tools refuse with the reason, its rows stay intact in `rl_*` and export normally, and the other ledgers work. Stores migrated by 0.7.0 are recognised as schema 1. |
| quarantine | belongs to the data, not the name. Every first projection of a ledger id (import, copy, rename, migration) is admitted only by round trip, so a copy or rename of quarantined data is refused; deleting the ledger lifts its quarantine. |
| packages | every open compares the installed package rules with the code's: a rule still as installed (its last writer is the kernel) is replaced; a rule the user changed in any field or retired is kept, and if the package changed it too the conflict is logged (`package conflict: …` in `k_log`); a rule the package dropped is retired unless another rule still uses it. If the new rules cannot stand beside the store's own, the model's proposals are retired first; if the user's rules conflict, the upgrade is deferred and logged. The store always opens. |
| newer schema | a store whose schema is newer than the code is refused before anything is written to it: upgrade the server instead |

After that the graph follows every write: a seal re-projects its ledger (only when its
fingerprint changed), a card change re-projects the cards, a rename or delete drops the old image,
and the change log is carried over append-only. Facts the rules need that are counts over the log
(the rule language has no aggregates) are derived at projection, as `derived_*` attributes.

To undo the migration, stop the service and put `users/<uid>.db.pre-kernel` back in place.

Cost: each sealed write re-projects the whole ledger. On the largest server ledger (565 rows) a
call takes 0.2–0.35 s on 2 vCPU, and the migration of both server ledgers 0.3 s. Projecting only
the rows that changed is the obvious optimisation.

## Reviewing the rules

The rules are data, so they are reviewed like data (card `rs-rv`):

- **When.** `rs_o_review` lists REVIEW at `research_begin` 7 sessions after the last review, or
  sooner once 3 signals gather: refusals of the work (logged as `refused: …` by every tool on a
  ledger; protocol refusals such as a missing session or a CONFLICT are not signals), UNAFFECTED
  disposals, carries and drops. The thresholds are the rule's text, so revising the rule retunes them.
- **Proposals.** `research_review` records the review (`review: <why>`). A rule change is a rule
  capability record (below): `cap(kind="rule", action="add"|"update", name=<id>, spec=…)`. A rule
  the model writes has authority `proposed`: it runs at once on every ledger of the store, its
  findings shown as warnings, and it never blocks. The write prints its trial findings on every
  ledger, so overconstraint shows before adoption. (`research_review rules=…` still works, as a
  deprecated alias.)
- **Adoption.** Only the user's channel approves (`/agents`, or `refhandbook proposals` and
  `refhandbook approve rule <id> --seen <approval>` on the server). The rules a proposal replaces
  are recorded as data beside it (`replaces`), never read from the model's prose, and the approval
  hash covers the proposal and each rule it retires: anything changed since the user looked is
  refused. `refhandbook reject <id>` retires a proposal for good (the model cannot propose that id
  again). A sealed rule may not rest on a proposed one.
- **Cost.** Every evaluation is bounded: a proposed rule gets 1 s per evaluation, and one that
  exceeds it is refused at proposal or retired by the kernel when it meets a large ledger; the
  sealed rules of a phase together get 30 s, past which the call fails instead of hanging.

## Sessions

A session (`kernel/sessions.py`, table `k_sessions`) is one participant's span of work on a scope:
a chat session per user message, an agent session per delegated run. Its token is stable for the
whole session. Sessions run side by side: a write names the objects it changes and is refused
(CONFLICT) only if another session changed one of them after this one read it (`k_writes`, and
`k_seen` for what a session read since its begin). A session closes over what it opened (the
pending hits it raised, the K it runs, the document plans it committed); a chat session also answers
for the user's directives and the continuation. One left open is resumed by the next
`research_begin` of its role once idle (30 min).

## Capabilities

Everything added to what the system does is a capability record (`kernel/capabilities.py`): a
script, a sandbox policy, a layer, a rule, a card, an alias. One tool family, `cap`, for every kind.

- **Records and versions.** `cap:<kind>:<name>` is a node with its owner (the author), the version in
  force, and a TTL; `k_cap_versions` holds every version, immutable (spec as JSON, a body for scripts
  and layers, author, note). `update` writes a new version; `restore` brings back an old one as a
  new version; history is never rewritten.
- **States.** proposed → active → deprecated (still works, warns, names what replaces it) → retired
  (out of force, history kept) → purged after 90 days. A proposal nobody approves expires after the
  kind's grace.
- **Who.** The owner changes a record; the model changes only its own. A version the model writes
  that widens a grant (each kind says what widens: a policy's commands, network, ports, limits,
  layers, mounts; a layer built with the network) waits for the user's approval on `/agents` (or
  `refhandbook cap approve <kind> <name> --version N`), with the version in force kept meanwhile.
  Everything else is in force at once.
- **TTL.** When `review_after` passes, the sweep (at most once a minute: on the cap tools, and in
  the runner loop) runs the kind's check on the version in force: a pass renews the TTL, a failure
  deprecates the record with the reason and counts a review signal (`cap:signals`). The kernel's own
  records repair themselves where the kind knows how (the default policy drops a command the host
  no longer has). A script's check can run its own self-test as a job.
- **Kinds** are registered by packages: `rule`, `alias`, `card` (`kernel/capkinds.py`); `policy`,
  `script`, `layer` (`agents/capkinds.py`). A kind validates a spec, says what widens, applies a
  version (writes what the rest of the system reads: the policy and script nodes the runner reads,
  the kernel rule, the handbook card) and checks it.
- **Old tool names** (`sandbox_*`, `research_review rules=`) are kernel-owned alias records,
  deprecated from the start: they work with a warning and stop when the alias retires (30 days).

## The sandbox workspace

One sandbox per user, shared by Chat sessions (the `cap`, `run`, `job`, `files` tools) and agents
(`agents/workspace.py`). Policies, scripts and layers are capability records.

- **Policy** — the sandbox itself: the commands it shows (its `/usr/bin` holds only those; every
  other command directory is empty; `["*"]` shows every command of the host and its layers), the
  network and its ports, the limits, the layers it stacks, and mounts of the user's own data. The
  kernel installs `default`: a coreutils-like set, a shell and Python, no network. The user grants
  on `/agents` or with `refhandbook policy <name> …` on the server; the model may propose one.
- **Mounts** — `{source, target, rw}`. The administrator names the directories users may mount with
  `RHB_SANDBOX_MOUNT_ROOTS` (colon-separated; `{user}` and `{uid}` name the store's owner, e.g.
  `/data/{user}`); a source outside them, or a target over the sandbox's own directories, is
  refused. Read-only unless `rw`; a read-write mount is noexec like every writable mount.
- **Layer** — what a policy can stack on the base: a build script run as root inside a sandbox (the
  build's own, with the network only if granted), whose changes under `/usr/local`, `/opt` and
  `/etc` become a read-only tree (`<db>.sandbox/layerstore/`). Built as a job; a policy that lists a
  layer resolves its commands from the layer first, and may execute beneath `/usr/local` and `/opt`.
- **Script** — the model's to add, revise, deprecate and remove with no approval, because it can
  call only what its policy shows; `requires` names the commands it needs, checked at every write
  and review. A user's script cannot be overwritten by the model.
- **Job** — one run of one script version, queued by `run`. The tool waits up to 50 s and
  otherwise returns the job id, so long computations run while the conversation goes on; while it
  waits it releases the server's call lock. A local server runs jobs in process; a remote one
  queues them for `refhandbook-runner.service`, the only unit that may create namespaces. Runners
  claim jobs by compare-and-swap; a job whose runner died is reaped as `lost`.

The sandbox (`agents/sandbox.py`) is user, mount, pid, net, ipc, uts and cgroup namespaces, a
pivot_root onto a tmpfs root, Landlock, and seccomp: a deny-list of dangerous calls, and ENOSYS for
any syscall newer than its table. `tests/test_sandbox_escape.py` runs real sandboxes against each
rule below.

- **Nothing written runs as code**, except through an allowed interpreter: every writable mount is
  noexec, `/dev` is read-only and noexec, and memfds are noexec (`vm.memfd_noexec=2` in the
  sandbox's pid namespace; where that cannot be set, `memfd_create` is refused).
- **What runs is the view**: with a command list, Landlock grants execution only beneath `/usr/bin`
  (the view) and the dynamic loader. The loader can still map any readable ELF, so the view bounds
  the vocabulary and the namespaces bound the capability.
- **The network is a list of ports**: a policy that grants the network shares the host's network,
  and Landlock (ABI 4+) lets TCP connect only to the policy's `ports` (default 80 and 443) and
  never bind, so the host's loopback services stay out of reach. UDP is not limited.
- **Limits**: memory and cpu through a delegated cgroup leaf per job (the runner unit has
  `Delegate=yes`), else RLIMIT_AS; the workspace's size is watched during a run and a job that takes
  it over the policy's `disk_mb` is stopped.
- **The host never follows a name the sandbox can write**: `files` walks paths on directory
  descriptors with O_NOFOLLOW, opens only regular files (O_NONBLOCK, then fstat), and removes a
  symlink as a link.

Open: every user's jobs run as the runner's uid outside the namespaces. `Spec.outside_uid` maps a
per-user id, but it needs a runner with CAP_SETUID and per-user ownership of the workspaces.

## The approval page

`/agents`, behind the site sign-in (RHB_AUTH=sso; nginx passes the SSO's X-Auth-Token for the
audience `refhandbook`): grants waiting (each capability version that widens what the model may do,
with what it widens; approve or reject), rule proposals with the hash of what each says, policies
(grant or change, with layers and mounts), every capability record and recent jobs. Forms carry a token bound to the signed-in uid
and must come from the site's own origin. What it writes is written as `user`.

## Large arguments

A long text (a document, an export) is sent once with `research_blob` (put, then append for the
pieces), stored by its sha256 in `k_blobs`, and passed to `research_doc` and `research_ledgers`
as `ref` (12 or more hex digits of the hash). An append consumes the blob it extends, so a text
sent in pieces is stored once, and blobs older than 7 days are pruned when a store opens.

## What is fixed, and what is data

The kernel fixes only:

- the meta-schema (`k_types`, `k_type_class`, `k_states`, `k_state_class`, `k_transitions`,
  `k_nodes`, `k_edges`, `k_rules`, `k_log`);
- the rule evaluator (`kernel/rules.py`);
- the scope gates (`kernel/scopes.py`);
- the authority model (`kernel/graph.py`).

Everything else is rows: node, edge and scope types, the states a type may be in and the classes
those states belong to, who may make which transition, and every obligation, gate and integrity
check. The research ledger is one package of such rows (`kernel/packages/research.py`); the
handbook cards are another.

## Scopes, not turns

A scope is a node of a scope type. It opens if the type's `pre` rules find no block, and closes if:

- the `close` rules of its type find no block;
- every attached child scope is closed, carried with a reason, or detached to an enclosing scope;
- the `check` rules of every enclosing scope find no block.

A conversation turn is one scope type (`turn`, inside a `ledger`). The kernel knows none of them by
name. A background run is a child scope that is detached outward, so the turn that started it can
close while the enclosing scope keeps the duty.

## Authority

| authority | written by | effect | changed or removed by |
|---|---|---|---|
| kernel | code | — | a release |
| sealed | the user, or a package the user installed | a `block` blocks | the user |
| proposed | the model | a `block` is reported as `warn` | the model or the user |

The actor of a write is decided by the server, not by the caller's arguments. A tool call is
`model`. `user` must come from a channel the model cannot drive: the approval page.

What the model cannot do, whatever the arguments:

- write unvalidated data;
- set a scope's state, or delete a scope;
- write the scope edges `contains`, `carry` and `touched` directly (those go through
  `open_scope`, `carry`, `touch` and `detach`);
- delete a node it did not write;
- change what a sealed rule means.

The last point holds in two ways. A sealed rule may not rest on a proposed rule, and
`class`/`tclass` ignore proposed types.

`origin` is the provenance a row claims. `author` is who actually wrote the node, and rules read it
with `author(Id, A)`.

A proposed rule that fails at evaluation becomes a warning about itself. The sealed rules are
evaluated apart from it.

## The rule language

A Datalog fragment, compiled to SQLite. The full grammar is in the docstring of
`kernel/rules.py`.

```
rs_c_bad_basis(R, D, S) :- rs_basis_row(Self, X, R), not rs_model(X), rs_dep(X, _, Dn),
    not node(Dn, missing, _), class(Dn, not_basis), attr(Dn, rid, D), attr(Dn, status, S).
```

- **Graph atoms:** `node`, `class`, `tclass`, `edge`, `attr`, `origin`, `content`, `state_decl`.
- **Builtins:** `match` (regex), `prefix`, comparisons, `+` `-` and `len`.
- **Evaluation:** rules are safety-checked and stratified, then evaluated to a fixpoint.
- **Messages:** a gate rule's message formats its head variables.
- **Null and ordering:** `=` and `!=` are null-safe, and ordering applies only between two numbers.
- **Refused at definition time:** a rule that could only fail later (a non-string pattern, a
  format spec, an out-of-range number) is refused when it is defined.

## How equivalence is checked

`tests/conftest.py` hooks every sealed write to a ledger in the whole test suite and requires that
the graph holds the ledger exactly: the export rebuilt from the graph equals the export. The
judgments themselves are the package's rules, which the research suites test directly.
`tests/test_kernel_migration.py` builds a ledger on which every gate rule fires.

## Next

1. Make the graph the write path. Rows, edges and verdicts would be written as graph rows, and
   the dep, status and evidence cells would become renderings of that structure.
2. Replace the global tool-call lock with a per-store lock, and deploy on free-threaded 3.14t.
3. The agent runner (docs/agents.md P3): agents use the same workspace and policies as Chat,
   with a shell (`sh`) as an extra tool.
