#!/bin/sh
# docs/frame.md §7 C7: the mock site as a Playwright route (no socket) around the built pages (web/dist),
# the real frame files (src/portal/static) and eq-sandbox's widget, in Chromium (headless shell); then the
# legibility measure in both colour schemes and the layout measure (layout.js). Needs node, playwright and its chromium; the roots below are
# taken from this tree and may be overridden (NODE_BIN, PLAYWRIGHT_BROWSERS_PATH, EQ_ROOT).
cd "$(dirname "$0")"
export PATH=${NODE_BIN:-/work/node/bin}:$PATH
export PLAYWRIGHT_BROWSERS_PATH=${PLAYWRIGHT_BROWSERS_PATH:-/work/pw-browsers}
export PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-ubuntu24.04-x64}
export NODE_PATH=${NODE_PATH:-/work/e2e/node_modules}   # where playwright is installed
export STATIC_ROOT=${STATIC_ROOT:-$(cd ../../src/portal/static && pwd)}
export DIST_ROOT=${DIST_ROOT:-$(cd ../dist && pwd)}
export WORDGEN_ROOT=${WORDGEN_ROOT:-$(cd ../../apps/WordGenerator/dist && pwd)}
export EQ_ROOT=${EQ_ROOT:-/work/frame-e2e/eq}
# the look's choices as /me carries them (portal/site.py reads [look] of the site file — the mock takes the same declaration)
export LOOK_JSON=${LOOK_JSON:-$(cd ../.. && PYTHONPATH=src python3 -c 'import json, tomllib; from portal.site import Site, _look; print(json.dumps(Site((), _look(tomllib.load(open("deploy/site.toml", "rb")))).look_in("ko"), ensure_ascii=False))')}
rm -rf out
node e2e.js > e2e.log 2>&1
grep -v '^ok' e2e.log
ok=$(grep -c '"ok": true' out/report.json); bad=$(( $(grep -c '"ok": false' out/report.json) + $(grep -c '"exception: ' out/report.json) ))
for s in light dark; do
  line=$(SCHEME=$s node contrast.js | head -1)
  echo "contrast ($s): $line"
  case "$line" in *"below 4.5:1: 0;"*) ok=$((ok + 1));; *) bad=$((bad + 1));; esac
done
node layout.js > layout.log 2>&1
line=$(head -1 layout.log)
echo "layout: $line"
grep '^BAD' layout.log | head -20
case "$line" in *"violations: 0"*) ok=$((ok + 1));; *) bad=$((bad + 1));; esac
if node appearance.js; then ok=$((ok + 1)); else bad=$((bad + 1)); fi
if node procedure.js; then ok=$((ok + 1)); else bad=$((bad + 1)); fi
# the calendar's head, scale and room (calendar-scale.js)
if node calendar-scale.js > scale.log 2>&1; then ok=$((ok + 1)); else bad=$((bad + 1)); fi
head -1 scale.log
grep '^FAIL' scale.log
echo "steps: $ok ok, $bad failed"
test "$bad" -eq 0
