# PAGE REF-OLD-NAMES — Old tool names
KIND: reference
TAGS: research, reference, device
TRIGGERS: deprecated tool; DEPRECATED; old tool name; old name; replacement tool; sandbox_script; sandbox_run; sandbox_job; sandbox_files; sandbox_policy; research_review rules
OBJECTIVE: The deprecated tool names that still answer, and the replacement to call for each.

Consulted when a tool result begins `DEPRECATED`, or before calling a tool by an
old name; return to the step that sent you.

**Old names.** These still answer, with a `DEPRECATED` line, until they are
removed. Do not call them; use the replacement.

| old name | use instead |
|---|---|
| `sandbox_script` | `cap(kind="script", action=…)`; `run` for a test |
| `sandbox_run` | `run` |
| `sandbox_job` | `job` |
| `sandbox_files` | `files` |
| `sandbox_policy` | `cap(kind="policy", action="list" or "show")` |
| `research_review` with `rules` | `cap(kind="rule", action="add" or "update")` |
