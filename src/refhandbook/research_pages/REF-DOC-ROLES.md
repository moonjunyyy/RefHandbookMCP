# PAGE REF-DOC-ROLES — Document roles: source, deliverable, working
KIND: reference
TAGS: research, reference
TRIGGERS: document role; source document; deliverable; working file; read-only original; hash-checked; working copy; register a document
OBJECTIVE: The three roles a registered document takes, and the rule each role carries.

Consulted from a card step; return to that step. Not a procedure: it consumes no K.

| role | what it is | rule |
|---|---|---|
| source | the user's original: a file the user provided | read-only, hash-checked: registered with its text; `check` detects any change; edits go to a working copy |
| deliverable | written for the user to read | readable prose (card REF-READER); section markers and a reader lint; plan → rewrite → sync |
| working | the model's own files (exports, scripts, scratch derivations) | never handed over as the deliverable; no reader rules |
