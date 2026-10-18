"""The plugin manifest for a remote server. Standard library only (packing runs without the deps)."""

from __future__ import annotations

import json
import re
from pathlib import Path


def project_version() -> str:
    try:
        from importlib.metadata import version

        return version("refhandbookmcp")
    except Exception:  # running from a source tree without an install
        text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
        return re.search(r'^version = "([^"]+)"', text, re.M).group(1)  # type: ignore[union-attr]


def plugin_json(url: str, version: str | None = None) -> dict:
    """One http MCP server and no local command: works in Chat, Cowork and Claude Code alike."""
    if not url.startswith("https://") or not url.rstrip("/").endswith("/mcp"):
        raise ValueError("the URL must be https://<domain>/mcp")
    return {
        "name": "refhandbookmcp",
        "version": version or project_version(),
        "description": "A quick reference handbook served over MCP: condition-indexed cards linked by relations, "
                       "the research cards (rs-*), and the research ledger. Remote server, one store per signed-in user.",
        "author": {"name": "Moonny"},
        "mcpServers": {"refhandbook": {"type": "http", "url": url.rstrip("/")}},
    }


def dump_plugin_json(url: str, version: str | None = None) -> str:
    return json.dumps(plugin_json(url, version), ensure_ascii=False, indent=2) + "\n"
