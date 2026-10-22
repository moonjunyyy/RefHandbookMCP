# PAGE FM-PREMISES — Premises: one atomic row each
KIND: checklist
TAGS: research, stage
TRIGGERS: premises; assumptions of the construction; atomic premise; presupposed premise; needs more than given; alternative premises; smooth or Lipschitz; finite or countable; grp
OBJECTIVE: Register each premise the construction rests on as its own atomic A row with its origin, keep model premises off the main line, and make alternatives to one premise swappable.

ENTRY — object: a K `@FM-PREMISES` (from FM-DEFINE or another page's exit), `on` the defined objects.

1. Record each user premise as its own atomic `A` row, with origin `user`.
2. If the construction seems to need more, first ask: does anything the user
   gave already presuppose it? If so, the origin is `entailed(<cited step>)`.
3. Otherwise, run **X5** step 3 (exit b): the premise is registered `proposed`
   and explored in a configuration (EX), never built into the main line.
4. Alternatives to one premise (smooth / Lipschitz / BV; finite / countable)
   are separate `A` rows that share a `grp`, so that a configuration can swap
   one for another.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: premises registered (`user` or `entailed`) → push `extract the structure of <objects>` @FM-STRUCTURE
- **b**: a needed premise is not given or entailed → push `handle A# proposed` @X5
