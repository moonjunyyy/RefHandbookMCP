# PAGE REF-LEDGER — Ledger: sections, vocabulary, configurations, tools
KIND: reference
TAGS: research, reference
TRIGGERS: ledger format; status vocabulary; research tools; configuration spec; dep syntax; section letters
OBJECTIVE: Definitions for the ledger the research_* tools keep: sections, statuses, relations, configurations, documents, and the tools themselves.

This page is consulted from a card step; return to that step afterwards. It is
not a procedure and consumes no K.

**Sections.** Each row has the columns `id · content · origin · status ·
evidence · dep`. Ids are the section letter plus a number, assigned by the
device.

| letter | holds | allowed status |
|---|---|---|
| U | directives and questions | active · question · answered · done · blocked · superseded |
| C | judgment criteria | mandatory · free · superseded |
| R | readings of the user's terms | confirmed · proposed · superseded · refuted |
| S | symbols | confirmed · proposed · superseded |
| A | assumptions (`grp` marks alternatives) | on · off · proposed · superseded · stale |
| Z | isolated unknowns | isolated · superseded |
| T | known results | on · proposed · superseded · refuted · stale |
| E | objects and structures | established · open · proposed · superseded · stale · history |
| H | claims (status = main-line verdict) | open · true · false · undecided · supports · contradicts · inconclusive · superseded · refuted · stale · history · proposed |
| X | approximations | on · off · proposed · superseded · stale |
| P | parked byproducts | parked · superseded |
| K | plan objects | queued · running · blocked (user) · done · dropped · superseded · stale |

The map `M` is free text, replaced whole with `research_set(id="M")`.

**dep.** A `dep` cell holds tokens of the form `[rel:]ID`. Each `rel` is either a
**basis** (the row rests on the target) or a **link** (it relates to the target
without resting on it):

| class | rel | meaning |
|---|---|---|
| basis | `req` (the default) | requires |
| basis | `der` | derived from |
| basis | `eq` | equivalent to |
| basis | `iso` | isomorphic to; needs the map |
| basis | `spec` | a special case of |
| basis | `int` | interprets; needs the map |
| link | `sup` | supports: evidence, not proof |
| link | `con` | contradicts |
| link | `ref` | refers to, without resting on it |

Basis checks (a stale, replaced, model-origin or pointer-only target) and
propagation (PENDING) follow basis edges only. Record a relation honestly as a
link instead of deleting it to pass a gate. A relation the device does not know
counts as a basis.

A claim's premises come from its configuration, not from `dep`. A true verdict
that rests on an external result `T` needs that `T` in the configuration.

**Configurations.**
- `main` is always the set of `A` and `T` rows that are `on`. Only the user
  switches it.
- Named configurations are defined with `research_explore(action="config")`.
  Their spec is built from these tokens:
  - `main`;
  - `+A5`, which adds a premise;
  - `-A2`, which removes one;
  - `A3>A7`, which swaps one for another;
  - plain ids.
- Alternatives from one `grp` exclude each other.
- A verdict lives in a claim × configuration cell. A cell can go stale on its
  own, without affecting the claim's other cells.

**Documents.**
- `source`: the user's original. Read-only, hash-checked.
- `deliverable`: for the reader. It has section markers, a reader lint, and
  goes through plan → sync.
- `working`: the model's own files.

**Tools.**

| tool | purpose |
|---|---|
| `research_ledgers` | list · init · status · export (`include_log`) · import (`to`, `dry_run`, `ref`) · copy · rename |
| `research_ledger_delete` | delete a ledger permanently (`confirm` repeats its id) |
| `research_begin` | open a turn: TOKEN, ledger view (`recent` · `brief` · `full`), OBLIGATIONS |
| `research_show` | read the ledger (`open_only`, `ids`, `recent`) |
| `research_add` | add a row |
| `research_set` | replace one cell, or the map `M` |
| `research_dispose` | VALID · RECHECK · INVALID · UNAFFECTED for a PENDING hit |
| `research_carry` | keep a `U` open past this turn, with a reason |
| `research_push` | push a plan object |
| `research_next` | take the next plan object and print its card |
| `research_done` | finish a plan object through an exit |
| `research_drop` | drop a plan object, with a reason |
| `research_explore` | config · verdict · matrix |
| `research_doc` | register · plan · sync · check (`text`, or `ref` for a staged blob) |
| `research_blob` | put · append · info: send a long text once (in pieces if needed), then pass its `ref` |
| `research_review` | done: record a review of the rules (`why`) and propose rule changes (`rules`), tried as warnings until the user adopts them · proposals: the open ones (card RV) |
| `research_check` | consistency check, or the `closure` of ids |
| `research_end` | close the turn: RECEIPT, ledger, Δ, NEXT |

Every write needs the newest TOKEN. A REFUSED names what to resolve (card X7).

**Checks to know when porting a ledger.**
- `check` judges the basis of `proposed` rows as well as settled ones: a
  proposed row resting on a superseded, refuted or stale row is an error. A
  ledger kept by hand often never checked that, so expect errors on import
  (`research_ledgers(action="import", dry_run=true)` lists them first).
- `[unverified]` propagates only from the evidence's first token. A note
  elsewhere in a cell ("the quoted lemma is [unverified]") does not mark the
  row unverified; write `[unverified] …` at the start when it is.
- One K waits for the user at a time: pushing page USER re-arms it.
