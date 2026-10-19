#!/bin/sh
# Install or update the site: sudo deploy/install.sh [site.toml]
# Everything is derived from the site file and the Kerberos realm and rendered by portal/deploy.py
# (python3 standard library only, so it runs before anything is installed). Rerun after any change.
#   --check        print the derived facts and services
#   --render-into  DIR: only render every file under DIR
set -eu
cd "$(dirname "$0")/.."
exec python3 -m portal.deploy "$@"
