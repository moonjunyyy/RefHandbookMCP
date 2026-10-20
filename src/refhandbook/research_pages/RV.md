# PAGE RV — Review the rules
KIND: checklist
TAGS: research, normal
TRIGGERS: REVIEW; review the rules; rule gap; the rules got in the way; propose a rule; device change; loophole
OBJECTIVE: Judge the device's rules against what happened since the last review, and propose the smallest rule change that removes a class of failure.

ENTRY — obligation: `REVIEW` in research_begin (7 sessions since the last review, or 3 signals: refusals, UNAFFECTED disposals, carries, drops).
ENTRY — object: a K routed `@RV`, from X2 or X3 when a diagnosis exposes a missing, ambiguous, conflicting or stale rule.
◆ The rule, not the instance. Propose; never patch around it.

1. Read what happened since the last review: `research_show(recent=…)` over
   those sessions and the log lines `refused:`, `UNAFFECTED`, `carry`, `dropped`.
   `research_review(action="proposals")` lists proposals still open.
2. For each signal, name the **generating rule**: the rule (or its absence)
   that produced the refusal, the drop or the carry. Group signals that one rule
   explains. A signal the rules handled as intended is not a gap: say so.
3. For a real gap, write the **smallest** change that removes the class of
   failure:
   - a kernel rule (check, obligation, close) in the rule language
     (`research_review rules=[{id, phase, body, message, severity, replaces}]`);
     prefer revising one rule (`replaces`) over adding a second that overlaps it;
   - or a card wording change, recorded as a `P` row (`proposal: <card> …`).

   State the expected benefit and the plausible overconstraint (which correct
   work it would also stop). A one-off slip does not become a rule.
4. Read the trial: a proposal runs at once on every ledger as a **warning**.
   Its findings on this ledger are printed. A finding on correct work is
   overconstraint: revise the proposal (same id) before asking for adoption.
5. Record the review with `research_review(why=…)`, even when no gap was
   found: `why` holds the finding, or "no gap: <signals read>". This resets
   the REVIEW obligation.
6. Only the user adopts a proposal: the approval page (`/agents` on the server's
   site), or on the server
   `refhandbook proposals`, then `refhandbook approve rule <id> --seen <sha>`
   (or `reject`). An approval names the version shown, and a rejected id cannot
   be proposed again. Never phrase a proposal as already in force.
7. A proposal must be cheap: it runs on every ledger at every call. One that
   takes over its budget (1 s) is refused, or retired when it meets a large
   ledger later.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

A REVIEW from research_begin needs no K: N1 runs these steps at SETTLE and takes no exit, except
that exit b's object is still pushed when a proposal was made.

- **a**: reviewed, no gap → push `resume` @<caller>
- **b**: rule or card changes proposed → push `await adoption of <rule ids / P#>` @USER
