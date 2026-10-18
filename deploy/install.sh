#!/bin/sh
# Install or update the site: sudo deploy/install.sh [site.toml]
# Everything is derived from the site file and the Kerberos realm and rendered by portal/deploy.py
# (python3 standard library only, so it runs before anything is installed). Rerun after any change.
#   --check          print the derived facts and services
#   --render-into    DIR: only render every file under DIR
#   --app ID DIST    publish an app's built files at /apps/ID/
# Paths are taken from where you run it (no cd here): `--app wordgen dist` means ./dist.
set -euo pipefail
set -eu
SRC="$(cd "$(dirname "$0")/.." && pwd)"
REPO=$(cd "$(dirname "$0")/.." && pwd)
PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m portal.deploy "$@"


ENVF=/etc/refhandbook/env
APP=/opt/refhandbook VENV=/opt/refhandbook-venv PY=/opt/refhandbook-python
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[ "$SRC" != "$APP" ] || { echo "run this from the unpacked source, not from $APP"; exit 1; }

# uv: a root-owned copy, so no other account's files run as root or as the service.
UVSRC="$(command -v uv || true)"
[ -n "$UVSRC" ] || { echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ "$UVSRC" = /usr/local/bin/uv ] || install -o root -g root -m 0755 "$UVSRC" /usr/local/bin/uv
UV=/usr/local/bin/uv

id refhandbook >/dev/null 2>&1 || useradd --system --home-dir /var/lib/refhandbook --shell /usr/sbin/nologin refhandbook
install -d -o refhandbook -g refhandbook -m 0700 /var/lib/refhandbook
install -d -o root -g refhandbook -m 0750 /etc/refhandbook

rm -rf "$APP.new" && mkdir -p "$APP.new"
tar -C "$SRC" --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=dist -cf - . | tar -C "$APP.new" -xf -
chown -R root:root "$APP.new" && chmod -R go-w,a+rX "$APP.new"
rm -rf "$APP.old"; [ -d "$APP" ] && mv "$APP" "$APP.old"
mv "$APP.new" "$APP"

if [ ! -f "$ENVF" ]; then
  install -o root -g refhandbook -m 0640 "$SRC/deploy/refhandbook.env.example" "$ENVF"
  if [ -r /etc/nslcd.conf ]; then
    { echo; echo "# taken from /etc/nslcd.conf (these lines override the ones above)"; \
      python3 "$APP/scripts/research.py" nslcd-env /etc/nslcd.conf; } >> "$ENVF"
    BINDPW="$(awk '$1=="bindpw"{sub(/^[ \t]*bindpw[ \t]+/,""); print; exit}' /etc/nslcd.conf)"
    if [ -n "$BINDPW" ]; then
      ( umask 077; printf '%s' "$BINDPW" > /etc/refhandbook/ldap-bindpw )
      chown refhandbook:refhandbook /etc/refhandbook/ldap-bindpw; chmod 0400 /etc/refhandbook/ldap-bindpw
      echo "copied nslcd's bind password to /etc/refhandbook/ldap-bindpw (0400)"
    fi
  fi
  echo "now set RHB_PUBLIC_URL in $ENVF, then run this script again"
  exit 0
fi
grep -q '^RHB_PUBLIC_URL=https://hb.example.org$' "$ENVF" && { echo "set RHB_PUBLIC_URL in $ENVF first"; exit 1; }

# PAM service for RHB_AUTH=pam (the default): the system's password check (common-auth).
# Not common-account: pam_unix's account phase reads shadow through a setuid/setgid helper, which a
# non-root service under NoNewPrivileges cannot run, so it would refuse every directory account.
# The account policy is the server's own: the name must resolve through NSS (and RHB_REQUIRE_GROUP).
# Kept if it exists, so a hand-tuned stack survives updates.
if [ ! -e /etc/pam.d/refhandbook ]; then
  HEAD="# refhandbook: the system's password check; account policy is the server's own (NSS + RHB_REQUIRE_GROUP)"
  if [ -e /etc/pam.d/common-auth ]; then
    printf '%s\n' "$HEAD" "@include common-auth" "account required pam_permit.so" > /etc/pam.d/refhandbook
  elif [ -e /etc/pam.d/system-auth ]; then
    printf '%s\n' "$HEAD" "auth    include system-auth" "account required pam_permit.so" > /etc/pam.d/refhandbook
  else
    echo "no common-auth or system-auth in /etc/pam.d: write /etc/pam.d/refhandbook yourself"; exit 1
  fi
  chmod 0644 /etc/pam.d/refhandbook
  echo "wrote /etc/pam.d/refhandbook"
fi

# The venv and its Python, as root; readable by the service, writable only by root.
# Only a uv-managed Python under $PY: uv otherwise reuses any 3.14 it finds (root's own, under
# /root), and the venv would point at an interpreter the service user cannot reach.
export UV_PYTHON_INSTALL_DIR=$PY UV_PYTHON_PREFERENCE=only-managed UV_PROJECT_ENVIRONMENT=$VENV
REQ=$(grep -oP '^requires-python = ">=\K[0-9.]+' "$APP/pyproject.toml")
"$UV" python install --no-bin "$REQ" 2>/dev/null || "$UV" python install "$REQ"
rm -rf "$VENV"   # a venv made earlier keeps pointing at whatever interpreter it was made with
"$UV" sync --frozen --no-dev --no-editable --project "$APP"
chmod -R go-w,a+rX "$VENV" "$PY"
case "$(readlink -f "$VENV/bin/python")" in
  "$PY"/*) ;;
  *) echo "venv interpreter is outside $PY: $(readlink -f "$VENV/bin/python")"; exit 1 ;;
esac
# The service user must be able to run it before the unit is installed.
if ! sudo -u refhandbook "$VENV/bin/refhandbook" --help >/dev/null 2>&1; then
  echo "user refhandbook cannot run $VENV/bin/refhandbook:"
  sudo -u refhandbook "$VENV/bin/refhandbook" --help 2>&1 | head -3
  namei -l "$(readlink -f "$VENV/bin/python")"
  exit 1
fi
"$VENV/bin/refhandbook" --env-file "$ENVF" plugin-json "$(grep -oP '^RHB_PUBLIC_URL=\K.*' "$ENVF" | tail -1 | sed 's#/*$##')/mcp" >/dev/null

install -o root -g root -m 0644 "$SRC/deploy/refhandbook.service" /etc/systemd/system/refhandbook.service
systemctl daemon-reload
systemctl enable refhandbook >/dev/null
systemctl restart refhandbook
PORT=$(grep -oP '^RHB_PORT=\K\d+' "$ENVF" | tail -1 || true)
for _ in $(seq 1 15); do
  curl -fsS "http://127.0.0.1:${PORT:-8765}/healthz" >/dev/null 2>&1 && break; sleep 1
done
curl -fsS "http://127.0.0.1:${PORT:-8765}/healthz" && echo "  <- service is up" || { journalctl -u refhandbook -n 30 --no-pager; exit 1; }
cat <<MSG
next:
  1. test a sign-in:   sudo -u refhandbook $VENV/bin/refhandbook --env-file $ENVF check-login <uid>
  2. put deploy/nginx.conf (or deploy/Caddyfile) in front, then from outside:
       curl -s https://<domain>/.well-known/oauth-protected-resource/mcp
MSG
