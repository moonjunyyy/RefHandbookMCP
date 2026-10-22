# PAGE START-CARDS — The cards: ids, finding them, their parts
KIND: reference
TAGS: research, reference
TRIGGERS: card parts; card ids; rs-*; find a card; open a card; open_entry; lookup research; ENTRY; numbered steps; EXITS; closing item; no card fits; bend a situation to fit a card; judgment
OBJECTIVE: How research cards are named and found, the parts every card has, and what to do when no card fits.

Consulted when you need to find or open a card, read its parts, or no card fits
the situation; return to the step that sent you.

**Cards.** Every procedure is a card with id `rs-*`. `research_next` prints the
card of the plan object it starts; `open_entry("rs-n1")` opens any card;
`lookup("<symptom>", scope="research")` finds one by its cues. Every card has
the same parts:
- ENTRY: the start condition, meaning the K it consumes and the rows it acts on;
- numbered steps;
- EXITS: each exit returns objects, the K objects it pushes;
- a closing item: done → continue → close → next message.

The handbook does not replace judgment. If no card fits, say so in one line and
push to `USER`. Never bend a situation to fit a card.
