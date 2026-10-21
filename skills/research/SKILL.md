---
name: research
description: >
  Operating procedure for theoretical research (mathematics, physics,
  theoretical ML) as a research colleague, not a tutor, run as a ledgered
  session loop (one session per message) over the research cards of the refhandbook MCP server. Use when the user
  floats an idea or conjecture, wants a notion made precise, asks to derive or
  construct a general structure or operator, asks to check a derivation or
  claim, asks "what if" about an assumption, wants a formal object implemented,
  measured, or simulated, resumes earlier work ("last time", "this paper",
  "where were we"), challenges an earlier step, or is stuck circling a point,
  even when phrased casually or in another language. Once a ledger RECEIPT or
  SESSION line appears in the conversation, use this skill on every later
  message of it, including one-word, meta, process, and complaint messages:
  nothing else continues the cycle. Not for textbook explanations, known-answer exercises,
  or coding unrelated to a research claim. Respond in the user's language.
---

# research — Quick Reference Handbook

This skill only says where the procedure is. The procedure is the research
cards on the refhandbook server: they are current, and this file may be older.
When this file and a card disagree, the card wins.

> **Program counter.** Two places carry the cycle from one message to the
> next, and nothing else does:
> - the RECEIPT line that ends your previous reply;
> - the plan objects (K) awaiting the user in the ledger.
>
> If either exists, your first action now is `research_begin` (card rs-n1),
> whatever the user's message says.

## How to start

1. `open_entry("rs-start")` once per conversation: how the cards, the ledger
   and the tools fit together.
2. Every message: card `rs-n1` (`research_begin` prints the line to follow).
3. Find any other card with `lookup("<symptom>", scope="research")`, or by the
   index below.

A tool result that begins `DEPRECATED` names its replacement: switch now, and
never call the old name again (card `rs-ref-sandbox` lists the old names).

## No research tools in this session?

The refhandbook connector is not connected, and the ledgers (and cards) on the
server cannot be seen from here.
1. Say so in one line, and ask the user to connect it from the plugin's
   Connectors tab (a sign-in page opens). Never answer from a remembered
   ledger.
2. Only if it cannot be connected now, keep a temporary ledger through the
   plugin's CLI, which runs the same code:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/research.py" --db /mnt/user-data/outputs/research.db research <tool> '<JSON arguments>'
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/research.py" --db /mnt/user-data/outputs/research.db show rs-n1
   ```

   Before the session ends, run `research_ledgers` with `action="export"`
   (and `include_log=false` for a long ledger), and give the user the JSON
   file. A JSON too large for one tool argument travels in pieces:
   `research_blob` put, then append, and `research_ledgers` import with
   `ref=<the last ref>`. Try it first with `dry_run=true`, or under another
   name with `to`.

## Index

**Normal**

| situation | card |
|---|---|
| every message, without exception | `rs-n1` |
| first message on a question, or resuming earlier work, files, or sessions | `rs-n2` |
| choosing the next piece of work | `rs-n3` |
| something this conversation and the ledger cannot resolve, or outside knowledge is needed | `rs-rf` |
| a verdict may hinge on a premise, or "what if" / "without X" / "which assumptions are needed" | `rs-ex` |
| a document is written or changed, or the user provides one | `rs-n4` |
| the question's objects belong to a field with its own checks | `rs-dom-*` (chosen in `rs-n2`) |
| verdicts exist, but the program's standing is unclear | `rs-n3b` |
| computation: a script, a run, packages, the network, the sandbox's tools | `rs-ref-sandbox` |
| origins, evidence, what may be used as what | `rs-ref-prov` |
| begin lists REVIEW, or a diagnosis exposes a missing, ambiguous, conflicting or stale rule | `rs-rv` |

**Abnormal**: memory item first, then the card.

<!-- BEGIN GENERATED: refhandbook research-index -->
| signal | ◆ memory item | card |
|---|---|---|
| the draft answers something other than an active `U`. | **X1** — Discard the substitution. Execute the directive as stated. | `rs-x1` |
| "why", "look", "explain", or a question about an error or a step. | **X2** — Answer only that. No new derivation, code, or search. | `rs-x2` |
| the same correction a second time, or the previous skeleton reused. | **X3** — Stop producing. Name the generating rule, then run a check. | `rs-x3` |
| the user asserts that a step is correct or urgent, and you have not reproduced it. | **X4** — Do not agree on the basis of assertion. | `rs-x4` |
| an action has no basis tag, cites an item against its use rule (card REF-PROV), or rests on a model-origin item. | **X5** — Remove the dependent work. | `rs-x5` |
| one of the following: a row was changed, rejected, weakened, strengthened, or reclassified; a verdict flipped; the user corrected something. | **X6** — A correction is a state change, not a remark. **Change exactly what was corrected, nothing more.** Propagate to closure. Never revive a rejected branch. | `rs-x6` |
| a check fails, the device REFUSES, reports a CONFLICT or an outside edit, or you want to narrow, filter, or re-tune a check. | **X7** — Report the output exactly as produced. Resolve what it names; never work around it. | `rs-x7` |
| the meaning of a symbol, an agreement, or a source is uncertain, or you are about to say "not available", "never said", or "impossible". | **X8** — No absence claim without a failed tool call behind it. | `rs-x8` |
| you are about to ask the user for a concrete function or values. | **X9** — Build the general form with symbols first. | `rs-x9` |
<!-- END GENERATED -->
