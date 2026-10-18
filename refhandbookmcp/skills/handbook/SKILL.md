---
name: handbook
description: Use the quick reference handbook when something goes wrong (a failing command, an error message, a stuck git operation), before starting a recurring procedure, or when the user says "check the handbook", "is there a checklist for this", or "add this to the handbook". Covers looking up, following, and writing entries.
---

# Quick reference handbook

The handbook holds short cards for situations that have come up before. Each card names the
situation it is for, says how to confirm you are in it, and lists what to do. Cards are linked
to each other by typed relations, so one card leads to the next.

## Using a card

1. **Look up by symptom, not by guess.** Call `lookup` with what you observed: the error text,
   the alert, a few plain words. Do not search for the fix you already have in mind.
2. **Confirm before you act.** Read each candidate's condition. If it does not describe the
   present state, it is the wrong card, however similar the title. Acting on the wrong card is
   the most damaging mistake a handbook allows.
3. **Open it and follow it in order.** Memory items first. Then the numbered steps, one at a
   time, checking each step's expected response before moving on. A caution or note applies to
   the step after it.
4. **Take branches literally.** A step that starts with IF applies only when its condition
   holds. `>> GO TO` means continue in that entry: open it. `## END` means stop there.
5. **Hold the deferred items.** They are not done now. Tell the user about them and do them
   when their condition arrives.
6. **If it did not work**, look under RELATED for `escalates_to`, or `traverse` from the card.

If you are interrupted partway through a card, reopen it and resume from the last step whose
response you confirmed. Do not restart from memory.

## Writing a card

Write one after resolving a situation that no card covered and that is likely to recur. Ask the
user before recording anything specific to their systems.

- **Title**: the situation as it would be named by someone in it. "Rebase stops on a conflict",
  not "Git tips".
- **Condition**: the observable state that confirms the card applies.
- **Objective**: what following it achieves.
- **Triggers**: the literal strings and symptoms someone would search with.
- **Memory items**: only what must happen immediately to prevent further harm. Four at most.
  Most cards have none.
- **Steps**: one action each, with the expected `response` where there is one. Put a `caution`
  before the step it concerns. Use `when` for a conditional step, and `goto` in place of copying
  another card's steps.
- **Deferred items**: actions that belong to a later moment, each with a `when`.

Then link it: `relate` it to the cards it escalates to, requires, or supersedes. If none of the
existing relation types says what you mean, add one with `define_relation_type`. Run `audit`
after writing and fix what it reports.

Replace a card that has gone stale by writing the new one and relating it with `supersedes`.
Delete only cards that were wrong from the start.
