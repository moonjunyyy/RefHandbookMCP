# PAGE QM-MAINTAIN — Question map: maintenance rules
KIND: reference
TAGS: research, reference
TRIGGERS: keep the map current; missing node mid-move; node rests on a changed row; map out of date; re-root; re-rooting; replace the question
OBJECTIVE: The rules that keep the question map current while other moves run: a missing node, a changed row under a node, and re-rooting.

Consulted from a card step (QM, or any move that touches the map); return to that step. Not a procedure: it consumes no K.

- A move that reaches a missing node pauses, runs QM-ACQUIRE on it, and returns.
- When a row a node rests on changes, the node is covered by **X6**.
- Re-rooting: after the user confirms, replace Q, record the old Q as a `P` row,
  and carry over the nodes that still apply.
