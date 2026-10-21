# PAGE FM — Formalize: read first, then define and claim
KIND: checklist
TAGS: research, stage
TRIGGERS: definition; general structure; operator; formalize; premises; claims
OBJECTIVE: Turn adopted readings into checkable objects: read first, then define, register premises, and derive claims.

ENTRY — object: a K `@FM` (from N3 dispatch or another page's exit), `on` the objects to work.

This stage produces checkable objects. It issues no verdicts.

### FM1 — Read first

◆ The established equations come before any new construction.

1. Try to read the target directly from the `E`, `T`, and user rows. Quote what
   was read.
2. If it can be read, record it (`add E`, with origin `entailed(<rows>)`).
3. Build only if reading fails, and state in one line why it failed. Never route
   through an intermediate object when an established equation already gives
   the target.

### FM2 — Define

For each object, settle and note (in the evidence cell) four things:

- **existence**: it can be constructed and is non-empty;
- **independence of representation**: no dependence on a choice of
  representative or coordinates;
- **domain and codomain**: what maps to what, with the types matching;
- **degeneracy**: where the definition fails, and how that locus is handled.

Unknowns the user isolated go to `Z`. A stand-in scalar for a form, tensor, or
geometry is marked `proxy(X)` in its content. Both follow the card REF-PROV use
rules.

### FM3 — Premises

1. Record each user premise as its own atomic `A` row, with origin `user`.
2. If the construction seems to need more, first ask: does anything the user
   gave already presuppose it? If so, the origin is `entailed(<cited step>)`.
3. Otherwise, run **X5** step 3: the premise is registered `proposed` and
   explored in a configuration (EX), never built into the main line.
4. Alternatives to one premise (smooth / Lipschitz / BV; finite / countable)
   are separate `A` rows that share a `grp`, so that a configuration can swap
   one for another.

### FM4 — Structure

1. Extract from the given relations the form of the operator or map: what it
   acts on, what it preserves, and whether it is linear.
2. Leave unspecified functions and values as symbols (X9).
3. Stay at the level of structure unless asked to descend.
4. Do not import machinery (multipliers, an extra functional, a background
   metric) when the given flow or equations already do that job.

### FM5 — Claims

1. List what must hold if the definitions are right:
   - consistency;
   - invariance;
   - correspondence with known special cases, in the appropriate limit;
   - type agreement;
   - boundary behavior;
   - generality.
2. Before marking a claim `open`, check whether user or entailed rows already
   settle it.
3. A claim that bears on a mandatory `C` becomes `add H`, with its
   configuration, status `open`. Any other claim becomes a `P` row.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: target read from established rows (FM1) → push `verify H#` @VF, or `await confirmation` @USER in a derivation chain
- **b**: objects built and claims registered → push one `verify H#` @VF per claim (queued)
- **c**: a reading fails → push `relabel R#` @DV
- **d**: a needed premise is not given or entailed → push `handle A# proposed` @X5
