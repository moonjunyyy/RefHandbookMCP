# PAGE REF-EGRESS — Egress: the sandbox's network
KIND: reference
TAGS: research, reference, device
TRIGGERS: egress; network; no network; proxy; HTTPS proxy; 403 egress; egress refused; egress profile; pip install; uv; npm install; cargo; git clone; curl; download in sandbox; pypi; npm; crates; github; huggingface; arxiv; propose an egress profile; TLS tunnel
OBJECTIVE: How a sandbox reaches the network through egress profiles, what a refusal means, and how to get a profile granted.

Consulted when a computation needs the network (packages, downloads, a
repository) or a job reports an egress refusal; return to the step that sent you.

**Egress.** A sandbox has no network of its own. A policy's `egress` profiles
(`cap(kind="egress")`: `pypi`, `npm`, `crates`, `github`, `huggingface`,
`arxiv`, …) open one way out: an HTTPS proxy the job's environment already names,
so `pip`, `uv`, `npm`, `cargo`, `git` and `curl` work unchanged, but only to the
profiles' hosts. A refusal reads `egress refused: <host> is in none of this
policy's egress profiles`: use a policy that has the profile, or propose one
(`cap(kind="egress", action="add", …)`, or `update` a policy of yours with the
profile); a proposal that widens a grant waits for the user's approval. A
tunnel must speak TLS to the very host it asked for. Never try to reach around
the proxy.
