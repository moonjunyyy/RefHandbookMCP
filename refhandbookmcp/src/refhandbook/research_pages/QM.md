# PAGE QM — Question map
KIND: checklist
TAGS: research, stage
TRIGGERS: question map; sub-question; missing knowledge; node; gap
OBJECTIVE: Keep the question map: decompose the question and acquire each needed node from originals.

ENTRY — object: a K `@QM` (from N3 dispatch or another page's exit), `on` the objects to work.

The map is section `M` of the ledger. It is changed only with
`research_set(id="M")`, which replaces the whole map, and shown only through N1.

```
Q  <research question, in the user's words>
├─ Q1 <sub-question>
│   ├─ K1 [definition | result | method | data | prior work]  <node>  <evidence>  → <source or calls>
│   └─ K2 ...
└─ Q2 ...
```

Node evidence uses the card REF-PROV evidence table. **gap** means the knowledge does not appear to
exist after search, which makes it a candidate contribution. It is not a search
failure.

### QM1 — Build

1. Decompose Q until each sub-question names the knowledge it needs. Stop at the
   grain the current move needs.
2. Type each node: definition, result, method, data, or prior work (including
   the user's own sessions and files).
3. Write the whole tree into M with `research_set(id="M", field="content")`.
   Replace the map; never append a line to it.

### QM2 — Acquire (per node, on demand)

◆ Queries come from the node's requirement, not from the topic.

1. State what must be true or available for this node to resolve.
2. Acquire the node by pushing `retrieve <node>` @RF. RF follows the source
   ladder: sessions, then files, then memory pointers, then the web. Record each
   find's **relation to the node**, not a summary of the find.
3. A node is `sourced` only with a locator (`chat:`, `file:`, or a URL) from an
   opened original. A snippet leaves it `[unverified]`; a memory line leaves it
   `pointer:`.
4. If the node, or an instance of it, is mechanically decidable, run the check.
   The instance then carries `computed` or `measured` over its stated range.
5. Anything that fails is recorded as `not found: <calls>`.

### QM3 — Sufficiency

The map suffices for the current move when every node that move depends on is
`sourced`, `not found`, or gap. Other nodes stay coarse.

### QM4 — Maintain

- A move that reaches a missing node pauses, runs QM2 on it, and returns.
- When a row a node rests on changes, the node is covered by **X6**.
- Re-rooting: after the user confirms, replace Q, record the old Q as a `P` row, and carry
  over the nodes that still apply.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: node resolved (`sourced` / `computed`) → push `resume <caller move> on <objects>` @<caller>
- **b**: node is `not found` or gap → push `record gap, resume <caller move>` @<caller>
- **c**: the question needs re-rooting → push `confirm re-root` @USER
