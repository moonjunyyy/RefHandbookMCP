# PAGE REF-RELATIONS — Choosing a relation
KIND: reference
TAGS: research, reference
TRIGGERS: relation type; which relation; typed dep edge; basis or link; sup is not proof; ref; iso map; int map; spec special case; result transfers to general; surface similarity; mathematical resemblance; physical interpretation
OBJECTIVE: How to choose the exact typed relation for a dep edge, and what each relation does and does not license.

Consulted when choosing the relation a `dep` edge records; return to the step
that sent you.

**Relations** (typed `dep` edges; syntax in REF-DEP). Record the exact relation. Never
infer one relation from surface similarity.

- A relation is a basis (the row rests on its target) or a link (it relates to
  it): the table is in REF-DEP. Choose by what the row does with the target,
  not by what makes a gate pass.
- `sup` (supports) is evidence, not proof. A claim becomes `true` only through
  basis edges (`req`, `der`, …) under explicit assumptions.
- `ref` points to a row the claim is about, or compares with, without resting
  on it.
- `iso` and `int` need the explicit map, written in the evidence cell.
- `spec` marks a special case. A result on a `spec` row does not transfer to the
  general row.
- Mathematical resemblance never creates an `int` edge to a physical or
  empirical identity.
