# PAGE VF — Verify: execution-backed verdicts
KIND: checklist
TAGS: research, stage
TRIGGERS: check; verify; verdict; derivation step; counterexample; sympy
OBJECTIVE: Decide claims by executed checks and record each verdict under its configuration.

ENTRY — object: a K `@VF` (from N3 dispatch or another page's exit), `on` the objects to work.

### VF1 — Execute, do not assert

◆ Anything a tool can decide is decided by the tool.

1. Choose the engine: a computer algebra system, numerics, a proof assistant,
   or a search. The default here is Python with sympy.
2. Hand reasoning only interprets results. A conclusion resting on hand
   reasoning alone is `[unverified]`.

### VF2 — Granularity

- **Derivation chain** (dependent steps):
  1. Take one step per message.
  2. Give each line a basis tag, naming the term or operation it comes from.
  3. Show the step's own check (signs, indices, units, substitution) before its
     result.
  4. Wait for the user's confirmation before the next step.
- **Independent claims**: may be checked in one batch, each with its own
  executed check and its own verdict.

### VF3 — Check patterns

Declare the pass criterion before running (X7).

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

### VF4 — Record

1. Call `research_explore(action="verdict", claim, config, verdict,
   evidence)`. Use `config="main"` for the main line, or the configuration you
   checked under. The verdicts are:
   - `true`, with the check reference;
   - `false`, with `cex:` in the evidence;
   - `undecided`, with `tried:` in the evidence (only after an attempt).

   The claim's status follows its main verdict.
2. A verdict that changed, or a counterexample, triggers **X6**.
3. Closure: the claim set is verified when every main-line `H` is true or
   false, and every true row is `computed` or explicitly `[unverified]`.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: verdict recorded, chain continues → push `await confirmation of step` @USER (derivation chain) or `verify next H#` @VF (independent claims)
- **b**: a verdict changed, or a counterexample was found → push `propagate H#` @X6
- **c**: undecided after an attempt → push `reformulate H#` @FM, or `relabel R#` @DV, or `find the premises it needs` @EX
- **d**: the check tool failed or you want to re-tune it → push `check integrity` @X7
