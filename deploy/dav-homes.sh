#!/usr/bin/env bash
# Make /data/<uid> for every member of the default group, so /dav/<uid>/ works from the first
# sign-in. Run as root, e.g. from a systemd timer every few minutes (dav-homes.timer).
# nginx (www-data) serves and writes the files: each directory is www-data's, mode 0700.
set -euo pipefail
GROUP="${1:-user}" ROOT="${DAV_ROOT:-/data}" OWNER="${DAV_OWNER:-www-data}"
install -d -o root -g root -m 0755 "$ROOT"
install -d -o "$OWNER" -g "$OWNER" -m 0700 "$ROOT/.upload"   # client_body_temp_path
members="$(getent group "$GROUP" | cut -d: -f4)"
IFS=, read -r -a uids <<< "$members"
for u in "${uids[@]}"; do
  [[ "$u" =~ ^[a-z][a-z0-9_-]{1,31}$ ]] || { echo "skipping odd name: $u" >&2; continue; }
  [ -d "$ROOT/$u" ] && continue
  install -d -o "$OWNER" -g "$OWNER" -m 0700 "$ROOT/$u"
  echo "created $ROOT/$u"
done
