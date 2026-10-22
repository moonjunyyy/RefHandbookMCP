# PAGE VF — Verify: execution-backed verdicts
KIND: checklist
TAGS: research, stage
TRIGGERS: check; verify; verdict; is this right; counterexample; sympy; executed check; closure of the claim set
OBJECTIVE: Decide claims by executed checks against a pass criterion declared beforehand, and record each verdict under its configuration until the claim set is closed.

ENTRY — object: a K `@VF` (from N3 dispatch or another page's exit), `on` the objects to work.

◆ Anything a tool can decide is decided by the tool.

1. Choose the engine: a computer algebra system, numerics, a proof assistant,
   or a search. The default here is Python with sympy.
2. Hand reasoning only interprets results. A conclusion resting on hand
   reasoning alone is `[unverified]`.
3. Take the granularity from card VF-CHAIN: dependent steps one per message,
   independent claims in one batch.
4. Declare the pass criterion before running (X7).
5. Run the executed check that fits the claim's shape (card REF-CHECKS).
6. Call `research_explore(action="verdict", claim, config, verdict,
   evidence)`. Use `config="main"` for the main line, or the configuration you
   checked under. The verdicts are:
   - `true`, with the check reference;
   - `false`, with `cex:` in the evidence;
   - `undecided`, with `tried:` in the evidence (only after an attempt).

   The claim's status follows its main verdict.
7. A verdict that changed, or a counterexample, triggers **X6**.
8. Closure: the claim set is verified when every main-line `H` is true or
   false, and every true row is `computed` or explicitly `[unverified]`.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: verdict recorded, chain continues → push `await confirmation of step` @USER (derivation chain) or `verify next H#` @VF (independent claims)
- **b**: a verdict changed, or a counterexample was found → push `propagate H#` @X6
- **c**: undecided after an attempt → push `reformulate H#` @FM-DEFINE, or `relabel R#` @DV-LABEL, or `find the premises it needs` @EX
- **d**: the check tool failed or you want to re-tune it → push `check integrity` @X7
