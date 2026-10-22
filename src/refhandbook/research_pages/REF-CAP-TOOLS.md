# PAGE REF-CAP-TOOLS — The computation tools
KIND: reference
TAGS: research, reference, device
TRIGGERS: computation tools; capability; cap; cap kinds; run; run a script; background job; job; job status; job output; wait for a job; cancel a job; files; workspace; /work; read a file in the sandbox; write a file in the sandbox
OBJECTIVE: The four tools computation uses (cap, run, job, files) and what each does.

Consulted when computation is needed and you need the tool for it: a capability
record, a run, a job, or the workspace; return to the step that sent you.

**Tools.**

| tool | purpose |
|---|---|
| `cap` | every capability record, one tool: `kinds` · `list` · `show` · `add` · `update` · `deprecate` · `remove` · `restore` · `history` · `review` |
| `run` | run a script (or an alias of one) as a background job; waits up to `wait` seconds |
| `job` | `list` · `status` · `wait` · `output` · `cancel` |
| `files` | the workspace, `/work` inside the sandbox: `ls` · `read` · `write` · `remove` |
