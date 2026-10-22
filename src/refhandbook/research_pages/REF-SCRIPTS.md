# PAGE REF-SCRIPTS — Scripts
KIND: reference
TAGS: research, reference, device
TRIGGERS: write a script; add a script; cap script; script spec; interpreter; script policy; requires; script test; revise a script; script version; retire a script; restore a script; script approval
OBJECTIVE: How a script is added, revised, retired and restored, what its spec holds, and why it needs no approval.

Consulted when writing, revising or retiring a script for a computation; return
to the step that sent you.

**Scripts.** `cap(kind="script", action="add", name=…, body=…, spec={interpreter,
policy, requires, test})`. No approval is needed: a script can use only what its
policy shows. Revise with `update` (a new version; history is kept), retire with
`remove`, bring back with `restore`. `requires` names the commands it needs; it
is checked at every write and every review.
