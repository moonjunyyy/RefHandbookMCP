# PAGE DOM-PH — Physics
KIND: checklist
TAGS: research, domain
TRIGGERS: physical identification; units; symmetry; prediction; correspondence
OBJECTIVE: Apply the layered checks of physics (assumption to observation) to the question's objects.

ENTRY — object: a K `@DOM-PH` (pushed by N2 exit a, or by a stage page), `on` the question's objects.

The work follows the chain: primitive assumption (L0) → mathematical
consequence (L1) → geometric structure (L2) → physical identification (L3) →
prediction (L4) → comparison with observation. A derivation at level Ln never
validates level Ln+1 by itself.

1. Identify each of the following, from the user's givens only:
   - the idealizations;
   - the degrees of freedom and constraints;
   - the symmetries;
   - the observables;
   - the regime of validity.
2. Check dimensions and units, covariance or coordinate dependence, symmetry
   and conservation, the initial and boundary data, and limiting regimes.
3. Every physical identification is a row with an `int:` edge that names the
   explicit map or limiting regime. With no map, the link is recorded as
   **missing**. It is not filled by analogy.
4. Classify every claim as one of: exact derivation, conditional consequence,
   approximation, phenomenological model, analogy, or speculation.
5. **Comparison with an established theory:**
   1. derive the user's side first;
   2. state the established theory in its own terms, independently;
   3. then construct the correspondence, classified as exact equivalence,
      structural correspondence, limiting agreement, shared prediction, or
      analogy.
6. Separate exact reproduction, limiting correspondence, qualitative
   resemblance, and new prediction.
7. Check the draft against these confusions; do none of the following:
   - Create an automatic edge from mathematical resemblance to physical identity.
   - Reverse-engineer the user's assumptions just to reproduce a known result.
   - Present a conditional internal consequence as an established physical fact.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: the step 1 items all found in the user's givens → push `resume <caller move> on <objects>` @<caller>
- **b**: step 1 items missing → push one `record open/symbol row for <item>` per item (N1 LOOP), then `resume <caller move>` @<caller>
- **c**: a confusion listed in step 7 appears in the current draft → push `remove dependent work` @X5 (or @X1 if the task was substituted)
