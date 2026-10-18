# PAGE DOM-AV — Analysis, variational problems, PDE, kernels
KIND: checklist
TAGS: research, domain
TRIGGERS: Euler-Lagrange; functional; PDE; boundary condition; kernel; variation
OBJECTIVE: Apply the checks of analysis, variational problems, PDE and kernels to the question's objects.

ENTRY — object: a K `@DOM-AV` (pushed by N2 exit a, or by a stage page), `on` the question's objects.

**EDGES.** Functional or equation → conditions → variation or operator → local
result → solution class → stability or global result.

**IDENTIFY (from the user's givens only).** Identify each of the following:

- the independent and dependent variables;
- the functional;
- the admissible function space and regularity;
- the boundary and initial conditions;
- **which quantities are fixed and which are varied**.

A variable the user did not declare fixed is **varied**. An endpoint the user
calls an output is never an input.

**CHECKS.**

1. **Variation:** admissible variation → first variation → integration by
   parts → boundary term → Euler–Lagrange equation in full vector form (not
   contracted) → stationary solution → second variation, if requested.
2. **PDE:** type and order → domain → data → symmetries → conserved quantities
   → solution strategy → limits.
3. **Kernel:** normalization, locality, positivity (if required), the semigroup
   property (if claimed), anisotropy, and the short-time and long-time limits.
4. Attach the boundary, regularity, and admissibility conditions to the
   **result row's config**, not only to the derivation text.

**DO NOT.** Confuse any of the following pairs:

- stationarity with minimum;
- local with global;
- formal with well-posed;
- coordinate simplification with invariance.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: IDENTIFY items all found in the user's givens → push `resume <caller move> on <objects>` @<caller>
- **b**: IDENTIFY items missing → push one `record open/symbol row for <item>` per item (N1 LOOP), then `resume <caller move>` @<caller>
- **c**: a DO NOT item appears in the current draft → push `remove dependent work` @X5 (or @X1 if the task was substituted)
