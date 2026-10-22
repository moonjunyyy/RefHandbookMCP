# PAGE REF-CHECKS — Check patterns by claim shape
KIND: reference
TAGS: research, reference
TRIGGERS: check pattern; how to check; claim shape; equality; cancellation; invariance; conservation; correspondence; limit; type agreement; dimension; boundary behavior; generality; randomized substitution; dependence on premises
OBJECTIVE: The executed check that decides each shape of claim, and how long symbolic runs are split.

Consulted from VF step 5 (or any card that runs a check), after the pass criterion is declared (X7); return to that step. Not a procedure: it consumes no K.

| claim shape | executed check |
|---|---|
| equality or cancellation | the difference simplifies to 0 |
| invariance or conservation | the derivative along the flow is 0 |
| correspondence | the limit or substitution minus the known form is 0 |
| type agreement | the dimension or type signatures match |
| boundary behavior | substitution at the degenerate locus gives the defined value |
| generality (symbolic check stalls) | randomized substitution over many trials; evidence is `measured`, not proof |
| dependence on premises | evaluate under named configurations (card EX) and read the boundary |

Long symbolic runs are split into steps, with intermediate results saved to
files.
