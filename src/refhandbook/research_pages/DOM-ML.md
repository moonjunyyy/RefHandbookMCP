# PAGE DOM-ML — Learning systems: optimization and geometry
KIND: checklist
TAGS: research, domain
TRIGGERS: parameter space; loss; Fisher; gradient; estimator; optimization
OBJECTIVE: Apply the checks of learning systems, optimization and their geometry to the question's objects.

ENTRY — object: a K `@DOM-ML` (pushed by N2 exit a, or by a stage page), `on` the question's objects.

The work follows the chain: model assumption → objective → mathematical
quantity → estimator → optimization procedure → empirical result.

1. Identify each of the following, from the user's givens only, and
   **separately**:
   - the data space x and the parameter space θ;
   - the model f;
   - the objective;
   - the probability model;
   - the optimization dynamics;
   - the geometry or metric of each space;
   - which quantities are observed and which are latent.
2. **Derivatives.** For each derivative, record the variable differentiated,
   the variables held fixed, whether it is total or partial, the dependence
   through intermediate variables, and the **tensor shape**. A scalar standing
   in for a tensor is `proxy(X)`.
3. **Theory to implementation.** For each theoretical quantity, determine:
   is it observable, exactly computable, or estimable? By what estimator? With
   what bias and variance, what cost, what differentiability? How does it enter
   training?
4. **Validation.** Keep these separate: mathematical consistency, optimization
   feasibility, statistical identifiability, and empirical usefulness.
5. Check the draft against these confusions; do none of the following:
   - Silently identify x-space geometry with θ-space geometry.
   - Treat an estimated quantity as the true one.
   - Complete a rank-deficient estimated form (damping, preconditioners, priors)
     without a user premise. Act on the supported subspace only (for example, a
     pseudo-inverse), and do not move along directions the estimate does not
     support.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: the step 1 items all found in the user's givens → push `resume <caller move> on <objects>` @<caller>
- **b**: step 1 items missing → push one `record open/symbol row for <item>` per item (N1 LOOP), then `resume <caller move>` @<caller>
- **c**: a confusion listed in step 5 appears in the current draft → push `remove dependent work` @X5 (or @X1 if the task was substituted)
