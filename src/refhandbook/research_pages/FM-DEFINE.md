# PAGE FM-DEFINE — Define: four properties of each object
KIND: checklist
TAGS: research, stage
TRIGGERS: define; definition; well-defined; existence; non-empty; independence of representation; coordinates; domain and codomain; degeneracy; proxy; unknowns; reformulate
OBJECTIVE: Define each object to be built by settling its existence, independence of representation, domain and codomain, and degeneracy, each noted in the evidence cell.

ENTRY — object: a K `@FM-DEFINE` (from FM when reading fails, or another page's exit), `on` the objects to define.

For each object, settle and note (in the evidence cell) four things, then mark
unknowns and proxies.

1. **Existence**: it can be constructed and is non-empty.
2. **Independence of representation**: no dependence on a choice of
   representative or coordinates.
3. **Domain and codomain**: what maps to what, with the types matching.
4. **Degeneracy**: where the definition fails, and how that locus is handled.
5. Unknowns the user isolated go to `Z`.
6. A stand-in scalar for a form, tensor, or geometry is marked `proxy(X)` in
   its content. Both the `Z` rows and the proxies follow the card REF-USE
   use rules.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: every object defined, its four properties noted → push `register the premises of <objects>` @FM-PREMISES
- **b**: a definition fails because a term's reading (`R`) does not fit → push `relabel R#` @DV-LABEL
