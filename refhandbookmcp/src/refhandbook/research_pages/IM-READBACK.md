# PAGE IM-READBACK — Read runs back as evidence
KIND: checklist
TAGS: research, stage
TRIGGERS: read back; record the run; results; measured; uncertainty; range; supports; contradicts; inconclusive; stable pattern
OBJECTIVE: Record each run with its configurations, seeds, result, uncertainty, and range, and turn it into measured verdicts on the affected claims under the configuration it realized.

ENTRY — object: a K `@IM-READBACK` (from IM-TEST or another page's exit), `on` the runs.

1. Record for each run: assumption configuration, run configuration, seeds,
   result with uncertainty, and range.
2. Record each affected claim with `research_explore(action="verdict")`
   under the configuration the run realized. The verdict is `supports`,
   `contradicts`, or `inconclusive`, with evidence `measured`. A measurement
   never makes a claim `true`, and never covers more than its range.
3. A new stable pattern becomes an `H` row only if it bears on a mandatory `C`.
   Otherwise it becomes a `P` row.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: measurement recorded → push `await reaction to results` @USER
