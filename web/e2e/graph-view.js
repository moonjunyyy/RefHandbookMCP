// The knowledge graph's page (/handbook, web/src/pages/graph.ts), in Chromium against the mock site (run.sh sets the
// roots): the overview is drawn (two topics and what joins them); a topic pressed opens into its rows and says itself
// beside the drawing, and pressed again closes; a node dragged moves and is not taken for a press; the scale changes;
// the drawing takes the room of the window. First line of the output: "graph view: N steps, failed: M".
const { chromium } = require('playwright');
const mock = require('./mock');

const BASE = mock.ORIGIN;
const lines = [], failed = [], errors = [];
const step = (name, ok, detail) => { lines.push(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`); if (!ok) failed.push(name); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nodes = (page) => page.$eval('.kg-canvas', (c) => c.graph.nodes());
const point = (page, id) => page.$eval('.kg-canvas', (c, i) => c.graph.point(i), id);
const side = (page) => page.$eval('.kg-side', (e) => e.innerText.trim());
const press = async (page, id) => { const [x, y] = await point(page, id); await page.mouse.click(x, y); await sleep(500); };

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx);
  mock.reset();
  mock.put('site', 'prefs', { apps: ['refhandbook'] });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(`${BASE}/handbook`, { waitUntil: 'networkidle' });
  await page.waitForSelector('.kg-canvas[data-nodes]');
  await sleep(400);

  const first = await nodes(page);
  step('개괄: 주제 둘과 그 둘을 잇는 것(함께 닿는 행 · 태그)과 카드', first.length === 5 && first.filter((n) => n.type === 'entry').length === 2, JSON.stringify(first.map((n) => n.id)));
  const apart = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
  const far = first.every((a) => first.every((b) => a === b || apart(a, b) > 12)) && first.every((n) => Number.isFinite(n.x) && Math.abs(n.x) < 3000 && Math.abs(n.y) < 3000);
  step('배치: 노드가 겹치지 않고 유한한 자리에 있다', far, JSON.stringify(first.map((n) => [Math.round(n.x), Math.round(n.y)])));
  const inked = await page.$eval('.kg-canvas', (c) => { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i]) n++; return n; });
  step('그림: 캔버스에 그려져 있다', inked > 500, String(inked));
  const stage = await page.$eval('.kg-stage', (b) => ({ bottom: Math.round(b.getBoundingClientRect().bottom), window: window.innerHeight, height: b.clientHeight }));
  step('그림은 창 아래 끝까지를 쓴다', stage.bottom <= stage.window && stage.window - stage.bottom < 80 && stage.height > 300, JSON.stringify(stage));
  step('범례 다섯과 안내', (await page.$$('.kg-legend .kg-key')).length === 5 && (await side(page)).includes('노드를 누르면'));

  await press(page, 'n:geo');
  const opened = await nodes(page);
  step('주제를 누르면 그 행으로 펼쳐진다', opened.length === 7 && opened.some((n) => n.id === 'n:h1'), JSON.stringify(opened.map((n) => n.id)));
  const said = await side(page);
  step('옆에 그 주제를 말한다', said.includes('로그 차트') && said.includes('행 3개') && said.includes('원장 geo'), said.replace(/\s+/g, ' ').slice(0, 120));
  await press(page, 'tag:charts');
  step('다른 노드를 누르면 그것을 말한다', (await side(page)).startsWith('charts'), (await side(page)).slice(0, 40));
  await press(page, 'n:geo');
  step('다시 누르면 접힌다', (await nodes(page)).length === 5, String((await nodes(page)).length));

  const [x, y] = await point(page, 'n:num');
  await page.mouse.move(x, y); await page.mouse.down(); await page.mouse.move(x + 90, y + 40, { steps: 6 }); await page.mouse.up();
  await sleep(300);
  const [x2, y2] = await point(page, 'n:num');
  step('끌면 옮겨지고 누른 것으로 치지 않는다', Math.hypot(x2 - x, y2 - y) > 40 && (await nodes(page)).length === 5, JSON.stringify([Math.round(x2 - x), Math.round(y2 - y)]));
  const before = await point(page, 'n:geo'), other = await point(page, 'n:num');
  await page.click('.kg-tools button:nth-child(2)');
  await sleep(200);
  const after = await point(page, 'n:geo'), other2 = await point(page, 'n:num');
  step('+ 로 커진다', Math.hypot(after[0] - other2[0], after[1] - other2[1]) > Math.hypot(before[0] - other[0], before[1] - other[1]) * 1.1);
  step('쪽 오류 없음', errors.length === 0, errors.join(' / ').slice(0, 300));

  await browser.close();
  console.log(`graph view: ${lines.length} steps, failed: ${failed.length}`);
  console.log(lines.join('\n'));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.log(`graph view: exception: ${e && e.stack || e}`); process.exit(2); });
