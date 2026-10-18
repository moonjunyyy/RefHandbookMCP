#!/usr/bin/env python3
"""Run the refhandbook CLI from the plugin directory without installing it.

The research skill uses this when a session has no MCP connection to the refhandbook server:
the research tools run here on a local database with the same code the server runs. Needs only
the Python standard library (sqlite3).

    python3 scripts/research.py --db <file> research <tool> '<JSON arguments>'
    python3 scripts/research.py --db <file> show rs-n1
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from refhandbook.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
