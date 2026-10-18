# PAGE REF-PROV — Provenance, relations, and approximations
KIND: reference
TAGS: research, reference
TRIGGERS: origin; entailed; model origin; relation type; approximation; proxy
OBJECTIVE: Rules for classifying an item's origin, typing relations, and telling approximation from added information.

Consulted from a card step; return to that step. Not a procedure: it consumes no K.

Origins and the use table are in the research skill (§4). This card holds the
rules for classifying items, typing relations, and exploring premises.

**Classifying an item's origin is itself a claim.** Compare the item with the
user's words before labeling it.

- Something that realizes the user's described operation in the minimal way is
  `entailed(<quote>)`, even if the model wrote it down.
- Mislabeling in either direction is an error:
  - labeling as `model` in order to disown work;
  - labeling as `user` in order to own work.

A model item stays out of the main line until the user adopts it; it may be
explored in a named configuration meanwhile. On adoption, `set` its
origin to `user(adopted, turn N)`. Content cells hold only the user's words for
user items; notes go in the evidence cell.

**Relations** (typed `dep` edges; syntax in REF-LEDGER). Record the exact relation. Never
infer one relation from surface similarity.

- `sup` (supports) is evidence, not proof. A claim becomes `true` only through
  `req` or `der` edges under explicit assumptions.
- `iso` and `int` need the explicit map, written in the evidence cell.
- `spec` marks a special case. A result on a `spec` row does not transfer to the
  general row.
- Mathematical resemblance never creates an `int` edge to a physical or
  empirical identity.
- **Approximation versus information.** An `X` row may change *how* the
  available information is computed: discretization, finite samples,
  tolerances. An `X` row may never *add* information: priors, damping or
  regularization, filled-in unobserved directions, default structure.
  Anything that adds information is an `A` row with origin `model`: it stays
  out of the main line and may be explored (X5, EX).
- **External results** (`T`) stay external. A verdict that rests on `T1` holds
  only in configurations that contain `T1`.

**Exploration.** Every verdict sits in a claim × configuration cell.
- `main` is the user's line: the `A` and `T` rows that are `on`.
- Named configurations are the model's to define freely. They may switch
  premises on or off, swap alternatives, and include model premises.
- Taint propagates. A row built on a model row is itself `model`. A `user` or
  `entailed` row that rests on a model row is an error.
- An exploration verdict is reported with its configuration, and never stands
  in for the main line.
- Only the user adopts a premise into the main line.
