# PAGE REF-CONFIG — Configurations
KIND: reference
TAGS: research, reference
TRIGGERS: configuration spec; configuration; main configuration; named configuration; define a configuration; research_explore config; add premise; remove premise; swap premise; grp alternatives; claim × configuration cell; stale cell
OBJECTIVE: What main and a named configuration are, the tokens a configuration spec is built from, and how verdicts live in claim × configuration cells.

Consulted when defining a configuration, writing its spec, or reading a verdict
in a claim × configuration cell; return to the step that sent you.

**Configurations.**
- `main` is always the set of `A` and `T` rows that are `on`. Only the user
  switches it.
- Named configurations are defined with `research_explore(action="config")`.
  Their spec is built from these tokens:
  - `main`;
  - `+A5`, which adds a premise;
  - `-A2`, which removes one;
  - `A3>A7`, which swaps one for another;
  - plain ids.
- Alternatives from one `grp` exclude each other.
- A verdict lives in a claim × configuration cell. A cell can go stale on its
  own, without affecting the claim's other cells.
