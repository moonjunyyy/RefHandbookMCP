# PAGE DOM-FND — Foundations
KIND: checklist
TAGS: research, domain
TRIGGERS: primitives; axioms; well-founded; infinity; equivalence relation
OBJECTIVE: Apply the checks of foundational constructions to the question's objects.

ENTRY — object: a K `@DOM-FND` (pushed by N2 exit a, or by a stage page), `on` the question's objects.

**EDGES.** Primitive definitions → axioms → constructions → derived structure.

**IDENTIFY (from the user's givens only).** Identify each of the following:

- the primitive objects;
- the equality and identity notion, and any equivalence relations;
- the allowed operations and closure conditions;
- the ordering;
- the finitary or infinite status;
- the notion of observation or distinguishability, if present.

**CHECKS.** Run in order:

1. For each claimed structure, ask whether it follows from the primitives.
   - If yes, derive it.
   - If no, name the extra axiom it needs and register it as `A`, origin
     `model`, status `proposed`.
2. Classify each existence claim as one of: explicit construction, finite
   recursion, limiting construction, existence theorem, or completed infinite
   object.
3. Check each of the following:
   - hidden use of infinity;
   - circular definitions;
   - closure and well-foundedness;
   - validity of equivalence relations;
   - dependence on choice or order;
   - cardinal versus ordinal statements;
   - algebraic versus topological assumptions.

**DO NOT.** Import standard real-analysis or set-theoretic assumptions when the
construction is deliberately foundational.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: IDENTIFY items all found in the user's givens → push `resume <caller move> on <objects>` @<caller>
- **b**: IDENTIFY items missing → push one `record open/symbol row for <item>` per item (N1 LOOP), then `resume <caller move>` @<caller>
- **c**: a DO NOT item appears in the current draft → push `remove dependent work` @X5 (or @X1 if the task was substituted)
