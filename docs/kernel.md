# The scope-graph kernel

Status: step 1 of the migration. The kernel exists beside the legacy stores and reproduces the
research ledger's semantics exactly; the MCP tools still run on the legacy code.

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

1. Run the `research_*` tools on the kernel. Rows, edges and verdicts are then written as graph
   rows, and the dep, status and evidence cells become renderings of that structure.
2. Replace the global tool-call lock with a per-store lock, and deploy on free-threaded 3.14t.
3. Build the approval page.
4. Build the sandbox, `invoke`, and background runs.
