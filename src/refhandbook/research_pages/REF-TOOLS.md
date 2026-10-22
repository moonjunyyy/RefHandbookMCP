# PAGE REF-TOOLS — The research tools
KIND: reference
TAGS: research, reference
TRIGGERS: research tools; which research tool; research_* tool; research_ledgers; research_ledger_delete; research_begin; research_show; research_add; research_set; research_dispose; research_carry; research_push; research_next; research_done; research_drop; research_explore; research_doc; research_blob; research_review; research_check; research_end; write names its session; REFUSED; CONFLICT
OBJECTIVE: Each research_* tool and what it does, and what every write must name.

Consulted when you need a research_* tool and what it takes; return to the step
that sent you.

**Tools.**

| tool | purpose |
|---|---|
| `research_ledgers` | list · init · status · export (`include_log`) · import (`to`, `dry_run`, `ref`) · copy · rename |
| `research_ledger_delete` | delete a ledger permanently (`confirm` repeats its id) |
| `research_begin` | open a session (`role` chat · agent): SESSION token, ledger view (`recent` · `brief` · `full`), OBLIGATIONS |
| `research_show` | read the ledger (`open_only`, `ids`, `recent`) |
| `research_add` | add a row |
| `research_set` | replace one cell, or the map `M` |
| `research_dispose` | VALID · RECHECK · INVALID · UNAFFECTED for a PENDING hit |
| `research_carry` | keep a `U` open past this session, with a reason |
| `research_push` | push a plan object |
| `research_next` | take the next plan object and print its card |
| `research_done` | finish a plan object through an exit |
| `research_drop` | drop a plan object, with a reason |
| `research_explore` | config · verdict · matrix |
| `research_doc` | register · plan · sync · check (`text`, or `ref` for a staged blob) |
| `research_blob` | put · append · info: send a long text once (in pieces if needed), then pass its `ref` |
| `research_review` | record a review of the rules (`why`); rule changes are rule records, `cap(kind="rule")`, tried as warnings until the user adopts them (card RV) |
| `research_check` | consistency check, or the `closure` of ids |
| `research_end` | close the session: RECEIPT, changed rows, Δ |

Every write names its session. A REFUSED or CONFLICT names what to resolve (card X7).
