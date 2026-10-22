# PAGE REF-EXEC — What runs: noexec and exec_work
KIND: reference
TAGS: research, reference, device
TRIGGERS: exec_work; noexec; what runs; permission denied running a binary; compiled binary; build in /work; native extension; virtual environment in /work; cannot execute
OBJECTIVE: Which written files may execute in a sandbox, and what exec_work allows.

Consulted when something built or installed in the sandbox will not execute;
return to the step that sent you.

**What runs.** Everything written is noexec, `/work` included, unless the policy
has `exec_work`: then what is built there (a compiled binary, a native extension
installed into a virtual environment in `/work`) runs too.
