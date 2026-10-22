# PAGE REF-PORTING — Porting a ledger
KIND: reference
TAGS: research, reference
TRIGGERS: port a ledger; import a ledger; ledger kept by hand; errors on import; import dry_run; proposed row on a stale basis; check proposed rows; [unverified] propagation; unverified note in a cell; one K waits for the user; USER re-arms
OBJECTIVE: The checks that surprise a ledger brought in from elsewhere: basis of proposed rows, where [unverified] counts, and the single K waiting for the user.

Consulted when importing or porting a ledger kept elsewhere (by hand, or in
another tool), or when its rows fail checks they never met before; return to the
step that sent you.

**Checks to know when porting a ledger.**
- `check` judges the basis of `proposed` rows as well as settled ones: a
  proposed row resting on a superseded, refuted or stale row is an error. A
  ledger kept by hand often never checked that, so expect errors on import
  (`research_ledgers(action="import", dry_run=true)` lists them first).
- `[unverified]` propagates only from the evidence's first token. A note
  elsewhere in a cell ("the quoted lemma is [unverified]") does not mark the
  row unverified; write `[unverified] …` at the start when it is.
- One K waits for the user at a time: pushing page USER re-arms it.
