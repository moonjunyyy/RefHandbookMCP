# PAGE N3b — Integrate
KIND: checklist
TAGS: research, normal
TRIGGERS: where do we stand; summary of results; integrate; standing of the program
OBJECTIVE: Report the standing of the program by structure, with each result's configuration and the boundaries exploration found.

ENTRY — object: a K routed `@N3b`; its `on` ids are the rows at issue.
ENTRY — signal: verdicts exist, but the program's standing is unclear.

1. Run N1 step 1.
2. Report by **structure, not turn order**:
   - established results, with their configuration;
   - refuted results, with their counterexample;
   - measured results, with their range;
   - exploration results, each with its configuration, and the boundary
     `research_explore(action="matrix")` reports;
   - open items, with their blockage;
   - gaps;
   - the status of each `U`.
3. Pose the next questions. Re-root the map only after the user confirms.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: structured report written → push `await reaction to the report` @USER
- **b**: next questions posed → push one `map <question>` @QM per question (queued)
- **c**: the question itself shifted → push `confirm re-root` @USER
