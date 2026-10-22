# PAGE IM-BUILD — Build the artifact
KIND: checklist
TAGS: research, stage
TRIGGERS: build; write the code; smallest artifact; requirements; user's symbols as names; seeds; configuration; versions; unexplained constant; deliver files; debug
OBJECTIVE: Build the smallest artifact that satisfies every active U, reproducible (seeds, configuration, versions) and named in the user's symbols.

ENTRY — object: a K `@IM-BUILD` (from IM-SPECIFY, or from IM-TEST to debug), `on` the specified components.

1. Build the smallest artifact that fully satisfies every active `U`.
   Minimality never removes a stated requirement.
2. Use the user's symbols as names.
3. Fix seeds, record configuration and versions, and leave no unexplained
   constant.
4. When the artifact is to be kept, deliver it as files.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: artifact built (or the component debugged) → push `test <artifact>` @IM-TEST
