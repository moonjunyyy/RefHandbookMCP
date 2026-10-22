# PAGE START-SESSIONS — Sessions side by side
KIND: reference
TAGS: research, reference
TRIGGERS: ledger sessions; several sessions; parallel sessions; another conversation; agent session; role="agent"; SESSION token; CONFLICT; write refused; re-read an object; ledger persists
OBJECTIVE: How several sessions share one persistent ledger, and what to do when a write meets another session's change.

Consulted when another session works on the same ledger, or a write is refused
with CONFLICT; return to the step that sent you.

**Sessions.** The ledger persists on the server. Several sessions work on one
ledger side by side (another conversation, an agent with `role="agent"`): each
holds its own SESSION token, runs its own K and answers for what it opened. A
write that meets another session's change to the same object is refused with
CONFLICT: read the object again (`research_show(ids=…, session=…)`) and redo the
change.
