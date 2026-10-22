"""The kernel's own capability kinds: rule, alias, card. The sandbox's (policy, script, layer) are in
agents/capkinds.py.

    rule   a kernel rule (Datalog). In force = defined in k_rules: the model's run as warnings until
           the user approves them on the approval page (kernel/proposals.py), as before.
    alias  a name for something else: a script with fixed arguments, or a tool under an old name.
           A deprecated tool keeps working through its alias, with a warning, until the alias retires.
    card   a handbook card (an entry): a procedure the model keeps up to date. Its review is the
           handbook's audit of that card.
"""

from __future__ import annotations

import re
from typing import Any

from . import proposals
from .capabilities import DAY, CapError, Kind, Registry, register
from .graph import NAME_RE as RULE_ID, PHASES, SEVERITIES, Forbidden

RULE_FIELDS = ("phase", "body", "message", "severity", "applies_to", "replaces", "description")


class RuleKind(Kind):
    name = "rule"
    description = "a kernel rule (check, obligation, close, pre or derive), in the rule language of card rs-rv"
    ttl = 60 * DAY

    def validate(self, reg: Registry, name: str, spec: dict[str, Any], body: str | None) -> dict[str, Any]:
        if not RULE_ID.match(name.replace("-", "_")) or "-" in name or "." in name:
            raise CapError(f"rule name {name!r}: lowercase letters, digits and _ (it names the predicate)")
        bad = set(spec) - set(RULE_FIELDS)
        if bad:
            raise CapError(f"unknown rule fields {sorted(bad)}; known: {', '.join(RULE_FIELDS)}")
        if spec.get("phase") not in PHASES:
            raise CapError(f"rule {name}: phase is one of {', '.join(PHASES)}")
        if not str(spec.get("body", "")).strip():
            raise CapError(f"rule {name}: body holds its clauses")
        spec.setdefault("severity", "block")
        if spec["severity"] not in SEVERITIES:
            raise CapError(f"rule {name}: severity is one of {', '.join(SEVERITIES)}")
        spec.setdefault("applies_to", "ledger" if spec["phase"] != "derive" else "*")
        reps = spec.get("replaces") or []
        spec["replaces"] = reps.split() if isinstance(reps, str) else list(reps)
        return spec

    def apply(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> None:
        s = ver["spec"]
        reg.g.define_rules([{"id": rec["attrs"]["name"], **{k: s[k] for k in ("phase", "body", "severity", "applies_to")},
                             "message": s.get("message", "")}], actor=ver["author"])
        if s.get("replaces"):
            proposals.record(reg.g, rec["attrs"]["name"], s["replaces"])

    def guard(self, reg: Registry, rec: dict[str, Any], actor: str) -> None:
        r = reg.g.get_rule(rec["attrs"]["name"])
        if actor == "model" and r is not None and r["state"] == "active" and r["authority"] != "proposed":
            raise Forbidden(f"rule {r['id']} was approved by the user ({r['authority']}): only the user changes or "
                            "retires it now")

    def unapply(self, reg: Registry, rec: dict[str, Any]) -> None:
        r = reg.g.get_rule(rec["attrs"]["name"])
        if r is not None and r["state"] == "active":
            reg.g.retire_rule(r["id"], actor="kernel")

    def check(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> tuple[str, str]:
        r = reg.g.get_rule(rec["attrs"]["name"])
        if r is None or r["state"] != "active":
            return "fail", "the rule is no longer defined in the kernel (rejected or retired)"
        return "pass", r["authority"]

    def summary(self, spec: dict[str, Any]) -> str:
        return spec.get("description") or spec.get("message", "")

    def report(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> str:
        """The trial: a check or obligation rule runs at once on every ledger (as a warning while it is
        the model's). One over its budget is refused, so nothing too costly stays in force."""
        from .rules import OVER_BUDGET, evaluate

        rid, phase = rec["attrs"]["name"], ver["spec"]["phase"]
        r = reg.g.get_rule(rid)
        state = "a proposal: it warns and blocks nothing until the user approves it" \
            if r and r["authority"] == "proposed" else f"{r['authority'] if r else '?'}"
        if phase not in ("check", "obligation"):
            return f"  rule {rid} [{phase}] is {state}; it is evaluated when a {phase} gate runs"
        out = []
        for (L,) in reg.g.db.execute("SELECT id FROM k_nodes WHERE type = 'ledger' ORDER BY id").fetchall():
            hits = [f.message for f in evaluate(reg.g, phase, L, "ledger") if f.rule == rid]
            if any(h.startswith(OVER_BUDGET) for h in hits):  # the write rolls back: nothing is kept
                raise CapError(f"rule {rid} is too costly to run on every ledger ({L}: {hits[0]}); it was not kept")
            if hits:
                out.append(f"  {L}: {len(hits)} finding(s)" + "".join(f"\n      {h}" for h in hits[:5]))
        return f"  rule {rid} [{phase}] is {state}. Trial: " + ("\n" + "\n".join(out) if out else "no findings")


class AliasKind(Kind):
    name = "alias"
    description = "another name: a script with fixed leading arguments (target script:<name>), or a tool (tool:<name>)"
    ttl = 90 * DAY
    grace = 30 * DAY

    def validate(self, reg: Registry, name: str, spec: dict[str, Any], body: str | None) -> dict[str, Any]:
        bad = set(spec) - {"target", "args", "fixed", "description"}
        if bad:
            raise CapError(f"unknown alias fields {sorted(bad)}")
        target = str(spec.get("target", ""))
        kind, _, tname = target.partition(":")
        if kind == "tool":
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", tname):
                raise CapError(f"alias {name}: tool:{tname!r} is not a tool name")
        elif kind in ("script",):
            reg.get(kind, tname)
        else:
            raise CapError(f"alias {name}: target is script:<name> or tool:<name>, not {target!r}")
        args = spec.get("args") or []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise CapError("alias args is a list of strings")
        spec["args"] = args
        if not isinstance(spec.get("fixed") or {}, dict):
            raise CapError("alias fixed is an object of tool arguments")
        return spec

    def check(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> tuple[str, str]:
        kind, _, tname = ver["spec"]["target"].partition(":")
        if kind == "tool":
            return "pass", ""
        try:
            reg.in_force(kind, tname)
        except CapError as e:
            return "fail", str(e)
        return "pass", ""

    def summary(self, spec: dict[str, Any]) -> str:
        return spec.get("description") or f"→ {spec.get('target')} {' '.join(spec.get('args') or [])}".rstrip()


CARD_FIELDS = ("title", "kind", "condition", "objective", "body", "triggers", "tags", "items")


class CardKind(Kind):
    name = "card"
    description = "a handbook card: title, condition, objective, items (the handbook's save_entry fields)"
    ttl = 90 * DAY

    def validate(self, reg: Registry, name: str, spec: dict[str, Any], body: str | None) -> dict[str, Any]:
        bad = set(spec) - set(CARD_FIELDS)
        if bad:
            raise CapError(f"unknown card fields {sorted(bad)}; known: {', '.join(CARD_FIELDS)}")
        if name.startswith("rs-"):
            raise CapError("rs-* cards are the research package's")
        if not str(spec.get("title", "")).strip():
            raise CapError("a card needs a title")
        hb = reg.ctx.get("hb")
        if hb is not None and reg.find("card", name) is None and hb.exists(name):
            raise CapError(f"card {name!r} is a handbook entry already (not a record): pick another name")
        from ..store import _clean_item, decomposition

        try:
            items = [_clean_item(i, n) for n, i in enumerate(spec.get("items") or [], 1)]
        except Exception as e:  # noqa: BLE001 — HandbookError: a bad item
            raise CapError(str(e)) from e
        parts = decomposition({"kind": spec.get("kind") or "checklist", "body": spec.get("body") or "", "items": items})
        if parts:
            raise CapError(f"card {name} holds more than one topic: {' · '.join(parts)}; one record per part "
                           "(card rs-split)")
        return spec

    def apply(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> None:
        hb = reg.ctx.get("hb")
        if hb is None:
            raise CapError("cards need the handbook")
        e = hb.save_entry(id=rec["attrs"]["name"], **ver["spec"])
        reg.g.update_node(rec["id"], actor="kernel", attrs={"card_revision": e["revision"]})

    def unapply(self, reg: Registry, rec: dict[str, Any]) -> None:
        """The card goes with its record, unless someone edited it outside the record since."""
        hb = reg.ctx.get("hb")
        name = rec["attrs"]["name"]
        if hb is not None and hb.exists(name):
            if hb.get_entry(name)["revision"] == reg.g.node(rec["id"])["attrs"].get("card_revision"):
                hb.delete_entry(name)
            else:
                reg.g.log("kernel", f"card {name} kept: edited outside its record", rec["id"])

    def check(self, reg: Registry, rec: dict[str, Any], ver: dict[str, Any]) -> tuple[str, str]:
        hb = reg.ctx.get("hb")
        if hb is None:
            return "pending", ""
        if not hb.exists(rec["attrs"]["name"]):
            return "fail", "the card is gone from the handbook"
        errors = [f["message"] for f in hb.audit() if f["entry"] == rec["attrs"]["name"] and f["level"] == "error"]
        return ("fail", "; ".join(errors)) if errors else ("pass", "")

    def summary(self, spec: dict[str, Any]) -> str:
        return spec.get("title", "")


for _k in (RuleKind(), AliasKind(), CardKind()):
    register(_k)
