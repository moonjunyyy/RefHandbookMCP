# PAGE QM — Question map: build
KIND: checklist
TAGS: research, stage
TRIGGERS: question map; sub-question; decompose the question; missing knowledge; node; gap; what do we need to know
OBJECTIVE: Build the question map: decompose the question into typed knowledge nodes, write the whole tree into M, and stop when it suffices for the current move.

ENTRY — object: a K `@QM` (from N3 dispatch or another page's exit), `on` the objects to work.

The map is section `M` of the ledger. It is changed only with
`research_set(id="M")`, which replaces the whole map, and shown only through N1.
Missing nodes met mid-move, changed rows, and re-rooting follow card
QM-MAINTAIN.

```
Q  <research question, in the user's words>
├─ Q1 <sub-question>
│   ├─ K1 [definition | result | method | data | prior work]  <node>  <evidence>  → <source or calls>
│   └─ K2 ...
└─ Q2 ...
```

Node evidence uses the card REF-EVIDENCE evidence table. **gap** means the
knowledge does not appear to exist after search, which makes it a candidate
contribution. It is not a search failure.

1. Decompose Q until each sub-question names the knowledge it needs. Stop at the
   grain the current move needs.
2. Type each node: definition, result, method, data, or prior work (including
   the user's own sessions and files).
3. Write the whole tree into M with `research_set(id="M", field="content")`.
   Replace the map; never append a line to it.
4. Check sufficiency. The map suffices for the current move when every node
   that move depends on is `sourced`, `not found`, or gap. Other nodes stay
   coarse.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: a node the current move depends on is not yet `sourced`, `not found`, or gap → push one `acquire <node>` @QM-ACQUIRE per node (queued)
- **b**: the map suffices for the current move → push `resume <caller move> on <objects>` @<caller>
- **c**: the question needs re-rooting → push `confirm re-root` @USER
