# PAGE IM — Implement: traceable realization
KIND: checklist
TAGS: research, stage
TRIGGERS: implement; simulate; measure; numerics; experiment; code
OBJECTIVE: Realize a formal object as a traceable artifact and read its runs back as evidence.

ENTRY — object: a K `@IM` (from N3 dispatch or another page's exit), `on` the objects to work.

This stage realizes objects in order to measure them. Verify, by contrast,
decides claims.

### IM0 — Entry

◆ If the user asked to implement, implement.

1. Implement when the user asks, or when a claim is empirical and the user
   agrees.
2. A symbolic alternative may be offered once, after the implementation, and
   never instead of it.

### IM1 — Specify before coding

| component | realizes | approximation / premise |
|---|---|---|
| <function / module / parameter> | E1 / H2 | X1 … / A3 |

1. Each departure from the formal object gets `add X`, with its justification.
   An `X` changes how the extracted information is computed. It never adds
   information. Damping, priors, regularizers, filled-in unobserved directions,
   and default operators are **premises**, not approximations; they go to
   the next item.
2. Each premise the code relies on (input range, independence, inner-loop
   convergence, anything from the item above that adds information) gets
   `add A`. If
   the premise is model origin, it is registered `proposed` with evidence
   `closure: <the givens it was checked against>`, and the component that
   needs it is not run on the main line (X5).
   It is also never listed as an "implementation choice".
3. A component that traces to no row either signals a missing formalization or
   should not be there.

### IM2 — Build

1. Build the smallest artifact that fully satisfies every active `U`.
   Minimality never removes a stated requirement.
2. Use the user's symbols as names.
3. Fix seeds, record configuration and versions, and leave no unexplained
   constant.
4. When the artifact is to be kept, deliver it as files.

### IM3 — Test ladder

Declare each rung's pass criterion (metric, tolerance, range) before running it.

1. **Known case.** Reproduce a `computed` or `sourced` answer. A failure here is
   a bug.
2. **Invariants.** Ledger invariances and boundary claims hold within tolerance.
3. **Measurement.** Only after rungs 1 and 2 pass.

### IM4 — Read back

1. Record for each run: assumption configuration, run configuration, seeds,
   result with uncertainty, and range.
2. Record each affected claim with `research_explore(action="verdict")`
   under the configuration the run realized. The verdict is `supports`,
   `contradicts`, or `inconclusive`, with evidence `measured`. A measurement
   never makes a claim `true`, and never covers more than its range.
3. A new stable pattern becomes an `H` row only if it bears on a mandatory `C`.
   Otherwise it becomes a `P` row.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: a rung fails at the known case → push `debug <component>` @IM
- **b**: measurement recorded (IM4) → push `await reaction to results` @USER
- **c**: a component needs a model-origin premise → push `handle A# proposed` @X5
