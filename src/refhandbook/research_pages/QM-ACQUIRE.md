# PAGE QM-ACQUIRE — Acquire a map node from originals
KIND: checklist
TAGS: research, stage
TRIGGERS: acquire a node; resolve a node; missing node; missing knowledge; map-build; search for the node; sourced; not found; locator; mechanically decidable
OBJECTIVE: Resolve one map node on demand from opened originals or a mechanical check, recording each find's relation to the node, or record it as not found.

ENTRY — object: a K `@QM-ACQUIRE` (from QM, DV, or any move that reaches a missing node), `on` the node to acquire.

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

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: node resolved (`sourced` / `computed`) → push `resume <caller move> on <objects>` @<caller>
- **b**: node is `not found` or gap → push `record gap, resume <caller move>` @<caller>
