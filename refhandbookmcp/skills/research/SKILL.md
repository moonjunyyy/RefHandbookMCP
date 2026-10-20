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

> **Program counter.** Two places carry the cycle from one message to the
> next, and nothing else does:
> - the RECEIPT line that ends your previous reply;
> - the plan objects (K) awaiting the user in the ledger.
>
> If either exists, your first action now is `research_begin` (card rs-n1),
> whatever the user's message says.

## 0. How to use this handbook

- **Procedures are cards** in the refhandbook MCP server, with ids `rs-*`.
  - `research_next` prints the card of the plan object it starts.
  - `open_entry("rs-n1")` opens any card.
  - `lookup("<symptom>", scope="research")` finds a card by its cues
    (without `scope`, `lookup` searches the ordinary handbook only).
- **Every card has the same parts:**
  - ENTRY: the start condition, meaning the K it consumes and the rows it
    acts on;
  - numbered steps;
  - EXITS: each exit returns objects, the K objects it pushes;
  - a closing item: done → continue → close → next message.
- **Work is object → objects.** Each message runs one session: `research_begin` → for each
  K: `research_next` → run the card → push the exit's objects →
  `research_done` → `research_end`.

  The ledger keeps the record of that processing (the K rows, and the Δ that
  `research_end` prints). The reply is prose for the user: what was checked,
  what changed, what it means, and what is asked of the user (card rs-n1
  step 8). The ▶/◀ transcript of a K —

  ```
  ▶ K7 @FM on E2 H1   (from K5/b)
     … each action, followed by ⟵ basis: …
  ◀ FM/b → K8 @VF on H3 · K9 @EX on H3
  ```

  — is given only when the user asks how a step was processed. The RECEIPT
  line closes every reply, last.
- **Abnormal (X) takes precedence** over normal. When several X rows match, run
  the lowest number first. `◆` marks a memory item: do it at once, then run
  the card.
- **The ledger persists** in the server's store across conversations.
  Several sessions work on one ledger side by side (another conversation, an
  agent with `role="agent"`): each holds its own SESSION token, runs its own K
  and answers for what it opened. A write that meets another session's change
  to the same object is refused with CONFLICT: read the object again
  (`research_show(ids=…, session=…)`) and redo the change.
- **Tools** are the `research_*` tools; card rs-ref-ledger lists them. Every
  call names its `session`. A REFUSED names what to resolve (card rs-x7).
- **No research tools in this session?** The refhandbook connector is not
  connected, and the ledgers on the server cannot be seen from here.
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
- **Ledgers are managed, not recreated.** `research_ledgers` copies (a sandbox
  to try something on) and renames; `research_ledger_delete` deletes, only
  with `confirm` set to the ledger id and only when the user asked.
- **The rules are reviewed, not worked around.** Every 7 sessions, or sooner when
  refusals, UNAFFECTED disposals, carries and drops gather, `research_begin`
  lists REVIEW (card rs-rv). A rule change is proposed as a rule record, `cap(kind="rule")`;
  it runs as a warning until the user approves it. Never treat a proposal as
  in force.
- The handbook does not replace judgment. If no card fits, say so in one line
  and push to `USER`. Never bend a situation to fit a card.

## 1. Index

**Normal**

| situation | card |
|---|---|
| every message, without exception | `rs-n1` (§2) |
| first message on a question, or resuming earlier work, files, or sessions | `rs-n2` |
| choosing the next piece of work | `rs-n3` |
| something this conversation and the ledger cannot resolve, or outside knowledge is needed | `rs-rf` |
| a verdict may hinge on a premise, or "what if" / "without X" / "which assumptions are needed" | `rs-ex` |
| a document is written or changed, or the user provides one | `rs-n4` |
| the question's objects belong to a field with its own checks | `rs-dom-*` (chosen in `rs-n2`) |
| verdicts exist, but the program's standing is unclear | `rs-n3b` |
| begin lists REVIEW, or a diagnosis exposes a missing, ambiguous, conflicting or stale rule | `rs-rv` |

**Abnormal**: memory item first, then the card.

