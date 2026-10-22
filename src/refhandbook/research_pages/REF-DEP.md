# PAGE REF-DEP — dep cells: basis and link relations
KIND: reference
TAGS: research, reference
TRIGGERS: dep syntax; dep cell; dep token; relation type; basis or link; basis edge; link edge; req; der; eq; iso; spec; int; sup; con; ref; basis check; propagation; PENDING; unknown relation; delete a relation to pass a gate; claim premises
OBJECTIVE: The syntax of a dep cell, which relations are a basis and which a link, what follows basis edges, and where a claim's premises come from.

Consulted when writing or reading a `dep` cell, or when a basis check or a
PENDING propagation follows one; return to the step that sent you.

**dep.** A `dep` cell holds tokens of the form `[rel:]ID`. Each `rel` is either a
**basis** (the row rests on the target) or a **link** (it relates to the target
without resting on it):

| class | rel | meaning |
|---|---|---|
| basis | `req` (the default) | requires |
| basis | `der` | derived from |
| basis | `eq` | equivalent to |
| basis | `iso` | isomorphic to; needs the map |
| basis | `spec` | a special case of |
| basis | `int` | interprets; needs the map |
| link | `sup` | supports: evidence, not proof |
| link | `con` | contradicts |
| link | `ref` | refers to, without resting on it |

Basis checks (a stale, replaced, model-origin or pointer-only target) and
propagation (PENDING) follow basis edges only. Record a relation honestly as a
link instead of deleting it to pass a gate. A relation the device does not know
counts as a basis.

A claim's premises come from its configuration, not from `dep`. A true verdict
that rests on an external result `T` needs that `T` in the configuration.
