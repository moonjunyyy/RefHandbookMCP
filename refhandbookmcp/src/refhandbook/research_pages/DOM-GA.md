# PAGE DOM-GA — Geometry, algebra, representation
KIND: checklist
TAGS: research, domain
TRIGGERS: manifold; Lie algebra; representation; metric; connection; isomorphism
OBJECTIVE: Apply the checks of geometry, algebra and representation theory to the question's objects.

ENTRY — object: a K `@DOM-GA` (pushed by N2 exit a, or by a stage page), `on` the question's objects.

The work follows the chain: object → map or operation → preserved structure →
invariant → representation.

1. Identify each of the following, from the user's givens only:
   - the space, manifold, module, or algebra;
   - its dimension;
   - the field or ring;
   - the metric or norm;
   - the maps;
   - the group actions and representations;
   - the symmetry constraints.

   A metric, connection, or splitting the user did not give **is not assumed**.
2. For each important map, write `domain → map → codomain`. Record whether it
   is injective, surjective, invertible, metric-preserving,
   structure-preserving, or equivariant, and whether it is a projection or an
   embedding.
3. Geometry chain: tangent and cotangent structure → metric or connection →
   curvature → invariant → coordinate representation.
4. Algebra chain: operation → closure → identity and inverse → associativity
   and related laws → automorphisms → representations → invariant
   decomposition.
5. Record the relation between two constructions with its exact type:
   `eq`, `iso` (with the explicit map), `spec` (special case), or projection,
   quotient, or embedding.
6. When two constructions look equivalent, **construct the isomorphism**. Do not
   call them similar.
7. Check the draft against this confusion: do not treat a coordinate or
   representation artifact as intrinsic structure.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: the step 1 items all found in the user's givens → push `resume <caller move> on <objects>` @<caller>
- **b**: step 1 items missing → push one `record open/symbol row for <item>` per item (N1 LOOP), then `resume <caller move>` @<caller>
- **c**: the confusion listed in step 7 appears in the current draft → push `remove dependent work` @X5 (or @X1 if the task was substituted)
