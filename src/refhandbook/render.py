"""Plain-text rendering. The card layout follows CAP 676: title, then the
condition and objective that confirm the right card was picked, memory items
first, numbered steps, deferred items last, and an explicit end marker."""

from __future__ import annotations

from typing import Any

PHASE_HEADINGS = {
    "memory": "MEMORY ITEMS — do these first, before reading further",
    "action": "ACTIONS",
    "deferred": "DEFERRED ITEMS — do later, when the stated condition arrives",
}


def device_note(tags: list[str] | str | None, running: str | None = None) -> str:
    """A card tagged `device:<version>` describes the device as that version had it. Opened on a
    server that runs another version, it says so: what it states about the device may have changed."""
    if isinstance(tags, str):
        tags = tags.split()
    marked = sorted({t.split(":", 1)[1] for t in tags or [] if t.startswith("device:")})
    if not marked:
        return ""
    if running is None:
        from . import version

        running = version()
    if running in marked:
        return ""
    return (f"DEVICE {', '.join(marked)}: written for that version; this server runs {running}. "
            "Verify what it says about tools and rules before relying on it, then update the card and its tag.")


def _ref(entry_id: str, title: str | None) -> str:
    return f"[{entry_id}] {title}" if title else f"[{entry_id}] (MISSING ENTRY)"


def _step(number: int, item: dict[str, Any]) -> str:
    parts = []
    if item["when"]:
        # A deferred item waits for its moment; an action branches on a state.
        parts.append(f"{'WHEN' if item['phase'] == 'deferred' else 'IF'} {item['when']}:")
    if item["text"]:
        parts.append(item["text"])
    line = " ".join(parts)
    if item["response"]:
        line += f" {'.' * max(3, 46 - len(line))} {item['response']}"
    if item["goto"]:
        line += f"  >> GO TO {_ref(item['goto'], item['goto_title'])}"
    if item["ends"]:
        line += "  ## END"
    return f"{number:>3}. {line}".replace("\n", "\n     ")


def route(title: str, ledgers: list[str]) -> str:
    """An entry that routes to a card, as one line: the topic, and the ledger its work is entered through."""
    return f"{title} — ledger {', '.join(ledgers)}" if ledgers else f"{title} (no ledger)"


def card(entry: dict[str, Any], neighbors: list[dict[str, Any]],
         routes: list[tuple[str, list[str]]] | None = None) -> str:
    out = [f"# {entry['title']}", f"[{entry['id']}] {entry['kind']} · rev {entry['revision']} · {entry['updated_at']}"]
    if entry["tags"]:
        out[-1] += " · " + " ".join(f"#{t}" for t in entry["tags"])
    if note := device_note(entry["tags"]):
        out.append(note)
    out.append("")
    for name, ledgers in routes or []:
        # the card is one of an entry's routes: the work it describes is entered there, before the card is used
        out.append(f"ENTRY      {route(name, ledgers)}." + "".join(
            f' Work on this runs in a session of that ledger: research_begin(ledger="{led}") first (card rs-n1).'
            for led in ledgers[:1]))
    if entry["condition"]:
        out.append(f"CONDITION  {entry['condition']}")
    if entry["triggers"]:
        out.append("CUES       " + " | ".join(entry["triggers"]))
    if entry["objective"]:
        out.append(f"OBJECTIVE  {entry['objective']}")
    if entry["body"]:
        out += ["", entry["body"].strip()]

    number, phase = 0, None
    for item in entry["items"]:
        if item["phase"] != phase:
            phase = item["phase"]
            out += ["", PHASE_HEADINGS[phase]]
        if item["kind"] == "step":
            number += 1
            out.append(_step(number, item))
        else:
            out.append(f"     {item['kind'].upper()}: {item['text']}".replace("\n", "\n     "))
    if entry["items"]:
        out += ["", f"## END OF {entry['title']}"]

    if neighbors:
        out += ["", "RELATED"]
        out += [
            f"  {n['label']} -> {_ref(n['id'], n['title'])}" + (f"  ({n['note']})" if n["note"] else "")
            for n in neighbors
        ]
    return "\n".join(out)


LOOP_SHOWN = 3  # how many open sessions the line names; the rest are counted


def _ago(seconds: float) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("min", 60)):
        if seconds >= 2 * size:
            return f"{int(seconds // size)} {unit}"
    return f"{int(max(seconds, 0))} s"


def loop_state(open_sessions: list[dict[str, Any]], now: float, calls: int | None = None,
               last_used: float | None = None) -> str:
    """The state of the session loop as the store has it, on one line: the open sessions (most recently
    used first) or that there is none, and `calls`, the changing calls made since a chat session was
    last used (at `last_used`). Inside the loop that count starts again with every research call;
    outside it only grows, whatever sessions other conversations left open. A tool that changes
    something outside a ledger ends its result with this line, so whether the work is inside a session
    is shown where the work happens, not remembered."""
    count = ""
    if calls is not None:
        since = f"{_ago(now - last_used)} ago" if last_used else "never"
        count = f" · {calls} changing call{'' if calls == 1 else 's'} since a chat session was last used ({since})"
    if not open_sessions:
        return (f"LOOP  no session is open{count}. Work that has a ledger is answered inside a session of it: "
                "research_begin(ledger=…) first (card rs-n1); calls made without one are missed messages (card rs-x7).")
    shown = [f"{s['scope']} {s['id']} ({s['role']}, used {_ago(now - s['active'])} ago)" for s in open_sessions[:LOOP_SHOWN]]
    more = len(open_sessions) - len(shown)
    return "LOOP  open: " + "; ".join(shown) + (f"; and {more} older" if more > 0 else "") + count


def candidates(situation: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"No entry matches {situation!r}. Try other words, or browse with index."
    out = [f"{len(rows)} candidate(s) for {situation!r}. Confirm the CONDITION fits before opening one.", ""]
    for r in rows:
        out.append(f"[{r['id']}] {r['title']}  ({r['kind']})")
        if r["superseded_by"]:
            out.append(f"    SUPERSEDED BY {r['superseded_by']} — open that instead")
        if note := device_note(r.get("device")):
            out.append(f"    {note}")
        for name, ledgers in r.get("routes") or []:
            out.append(f"    entry: {route(name, ledgers)}")
        if r["condition"]:
            out.append(f"    condition: {r['condition']}")
        if r["objective"]:
            out.append(f"    objective: {r['objective']}")
    return "\n".join(out)


def index(groups: dict[str, list[dict[str, Any]]]) -> str:
    if not groups:
        return "The handbook is empty. Add entries with save_entry."
    out = []
    for group, rows in groups.items():
        out.append(f"{group}")
        out += [f"  [{r['id']}] {r['title']}" + (f" — {r['condition']}" if r["condition"] else "") for r in rows]
    return "\n".join(out)


def walk(start: str, hops: list[dict[str, Any]]) -> str:
    if not hops:
        return f"[{start}] has no related entries within range."
    return "\n".join(
        [f"From [{start}]:"]
        + [f"{'  ' * h['depth']}[{h['from']}] {h['label']} -> {_ref(h['id'], h['title'])}" for h in hops]
    )


def audit(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "Audit clean: no findings."
    errors = sum(f["level"] == "error" for f in findings)
    out = [f"{len(findings)} finding(s): {errors} error(s), {len(findings) - errors} warning(s)."]
    out += [f"  {f['level'].upper():7} [{f['entry']}] {f['message']}" for f in findings]
    return "\n".join(out)
