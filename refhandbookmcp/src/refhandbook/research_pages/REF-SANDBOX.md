# PAGE REF-SANDBOX — Computation: scripts, runs, policies, layers, egress
KIND: reference
TAGS: research, reference, device
TRIGGERS: run a script; compute; simulate; sandbox; policy; layer; egress; pip install; npm install; cargo; network; no network; proxy; 403 egress; deprecated tool; sandbox_script; sandbox_run; sandbox_job; sandbox_files; sandbox_policy; exec_work; capability
OBJECTIVE: How computation runs in the user's sandbox, and the tools that run it.

Consulted from a card step (VF, IM, …) or whenever computation is needed; return
to that step. Not a procedure: it consumes no K.

**Tools.**

| tool | purpose |
|---|---|
| `cap` | every capability record, one tool: `kinds` · `list` · `show` · `add` · `update` · `deprecate` · `remove` · `restore` · `history` · `review` |
| `run` | run a script (or an alias of one) as a background job; waits up to `wait` seconds |
| `job` | `list` · `status` · `wait` · `output` · `cancel` |
| `files` | the workspace, `/work` inside the sandbox: `ls` · `read` · `write` · `remove` |

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

**Scripts.** `cap(kind="script", action="add", name=…, body=…, spec={interpreter,
policy, requires, test})`. No approval is needed: a script can use only what its
policy shows. Revise with `update` (a new version; history is kept), retire with
`remove`, bring back with `restore`. `requires` names the commands it needs; it
is checked at every write and every review.

**Policies** are what a sandbox is; pick one in the script's spec (`policy`).
`cap(kind="policy")` lists those in force.
- `default`: a coreutils-like set, a shell and Python; no network.
- `dev` (when the server has it): every command, the server's layers (Python
  with uv, the scientific stack, Node, Rust), the package registries through
  egress, and what is built in `/work` may run (`exec_work`).

**Egress.** A sandbox has no network of its own. A policy's `egress` profiles
(`cap(kind="egress")`: `pypi`, `npm`, `crates`, `github`, `huggingface`,
`arxiv`, …) open one way out: an HTTPS proxy the job's environment already names,
so `pip`, `uv`, `npm`, `cargo`, `git` and `curl` work unchanged, but only to the
profiles' hosts. A refusal reads `egress refused: <host> is in none of this
policy's egress profiles`: use a policy that has the profile, or propose one
(`cap(kind="egress", action="add", …)`, or `update` a policy of yours with the
profile); a proposal that widens a grant waits for the user's approval. Never
try to reach around the proxy.

**Layers** stack software on the sandbox's base. The server's own are named
`sys:<name>` (built by its administrator). Your own layer is a build script run
as root inside a sandbox of a policy you hold (`cap(kind="layer", body=…,
spec={policy, parents, env})`); a policy stacks a layer at a pinned build
(`name@N`), and moving the pin is a new policy version.

**What runs.** Everything written is noexec, `/work` included, unless the policy
has `exec_work`: then what is built there (a compiled binary, a native extension
installed into a virtual environment in `/work`) runs too.

**Keeping records current.** Every record has a TTL: when it passes, the record
is reviewed and either renewed or deprecated with the reason. When a review
deprecates one of yours, fix it (`update`) or retire it (`remove`). A
deprecated record still works and warns; it retires after its grace.
