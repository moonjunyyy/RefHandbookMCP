#!/usr/bin/env bash
# Build release files into OUT (default: dist/):
#   refhandbookmcp-server-<ver>.tar.gz   the project, to unpack on the server and run deploy/install.sh
#   refhandbookmcp-<ver>.plugin          the plugin; with a URL argument it declares the remote server,
#                                        without one it keeps the local (stdio) declaration
# usage: scripts/pack.sh [https://<domain>/mcp] [OUT]
set -euo pipefail
cd "$(dirname "$0")/.."
URL="${1:-}"; OUT="${2:-dist}"
VER=$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
EXCL=(--exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=dist --exclude='*.db' --exclude='*.db-*')

tar "${EXCL[@]}" -czf "$OUT/refhandbookmcp-server-$VER.tar.gz" --transform "s,^\.,refhandbookmcp-$VER," .

mkdir -p "$STAGE/p" && tar "${EXCL[@]}" -cf - . | tar -C "$STAGE/p" -xf -
if [ -n "$URL" ]; then
  python3 scripts/research.py plugin-json "$URL" --write "$STAGE/p/.claude-plugin/plugin.json" >/dev/null
fi
rm -f "$OUT/refhandbookmcp-$VER.plugin"
(cd "$STAGE/p" && zip -qr "$OUT/refhandbookmcp-$VER.plugin" . -x 'deploy/*' 'tests/*')
echo "$OUT/refhandbookmcp-server-$VER.tar.gz"
echo "$OUT/refhandbookmcp-$VER.plugin  ($( [ -n "$URL" ] && echo "remote: $URL" || echo local ))"
