# PAGE IM-TEST — Test ladder
KIND: checklist
TAGS: research, stage
TRIGGERS: test; test ladder; known case; reproduce a known answer; invariants hold; tolerance; pass criterion; measurement run; bug
OBJECTIVE: Run the artifact up the test ladder (known case, invariants, then measurement), each rung against a pass criterion declared before running.

ENTRY — object: a K `@IM-TEST` (from IM-BUILD or another page's exit), `on` the built artifact.

Declare each rung's pass criterion (metric, tolerance, range) before running it.

1. **Known case.** Reproduce a `computed` or `sourced` answer. A failure here is
   a bug.
2. **Invariants.** Ledger invariances and boundary claims hold within tolerance.
3. **Measurement.** Only after rungs 1 and 2 pass.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: a rung fails at the known case → push `debug <component>` @IM-BUILD
- **b**: rungs 1 and 2 passed and the measurement ran → push `read back <runs>` @IM-READBACK
