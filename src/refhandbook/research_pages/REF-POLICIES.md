# PAGE REF-POLICIES — Policies
KIND: reference
TAGS: research, reference, device
TRIGGERS: policy; sandbox policy; which policy; policies in force; default policy; dev policy; what dev holds; command not found in sandbox; scientific stack; uv; Node; Rust; no network
OBJECTIVE: What a policy is, how a script picks one, and what the default and dev policies hold.

Consulted when choosing the policy a script runs under, or when a command or
package is missing from a sandbox; return to the step that sent you.

**Policies** are what a sandbox is; pick one in the script's spec (`policy`).
`cap(kind="policy")` lists those in force.
- `default`: a coreutils-like set, a shell and Python; no network.
- `dev`: what the server's administrator set up for development: the server's
  layers (Python with uv, the scientific stack, Node, Rust) with every command,
  the egress profiles they granted, and `exec_work` if they granted it.
  `cap(kind="policy", action="show", name="dev")` says what it holds now.
