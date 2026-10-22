# The current Node.js LTS from nodejs.org, under /opt/node, linked into /usr/local/bin.
set -eu
arch=$(uname -m); case "$arch" in x86_64) a=x64 ;; aarch64) a=arm64 ;; *) a=$arch ;; esac
v=$(python3 /recipes/fetch.py --json https://nodejs.org/dist/index.json "[r['version'] for r in d if r['lts']][0]")
python3 /recipes/fetch.py --sums "https://nodejs.org/dist/${v}/SHASUMS256.txt" \
  --unpack "https://nodejs.org/dist/${v}/node-${v}-linux-${a}.tar.xz" /opt/node 1
mkdir -p /usr/local/bin
for b in node npm npx corepack; do ln -sf /opt/node/bin/$b /usr/local/bin/$b; done
/usr/local/bin/node --version
