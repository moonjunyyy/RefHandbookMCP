#!/bin/sh
# Install or update the site: sudo deploy/install.sh [site.toml]
# Everything is derived from the site file and the Kerberos realm and rendered by portal/deploy.py
# (python3 standard library only, so it runs before anything is installed). Rerun after any change.
#   --check          print the derived facts and services
#   --render-into    DIR: only render every file under DIR
#   --app ID DIST    publish an app's built files at /apps/ID/
# Paths are taken from where you run it (no cd here): `--app wordgen dist` means ./dist.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m portal.deploy "$@"
