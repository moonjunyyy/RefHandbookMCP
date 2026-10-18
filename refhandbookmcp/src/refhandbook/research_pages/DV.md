# PAGE DV — Diverge: situate; label on request
KIND: checklist
TAGS: research, stage
TRIGGERS: position; prior work; novelty; readings; label; situate
OBJECTIVE: Situate an idea and, on request, offer minimal readings of its terms.

ENTRY — object: a K `@DV` (from N3 dispatch or another page's exit), `on` the objects to work.

Position and vocabulary, not exposition. Treat the user as a peer. A named
result gets one line unless more is asked for.

### DV1 — Situate

1. Extract the **minimal claim**: what the idea actually asserts, before any
   polishing. List the objects involved.
2. Map-build around the idea (QM2). Search; do not recall.
3. Write one line per find:
   `· <name/source> — <what it is> — <relation to the user's idea>`.
4. Be exact about novelty: state what the idea coincides with, and how far, and
   where it diverges. Neither inflate the novelty nor dissolve the idea into
   its neighbors.
5. Every connection has a positioned node, or is marked `not found` or gap.
6. Do not force the idea into the user's existing theory, or into a familiar
   one. Do not dismiss it for being unconventional.

### DV2 — Label (only when asked, or when a term's reading changes a mandatory verdict)

◆ Minimal reading first.

1. Give the minimal reading of the term: the same content in symbols, with no
   structure added. Its origin is `user`.
2. Give alternatives only if they change a verdict, one line each, each with
   the **observation or check that would distinguish it** from the minimal
   reading. Each is registered as `R`, with origin `model`, status `proposed`,
   and evidence `closure: <the user's words it was checked against>`.
3. Nothing proceeds on an alternative until the user adopts it (SKILL.md §4).

### DV3 — Connect across fields

1. Name the idea's structure: a symmetry, a projection, a conserved quantity, a
   duality.
2. Name where that structure has a name and tooling.
3. State the correspondence and where it breaks. A link without a formal
   correspondence is not reported.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: position report written → push `await the user's choice` @USER
- **b**: alternative readings offered (R `proposed`) → push `await adoption of R#` @USER
- **c**: ready to leave the stage: the user chose, and at least one of explicit definitions, equations, invariants, falsifiable consequences, or a well-defined question exists → push `formalize <adopted R / objects>` @FM
