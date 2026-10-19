"""Append-only JSON-lines audit log of every login and change: who, what, to whom, from where."""
import json
import logging
import os
from datetime import datetime, timezone

_log = logging.getLogger("ldap_portal.audit")


def setup(path: str) -> None:
    target = os.path.abspath(path)
    if any(getattr(h, "baseFilename", None) == target for h in _log.handlers):
        return
    for h in list(_log.handlers):  # a new app with another log path (tests build several)
        _log.removeHandler(h)
        h.close()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    handler = logging.FileHandler(path)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _log.addHandler(handler)
    _log.setLevel(logging.INFO)
    _log.propagate = False


def record(actor: str | None, action: str, target: str | None, ok: bool, ip: str | None, detail: str = "") -> None:
    _log.info(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor": actor, "action": action, "target": target, "ok": ok, "ip": ip, "detail": detail,
    }, ensure_ascii=False))
