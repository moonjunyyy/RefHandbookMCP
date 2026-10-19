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

- **When.** `rs_o_review` lists REVIEW at `research_begin` 7 turns after the last review, or
  sooner once 3 signals gather: refusals of the work (logged as `refused: …` by every tool on a
  ledger; protocol refusals such as a stale token are not signals), UNAFFECTED disposals,
  carries and drops. The thresholds are the rule's text, so revising the rule retunes them.
- **Proposals.** `research_review` records the review (`review: <why>`) and may propose rules.
  A proposal is a kernel rule written by the model, so its authority is `proposed`: it runs at once
  on every ledger of the store, its findings shown as warnings, and it never blocks. The review
  prints its trial findings on the ledger at hand, so overconstraint shows before adoption.
- **Adoption.** Only the user's channel approves: `refhandbook proposals` shows each proposal with
  the hash of what it says, and `refhandbook approve rule <id> --seen <sha> [--retire <old>]`
  seals that version only (a proposal revised since is refused); `refhandbook reject <id>` retires
  it for good (the model cannot propose that id again). The approval page will do the same. A
  sealed rule may not rest on a proposed one.
- **Cost.** Every evaluation is bounded: a proposed rule gets 1 s per evaluation, and one that
  exceeds it is refused at proposal or retired by the kernel when it meets a large ledger; the
  sealed rules of a phase together get 30 s, past which the call fails instead of hanging.

## The sandbox workspace

One sandbox per user, shared by Chat sessions (the `sandbox_*` tools) and agents
(`agents/workspace.py`), on the same rule as the rules: the model writes what is proposed, the user
writes what governs.

- **Policy** — the user's grant, and the sandbox itself: the commands the sandbox shows (its
  `/usr/bin` holds only those; every other command directory is empty), the network, the limits.
  The model cannot write one. The kernel installs `default`: a coreutils-like set, a shell and
  Python, no network. Granted on `/agents` or with `refhandbook policy <name> …` on the server.
- **Script** — the model's to add and revise with no approval, because it can call only what its
  policy shows. A user's script cannot be overwritten by the model.
- **Job** — one run of one script version, queued by `sandbox_run`. The tool waits up to 50 s and
  otherwise returns the job id, so long computations run while the conversation goes on; while it
  waits it releases the server's call lock. A local server runs jobs in process; a remote one
  queues them for `refhandbook-runner.service`, the only unit that may create namespaces. Runners
  claim jobs by compare-and-swap; a job whose runner died is reaped as `lost`.

The sandbox (`agents/sandbox.py`) is user, mount, pid, net, ipc, uts and cgroup namespaces, a
pivot_root onto a tmpfs root, Landlock, and seccomp: a deny-list of dangerous calls, and ENOSYS for
any syscall newer than its table. Everything writable is mounted noexec, so nothing written runs
as code except through an allowed interpreter. `tests/test_sandbox_escape.py` runs real sandboxes
against each of these.

## The approval page

`/agents`, behind the site sign-in (RHB_AUTH=sso; nginx passes the SSO's X-Auth-Token for the
audience `refhandbook`): open proposals with the hash of what each says (approve or reject),
policies (grant or change), scripts and recent jobs. Forms carry a token bound to the signed-in uid
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
