# PAGE IM-SPECIFY — Specify before coding
KIND: checklist
TAGS: research, stage
TRIGGERS: specify; before coding; component; trace to a row; approximation; damping; prior; regularizer; default operator; implementation choice; input range; convergence
OBJECTIVE: Trace every component of the planned artifact to the rows it realizes, registering each departure as X and each premise the code relies on as A.

ENTRY — object: a K `@IM-SPECIFY` (from IM or another page's exit), `on` the objects to realize.

1. Write one line per component, before any code:
   `<function / module / parameter> — realizes <E1 / H2> — approximation / premise <X1 … / A3>`.
2. Each departure from the formal object gets `add X`, with its justification.
   An `X` changes how the extracted information is computed. It never adds
   information. Damping, priors, regularizers, filled-in unobserved directions,
   and default operators are **premises**, not approximations; they go to
   the next step.
3. Each premise the code relies on (input range, independence, inner-loop
   convergence, anything from the step above that adds information) gets
   `add A`. If the premise is model origin, it is registered `proposed` with
   evidence `closure: <the givens it was checked against>`, and the component
   that needs it is not run on the main line (X5). It is also never listed as
   an "implementation choice".
4. A component that traces to no row either signals a missing formalization or
   should not be there.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: every component traces to a row → push `build <components>` @IM-BUILD
- **b**: a component needs a model-origin premise → push `handle A# proposed` @X5
- **c**: a component signals a missing formalization → push `formalize <object>` @FM
