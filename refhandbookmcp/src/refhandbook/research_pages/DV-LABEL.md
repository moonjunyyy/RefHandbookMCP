# PAGE DV-LABEL — Label: minimal reading of a term
KIND: checklist
TAGS: research, stage
TRIGGERS: readings; label; relabel; reading of a term; what does this term mean; interpretation; alternative reading; minimal reading
OBJECTIVE: Give a term's minimal reading and, only where they change a verdict, alternative readings registered as proposed R rows, each with the check that distinguishes it.

ENTRY — object: a K `@DV-LABEL` (from DV, N3 dispatch, or another page's exit), `on` the term or the `R` row to read.
ENTRY — signal: only when the user asks for readings, or when a term's reading
changes a mandatory verdict.

◆ Minimal reading first.

1. Give the minimal reading of the term: the same content in symbols, with no
   structure added. Its origin is `user`.
2. Give alternatives only if they change a verdict, one line each, each with
   the **observation or check that would distinguish it** from the minimal
   reading. Each is registered as `R`, with origin `model`, status `proposed`,
   and evidence `closure: <the user's words it was checked against>`.
3. Nothing proceeds on an alternative until the user adopts it (card REF-ORIGIN).

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: alternative readings offered (R `proposed`) → push `await adoption of R#` @USER
- **b**: minimal reading only, no alternative changes a verdict → push `resume <caller move> on <R#>` @<caller>
