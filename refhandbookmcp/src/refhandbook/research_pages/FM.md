# PAGE FM — Formalize: read first
KIND: checklist
TAGS: research, stage
TRIGGERS: formalize; definition; general structure; operator; read off; established equation; already given by the equations; derive the target
OBJECTIVE: Enter formalization: read the target from the established rows when they give it, and build only when reading fails, saying why.

ENTRY — object: a K `@FM` (from N3 dispatch or another page's exit), `on` the objects to work.

This stage produces checkable objects. It issues no verdicts.

◆ The established equations come before any new construction.

1. Try to read the target directly from the `E`, `T`, and user rows. Quote what
   was read.
2. If it can be read, record it (`add E`, with origin `entailed(<rows>)`).
3. Build only if reading fails, and state in one line why it failed. Never route
   through an intermediate object when an established equation already gives
   the target.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: target read from established rows → push `verify H#` @VF, or `await confirmation` @USER in a derivation chain
- **b**: the target cannot be read (why stated), so it must be built → push `define <objects>` @FM-DEFINE
- **c**: a reading (`R`) of a term fails → push `relabel R#` @DV-LABEL
