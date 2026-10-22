# PAGE SPLIT — Split a card that holds more than one topic
KIND: checklist
TAGS: research, normal, handbook
TRIGGERS: SPLIT BEFORE USE; holds more than one topic; decomposable card; card too long; sub-procedures; split a card; atomic card
OBJECTIVE: One card per topic: each part a procedure (one situation, one outcome, one sequence) or a set (one list or table), the original id kept as the first part or as their index.

ENTRY — signal: `open_entry` says SPLIT BEFORE USE, `save_entry` or `cap` refuses a card that holds
more than one topic, or `audit` reports one.

◆ Split before you follow it. Follow the part that fits, never the whole.

1. Name the parts from what the device listed: each sub-procedure, each set
   (a list or a table), and the procedure that remains.
2. Give each part its own situation: the condition that confirms it applies,
   and triggers it is found by. A part that has no situation of its own is not
   a part; it stays in the card it serves.
3. Write each part as its own card (`save_entry`, or `cap(kind="card")` for a
   record of yours): a procedure of at most 10 steps, or one list or one table.
4. Keep the original id. If one part is the entry to the others, it becomes
   that part and sends the reader on (GO TO, or an exit); otherwise it becomes
   their index: a reference card whose body only lists the parts.
5. Link the parts: `relate(part, "part_of", original)` for an index, and
   `precedes` (or GO TO) where one part follows another.
6. Run `audit`. Repeat for any card it still reports.
7. Continue the work with the part that fits the situation in front of you.
