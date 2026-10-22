# PAGE IM — Implement: whether and when
KIND: checklist
TAGS: research, stage
TRIGGERS: implement; simulate; measure; numerics; experiment; code; run it; should we implement; symbolic instead
OBJECTIVE: Decide whether to realize a formal object as a traceable artifact: implement when the user asks, or when a claim is empirical and the user agrees.

ENTRY — object: a K `@IM` (from N3 dispatch or another page's exit), `on` the objects to work.

This stage realizes objects in order to measure them. Verify, by contrast,
decides claims.

◆ If the user asked to implement, implement.

1. Implement when the user asks, or when a claim is empirical and the user
   agrees.
2. A symbolic alternative may be offered once, after the implementation, and
   never instead of it.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: implementation goes ahead (asked, or agreed for an empirical claim) → push `specify <objects>` @IM-SPECIFY
- **b**: a claim is empirical and the user has not yet agreed to implement → push `await agreement to implement` @USER
