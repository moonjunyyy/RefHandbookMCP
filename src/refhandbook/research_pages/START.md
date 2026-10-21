# PAGE START — Using the research cards
KIND: reference
TAGS: research, reference
TRIGGERS: how to use the research cards; start here; card parts; transcript; abnormal precedence; ledger sessions; deprecated; skill out of date
OBJECTIVE: How the cards, the ledger and the tools fit together: read this first, then card N1.

The research skill only points here. The cards on the server are the procedure,
and they are current; the skill file a client holds may be older. When the skill
and a card disagree, the card wins.

**Cards.** Every procedure is a card with id `rs-*`. `research_next` prints the
card of the plan object it starts; `open_entry("rs-n1")` opens any card;
`lookup("<symptom>", scope="research")` finds one by its cues. Every card has
the same parts:
- ENTRY: the start condition, meaning the K it consumes and the rows it acts on;
- numbered steps;
- EXITS: each exit returns objects, the K objects it pushes;
- a closing item: done → continue → close → next message.

**Work is object → objects.** Each message runs one session: `research_begin`
→ for each K: `research_next` → run the card → push the exit's objects →
`research_done` → `research_end` (card N1). The ledger keeps the record of that
processing (the K rows, and the Δ that `research_end` prints). The reply is
prose for the user (N1 step 8). The ▶/◀ transcript of a K is given only when
the user asks how a step was processed:

```
▶ K7 @FM on E2 H1   (from K5/b)
   … each action, followed by ⟵ basis: …
◀ FM/b → K8 @VF on H3 · K9 @EX on H3
```

**Abnormal before normal.** An X card takes precedence over a normal one; when
several match, run the lowest number first. `◆` marks a memory item: do it at
once, then run the card.

**Sessions.** The ledger persists on the server. Several sessions work on one
ledger side by side (another conversation, an agent with `role="agent"`): each
holds its own SESSION token, runs its own K and answers for what it opened. A
write that meets another session's change to the same object is refused with
CONFLICT: read the object again (`research_show(ids=…, session=…)`) and redo the
change.

**Tools.** The research tools are listed in REF-LEDGER; computation (scripts,
runs, files, policies, layers, egress) in REF-SANDBOX. A tool result that
begins `DEPRECATED` names its replacement: make every later call with the
replacement, starting now; never call the old name again in the conversation.

**Ledgers are managed, not recreated.** `research_ledgers` copies (a sandbox to
try something on) and renames; `research_ledger_delete` deletes, only with
`confirm` set to the ledger id and only when the user asked.

**The rules are reviewed, not worked around.** Every 7 sessions, or sooner when
refusals, UNAFFECTED disposals, carries and drops gather, `research_begin` lists
REVIEW (card RV). A rule change is proposed as a rule record,
`cap(kind="rule")`; it runs as a warning until the user approves it. Never treat
a proposal as in force.

The handbook does not replace judgment. If no card fits, say so in one line and
push to `USER`. Never bend a situation to fit a card.
