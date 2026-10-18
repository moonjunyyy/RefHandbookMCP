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


def card(entry: dict[str, Any], neighbors: list[dict[str, Any]]) -> str:
    out = [f"# {entry['title']}", f"[{entry['id']}] {entry['kind']} · rev {entry['revision']} · {entry['updated_at']}"]
    if entry["tags"]:
        out[-1] += " · " + " ".join(f"#{t}" for t in entry["tags"])
    out.append("")
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


def candidates(situation: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"No entry matches {situation!r}. Try other words, or browse with index."
    out = [f"{len(rows)} candidate(s) for {situation!r}. Confirm the CONDITION fits before opening one.", ""]
    for r in rows:
        out.append(f"[{r['id']}] {r['title']}  ({r['kind']})")
        if r["superseded_by"]:
            out.append(f"    SUPERSEDED BY {r['superseded_by']} — open that instead")
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
