# The scope-graph kernel

Status (0.7.0): the kernel is live. Each store is migrated the first time the server opens it,
and the research gates are decided by the kernel's rules. The legacy tables remain the write path.

## Running on a server

The first open of a user's store after the upgrade does the following:

1. It copies the store to `users/<uid>.db.pre-kernel`.
2. It loads the cards and every ledger into the kernel tables (`k_*`) of the same file.
3. It verifies each ledger with `kernel/verify.compare`, which checks:
   - the export round trip;
   - the `check()` messages;
   - the obligations;
   - the end blockers of an open turn.
4. It records `kernel_status` in `k_meta`:
   - `active` when every ledger matches;
   - `legacy: <differences>` otherwise. The store then keeps the legacy gates, and the server log
     says why.

After the migration, the graph stays current with every write:

- a write that seals a ledger re-projects that ledger inside the same transaction, so a rollback
  undoes both;
- a card change re-projects the cards;
- a rename or delete drops the old image;
- the change log is carried over append-only.

While a store is `active`, the kernel decides the gates:

- `research_check`, and the CHECK lines of `research_end`, come from the package's check rules;
- the obligations of `research_begin` come from its obligation rules;
- the refusals of `research_end` come from its close rules.

The legacy computation runs beside the kernel as a cross-check. A disagreement goes to the server
log and to `k_log` (`divergence: …`), and the kernel's answer stands. The tests set
`RHB_KERNEL_STRICT=1`, which turns a divergence into a failure.

To turn the kernel off, set `RHB_KERNEL=0` in `/etc/refhandbook/env` and restart. The legacy
engine then runs alone, and nothing is written to `k_*`. To undo the migration completely, stop
the service and put `users/<uid>.db.pre-kernel` back in place.

Cost: each sealed write re-projects the whole ledger. On the largest server ledger (565 rows) a
call took 0.2–0.35 s on 2 vCPU. Projecting only the rows that changed is the obvious
optimisation.

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

`tests/conftest.py` hooks every sealed write to a legacy ledger in the whole test suite. Each time,
it loads the ledger into a fresh graph and requires four results:

- the export round-trips unchanged;
- `check()` errors and warnings match word for word;
- the begin obligations match;
- the `research_end` blockers match, with and without an idle reason.

`tests/test_kernel_migration.py` adds a ledger built so that every one of the 34 gate rules fires.
It also includes a test that the harness fails when the two sides disagree.

## Next

1. Make the graph the write path. Rows, edges and verdicts would be written as graph rows, and
   the dep, status and evidence cells would become renderings of that structure.
2. Replace the global tool-call lock with a per-store lock, and deploy on free-threaded 3.14t.
3. Build the approval page.
4. Build the sandbox, `invoke`, and background runs.