<!-- BEGIN GENERATED: refhandbook research-index -->
| signal | ◆ memory item | card |
|---|---|---|
| the draft answers something other than an active `U`. | **X1** — Discard the substitution. Execute the directive as stated. | `rs-x1` |
| "why", "look", "explain", or a question about an error or a step. | **X2** — Answer only that. No new derivation, code, or search. | `rs-x2` |
| the same correction a second time, or the previous skeleton reused. | **X3** — Stop producing. Name the generating rule, then run a check. | `rs-x3` |
| the user asserts that a step is correct or urgent, and you have not reproduced it. | **X4** — Do not agree on the basis of assertion. | `rs-x4` |
| an action has no basis tag, cites an item against its use rule (SKILL.md §4), or rests on a model-origin item. | **X5** — Remove the dependent work. | `rs-x5` |
| one of the following: a row was changed, rejected, weakened, strengthened, or reclassified; a verdict flipped; the user corrected something. | **X6** — A correction is a state change, not a remark. **Change exactly what was corrected, nothing more.** Propagate to closure. Never revive a rejected branch. | `rs-x6` |
| a check fails, the device REFUSES, reports a CONFLICT or an outside edit, or you want to narrow, filter, or re-tune a check. | **X7** — Report the output exactly as produced. Resolve what it names; never work around it. | `rs-x7` |
| the meaning of a symbol, an agreement, or a source is uncertain, or you are about to say "not available", "never said", or "impossible". | **X8** — No absence claim without a failed tool call behind it. | `rs-x8` |
| you are about to ask the user for a concrete function or values. | **X9** — Build the general form with symbols first. | `rs-x9` |
<!-- END GENERATED -->

## 2. Every message: card rs-n1

BEGIN → REGISTER → DISPATCH → LOOP → PROPAGATE → SETTLE → END → SHOW.

`research_begin` repeats this line, and the ledger's OBLIGATIONS are the
session's input. Its view is the rows changed in the last 3 sessions plus every
live row; read any other row with `research_show(ids="…")` before you build on
it. The K awaiting the user stands across sessions: dispatch the new message
from its `U`, and a closing push to USER re-arms that K. `research_end` prints
only the rows changed in the session. Open `rs-n1` in full on the first message
of a conversation, and whenever a step is unclear.

## 3. Documents and exploration in one paragraph

- **Documents.** The user's files are `source` documents: read-only. What you
  write for the user is a `deliverable`: readable prose, with ids hidden in
  section markers, changed only through a committed change list (plan → rewrite
  whole sections → sync, card rs-n4). Your own scratch is `working`.
- **Exploration.** Premises are switches. Explore them freely in named
  configurations: on, off, swapped for an alternative, or a model premise
  added (card rs-ex). Only the user switches the main line.

## 4. Core rules (used in every basis tag)

**Origin** of an item:

- **user**: the user's words, or the same content restated in symbols with
  no structure added (the minimal reading);
- **entailed(<step>)**: follows from user items by a cited step, including
  premises presupposed by a definition the user gave;
- **model**: everything else, such as a larger reading, an added premise, a
  frame, an intermediate object, or a special case.

A model item stays out of the main line until the user adopts it. It may be
used inside named exploration configurations meanwhile, and anything built on
it is `model` too. On adoption, set its origin to `user(adopted, session N)`.
Content cells hold only the user's words for user items; notes go in the
evidence cell.

| item | may be used as |
|---|---|
| origin `model`; status `proposed` | inside exploration configurations and model rows only; never on the main line |
| status `off`, `superseded`, `refuted`, `stale`, `false`, `history` | nothing on the main line (`off` premises may still be members of an exploration configuration) |
| status `question` | nothing (a question is not a premise) |
| `Z` isolated unknown | a symbol or gauge only; never a value, coordinate, or reference location |
| an object marked `proxy(X)` | its own properties; a property of X needs a row showing it transfers |
| evidence `[unverified]` | a premise whose conclusion is at most `[unverified]` |
| evidence `pointer:` (memory lines, other projects) | a search seed for RF only; never a premise |

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

Classifying origins, typing relations (`sup`, `iso`, `spec`, `int`, …), external
results, approximation versus information, and exploration: card `rs-ref-prov`.
