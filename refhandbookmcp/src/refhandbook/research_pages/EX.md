# PAGE EX — Explore conditions: assumptions on, off, swapped
KIND: checklist
TAGS: research, normal
TRIGGERS: what if; without this assumption; toggle assumption; which assumptions are needed; under which conditions; alternative premise; ablation; boundary; necessary and sufficient
OBJECTIVE: Map how verdicts depend on assumptions by evaluating claims under named configurations, and read the boundary.

ENTRY — object: a K @EX on claims (H#) and on the premises (A#, T#) to vary.
It is pushed by one of the following:
- N3;
- VF, for a verdict that may hinge on a premise;
- X5, for a model premise;
- the user's "what if".

◆ Explore freely; keep the main line clean. Every verdict names its
configuration.

1. **State the question.** Name the claims, the premises that vary, and what
   counts as an answer: a boundary, a minimal sufficient set, or a
   counterexample under one premise set.
2. **Register premises.** Add each premise not yet in the ledger as an `A`
   row, with origin `model`, status `proposed`, and evidence
   `closure: <the user's givens it was checked against>`. Alternatives to the
   same premise share a `grp`, for example smooth / Lipschitz / bounded
   variation.
3. **Define configurations** with
   `research_explore(action="config", name, spec, purpose)`. The spec starts
   from `main` and edits it:
   - `+A5` adds a premise;
   - `-A2` removes one;
   - `A3>A7` swaps one for another.

   A spec may also list the members outright. Make one change per
   configuration, so that the boundary can be read. A configuration that has
   verdicts is immutable; define a new name instead.
4. **Check each pair.** For each claim × configuration, check by execution
   (card VF). Then record the result with
   `research_explore(action="verdict", claim, config, verdict, evidence)`.
   `false` needs `cex:` in the evidence; `undecided` needs `tried:`.
5. **Read the boundary.** Call `research_explore(action="matrix")`. It returns
   the table and the boundary lines: which single change flips a verdict.
   When the boundary bears on a mandatory `C`, record it as a claim of its own,
   with its own verdicts (for example "H1 holds iff A2 or A5").
6. **Report.** Give main-line verdicts first. Then give exploration verdicts,
   each labelled with its configuration and with the model premises it uses.
   An exploration result never stands in for a main-line result.
7. **Adoption.** Propose a premise for the user to adopt once, together with
   the boundary that motivates it. Only the user switches the main line: the
   `A` row is set `on`, with origin `user(adopted, session N)`.

**EXITS**

- **a**: boundary read and reported → push `report the boundary; propose adoption if any` @USER
- **b**: a new claim emerged from the boundary → push `verify H#` @VF
- **c**: a configuration stays undecided after an attempt → push `reformulate H# under <config>` @FM-DEFINE
- **d**: the user adopts or rejects a premise → push `apply the main-line change` @X6
