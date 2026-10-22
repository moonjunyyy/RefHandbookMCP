# PAGE REF-APPROX — Approximation versus information
KIND: reference
TAGS: research, reference
TRIGGERS: approximation; X row; discretization; finite samples; tolerance; prior; damping; regularization; fill in unobserved directions; default structure; adds information; external result; T row; verdict rests on T
OBJECTIVE: What an approximation row may and may not change, where added information goes instead, and how far a verdict resting on an external result holds.

Consulted when adding or judging an `X` row, or when a verdict rests on an
external result `T`; return to the step that sent you.

- **Approximation versus information.** An `X` row may change *how* the
  available information is computed: discretization, finite samples,
  tolerances. An `X` row may never *add* information: priors, damping or
  regularization, filled-in unobserved directions, default structure.
  Anything that adds information is an `A` row with origin `model`: it stays
  out of the main line and may be explored (X5, EX).
- **External results** (`T`) stay external. A verdict that rests on `T1` holds
  only in configurations that contain `T1`.
