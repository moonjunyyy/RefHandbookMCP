# PAGE DOM-SI — Signal and inverse problems
KIND: checklist
TAGS: research, domain
TRIGGERS: inverse problem; forward operator; identifiability; aliasing; Fourier phase
OBJECTIVE: Apply the forward-first checks of signal and inverse problems to the question's objects.

ENTRY — object: a K `@DOM-SI` (pushed by N2 exit a, or by a stage page), `on` the question's objects.

The work follows the chain: latent state → forward operator → sampling →
observation → identifiable equivalence class → estimator → reconstruction.

1. Identify the latent parameters, the forward process, the sampling process,
   and the observation model, from the user's givens only.
2. **Forward first.** Do not design an inverse method before the forward model
   is specified well enough to decide identifiability.
3. Proceed in order:
   1. latent parameters;
   2. forward operator;
   3. sampling and aliasing;
   4. invariants under observation;
   5. identifiable combinations;
   6. degeneracies;
   7. estimator;
   8. uncertainty;
   9. reconstruction check.
4. **Inverse check.** Can two distinct latent states give the same observation?
   - If yes, characterize the equivalence class.
   - If no, state the conditions that guarantee uniqueness.
5. **Fourier.** Keep magnitude, phase, frequency, orientation, conjugate
   symmetry, and sampling geometry separate. Complex phase is discarded only
   when it is proven irrelevant to the requested parameter.
6. **Output.** Report a parameter together with its uncertainty and its
   degeneracy, rather than a bare estimate.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: the step 1 items all found in the user's givens → push `resume <caller move> on <objects>` @<caller>
- **b**: step 1 items missing → push one `record open/symbol row for <item>` per item (N1 LOOP), then `resume <caller move>` @<caller>
- **c**: the current draft breaks the rule of step 2 or step 5 → push `remove dependent work` @X5 (or @X1 if the task was substituted)
