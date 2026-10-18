# PAGE RF — Retrieve: sessions, files, memory, web
KIND: checklist
TAGS: research, normal
TRIGGERS: last time; as we agreed; the lemma; that equation; which paper; unknown symbol; not in this conversation; other project
OBJECTIVE: Resolve a reference from originals (sessions, files, memory pointers, web) and record it with a locator, or record the calls that failed.

ENTRY — object: a K `@RF` `on` the item to resolve (a term, symbol, claim,
agreement, result, or paper). It is pushed by:
- N1 step 2, for an unresolvable reference in the user's message;
- N2 step 1 (context sweep);
- QM2, X8, or any page that needs knowledge from outside this conversation.

◆ Look before you say you do not know, and before you proceed as if you know.
Every recovered item carries the place it came from.

1. **Classify the target.** It is one of:
   - **internal**: the user's own prior work, agreement, symbol, or decision;
   - **external**: a definition, theorem, paper, method, or current fact;
   - **both**.
2. **Internal ladder.** Stop at the first hit in an original.
   1. **This conversation.** Quote the turn.
   2. **Ledger, registered documents, uploaded or project files.** Register a
      user file you rely on as a `source` document (card N4). Use `cat -n` or
      `view`.
   3. **Past chats in scope.** These tools search only the current project, or
      only non-project chats when outside a project.
      - `conversation_search` takes 2–4 **content words** from the target:
        symbols, names, the project's terms. It never takes meta words such as
        "discussed" or "last time".
      - Then open the hit with `read_conversation` at its `page_token`.
      - Open at most 2 chats per target, one page each. Take a second page only
        when the item is cut off at the page edge.
   4. **Memory.** Run `memory_read` on files whose descriptions match. Run
      `memory_list` with `path_prefix=/projects/<id>/` for other projects.
      Memory yields only **pointers** (`pointer: memory:<path>`). Use them to
      sharpen the past-chat search above, or to ask the user. They are never
      premises.
   5. **Another project's chats** (out of scope). Ask the user once for the chat
      link or a paste. If a link is given, try `read_conversation` with its id,
      and record the result either way.
3. **External ladder.**
   1. `web_search` with short queries (1–6 words). Prefer originals: the paper,
      arXiv, official documentation, the author's notes.
   2. Before citing any specific (a statement, a constant, a condition), open
      the page with `web_fetch`.
   3. Use at most one short quote per source, and paraphrase the rest.
   4. When sources disagree, record both, joined by a `con:` edge.
4. **Record** each recovered item as a row:
   - internal agreements and definitions are restored as `U`, `R`, `S`, or `A`
     rows with origin `user`;
   - external results become `T` rows.

   The evidence carries a locator:
   - `sourced: chat:<uuid>` (with the quoted turn);
   - `sourced: file:<path>:<line>`;
   - `sourced: <url>`.

   Snippets, search summaries, and model-written digests are `[unverified]`.
   Memory lines are `pointer:`.
5. **Budget per target.** At most 4 searches and 2 chat reads (internal), and 5
   web searches. Beyond that, ask the user.
6. **Failure** is recorded as `not found: <each call, with its query>`.

**EXITS** (each exit returns objects; `<caller>` = the page of the K that routed here)

- **a**: found in originals and recorded with locators → push `resume <caller step> on <new rows>` @<caller>
- **b**: only pointers or snippets found → push `ask the user to confirm or paste <item>` @USER **and** `resume the independent part` @<caller>
- **c**: not found after the ladder (calls recorded) → push `tell the user what was tried, ask` @USER
- **d**: sources disagree (session vs session, or source vs source) → push `record the conflict as P#` (N2 rule: the latest session wins); also push `ask` @USER if it touches a mandatory C
- **e**: the item lives in another project's chats → push `ask for the chat link or a paste` @USER
