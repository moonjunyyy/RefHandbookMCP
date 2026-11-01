#!/bin/sh
# docs/frame.md §7 C7: the mock site as a Playwright route (no socket) around the built pages (web/dist),
# the real frame files (src/portal/static) and eq-sandbox's widget, in Chromium (headless shell); then the
# legibility measure in both colour schemes. Needs node, playwright and its chromium; the roots below are
# taken from this tree and may be overridden (NODE_BIN, PLAYWRIGHT_BROWSERS_PATH, EQ_ROOT).
cd "$(dirname "$0")"
export PATH=${NODE_BIN:-/work/node/bin}:$PATH
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-/work/pw-browsers}
export PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-ubuntu24.04-x64}
export STATIC_ROOT=${STATIC_ROOT:-$(cd ../../src/portal/static && pwd)}
export DIST_ROOT=${DIST_ROOT:-$(cd ../dist && pwd)}
export EQ_ROOT=${EQ_ROOT:-/work/frame-e2e/eq}
rm -rf out
node e2e.js > e2e.log 2>&1
grep -v '^ok' e2e.log
ok=$(grep -c '"ok": true' out/report.json); bad=$(( $(grep -c '"ok": false' out/report.json) + $(grep -c '"exception: ' out/report.json) ))
for s in light dark; do
  line=$(SCHEME=$s node contrast.js | head -1)
  echo "contrast ($s): $line"
  case "$line" in *"below 4.5:1: 0;"*) ok=$((ok + 1));; *) bad=$((bad + 1));; esac
done
echo "steps: $ok ok, $bad failed"
