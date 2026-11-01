# PAGE REF-DEP — dep cells: one relation, within and across ledgers
KIND: reference
TAGS: research, reference
TRIGGERS: dep syntax; dep cell; dep token; ref; relation type; cross-ledger ref; another ledger; ref:<ledger>/<id>; basis check; propagation; PENDING; old relation word; req; sup; eq; iso; spec; int; con; unknown relation; delete a relation to pass a gate; claim premises
OBJECTIVE: The syntax of a dep cell, that every edge is a basis, how a row of another ledger is cited, what follows the edges, and where a claim's premises come from.

Consulted when writing or reading a `dep` cell, or when a basis check or a
PENDING propagation follows one; return to the step that sent you.

**One relation.** A `dep` cell holds the rows the row rests on: `ref:ID` (or a
bare `ID`) for a row of this ledger, `ref:<ledger>/ID` for a row of another ledger
of the same store (`ref:ratio-kernel/E2`). There is nothing else to choose: an
edge means the row rests on its target. What the row does with the target — uses,
derives from, is equivalent to, compares with — is said in the evidence cell, in
words, where it can be read and checked.

Every edge is followed by the basis checks (a missing, replaced, stale, proposed,
model-origin or pointer-only target) and by propagation: a change of the target's
content, or a status that invalidates it, opens PENDING on every row that rests
on it — in this ledger, and in every other ledger whose rows cite it. A dep edit
alone (what a row rests on, not what it says) opens nothing downstream; the row's
own basis is checked when the session ends.

A row that only compares with, or mentions, another row does not cite it in
`dep`: the comparison goes in the evidence cell. In particular a user row cannot
rest on a model row, by any spelling — either the user adopts the row, or the
citation is a sentence, not an edge.

Across ledgers: a cross-ledger target must exist when the cell is written. Its
checks read as `<ledger>/<id>` ("rests on ratio-kernel/E2 with status
'superseded'"). A change there opens `PENDING <row> (from <ledger>/<id>)` here,
which this ledger's next chat session disposes like any other. A ledger that is
deleted leaves its citers resting on missing rows. Renaming a ledger does not
rewrite the cells that cite it: cite by the name that will stay.

Old relation words: cells written before 0.11 may still read `req:`, `der:`,
`eq:`, `iso:`, `spec:`, `int:`, `sup:` or `con:`. They are read as `ref` (every
one of them a basis). Writing them is refused.

A directive (`U`) and a plan object (`K`) are the exceptions: their `dep` names
the rows they are about (where they work), and nothing rests on it or follows
from it. A row that replaces another does not rest on what it replaces: name
the old row in the evidence (`supersedes R41`), not in `dep`.

A claim's premises come from its configuration, not from `dep`. A true verdict
that rests on an external result `T` of this ledger needs that `T` in the
configuration.
