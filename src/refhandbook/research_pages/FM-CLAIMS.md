# PAGE FM-CLAIMS — Claims: what must hold
KIND: checklist
TAGS: research, stage
TRIGGERS: claims; what must hold; consistency; invariance; special case; limit; type agreement; boundary behavior; generality; register claims
OBJECTIVE: List what must hold if the definitions are right, and register each claim as an H row (when it bears on a mandatory C) or a P row.

ENTRY — object: a K `@FM-CLAIMS` (from FM-STRUCTURE or another page's exit), `on` the defined objects and their structure.

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

- **a**: objects built and claims registered → push one `verify H#` @VF per claim (queued)
