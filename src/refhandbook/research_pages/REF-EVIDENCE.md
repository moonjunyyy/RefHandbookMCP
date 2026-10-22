# PAGE REF-EVIDENCE — Evidence tags
KIND: reference
TAGS: research, reference
TRIGGERS: evidence; evidence tag; evidence cell; computed; measured; sourced; locator; followed; unverified; [unverified]; restored; pointer; not found; what counts as evidence
OBJECTIVE: The evidence tags and what the work must actually have done to earn each.

Consulted when writing or judging a row's evidence cell; return to the step that
sent you.

**Evidence** (what the work actually earned):

| evidence | earned by |
|---|---|
| `computed` | executed symbolic or exact check, result visible |
| `measured` | executed run with recorded configuration; corroborates, does not prove |
| `sourced: <locator>` | original opened and read this session; the locator is `chat:<uuid>`, `file:<path>`, or a URL |
| `followed` | each step reproduced |
| `[unverified]` | recall, plausibility, summaries, anything else |
| `restored` | copied verbatim from an earlier printed ledger |
| `pointer: <where>` | a memory line or summary that says where to look; not evidence |
| `not found: <calls>` | failed search or reading |
