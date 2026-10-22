# PAGE REF-LAYERS — Layers
KIND: reference
TAGS: research, reference, device
TRIGGERS: layer; sys: layer; server layers; build a layer; own layer; layer build script; install software in the sandbox; software stack; pinned build; name@N; move the pin; layer parents
OBJECTIVE: What a layer is, the server's own versus yours, how yours is built, and how a policy pins one.

Consulted when the software a computation needs is not in any layer a policy
stacks; return to the step that sent you.

**Layers** stack software on the sandbox's base. The server's own are named
`sys:<name>` (built by its administrator). Your own layer is a build script run
as root inside a sandbox of a policy you hold (`cap(kind="layer", body=…,
spec={policy, parents, env})`); a policy stacks a layer at a pinned build
(`name@N`), and moving the pin is a new policy version.
