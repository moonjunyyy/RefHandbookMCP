// Layout measured, not eyeballed: on the same board as contrast.js, the places where an icon meets its
// text, where chips and buttons sit in a row, where a card's columns align — each measured as a gap and
// a vertical offset, and judged by a rule. The first line is the total (run.sh reads it); then every
// violation (pass · where · what · value), then a short table of the measured pairs for the eye.
const { chromium } = require('playwright');
const mock = require('./mock');

// Rules (px): an icon and its text are 4..12 apart (a big icon, as a card's column: up to 0.35 of its height,
// so 44px → 15, 64px → 22) and share a centre within 2; chips in a row share a
// height within 1 and a centre within 1; buttons in one .actions row share a height within 1; no text
// element is clipped by its parent; nothing in the header wraps onto a second line.
const RULES = { gapMin: 4, gapMax: 12, centre: 2, rowHeight: 1 };

const MEASURE = (rules) => {
  const out = { pairs: [], bad: [] };
  const r = (el) => el.getBoundingClientRect();
  const vis = (el) => { const b = r(el); return b.width > 0 && b.height > 0; };
  const text = (el) => (el.textContent || '').trim().slice(0, 24);
  const where = (el) => { const parts = []; for (let e = el; e && e !== document.body; e = e.parentElement) { parts.unshift(e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).join('.') : '')); if (parts.length > 3) break; } return parts.join('>'); };
  // the first element or text box to the right of the icon, on its line
  const rangeOf = (node) => { const rg = document.createRange(); rg.selectNodeContents(node); const b = rg.getBoundingClientRect(); return b; };
  for (const icon of document.querySelectorAll('.app-icon, .dot')) {
    if (!vis(icon)) continue;
    const ib = r(icon);
    let next = icon.nextSibling;
    while (next && next.nodeType === 3 && !next.textContent.trim()) next = next.nextSibling;
    if (!next) continue;
    const nb = next.nodeType === 3 ? rangeOf(next) : r(next);
    if (!nb.width) continue;
    const gap = +(nb.left - ib.right).toFixed(1);
    const dy = +(((ib.top + ib.bottom) / 2) - ((nb.top + nb.bottom) / 2)).toFixed(1);
    const label = `${where(icon.parentElement)} "${text(icon)}${next.nodeType === 3 ? next.textContent.trim().slice(0, 16) : text(next)}"`;
    out.pairs.push({ what: 'icon·text', where: label, gap, dy, iconH: +ib.height.toFixed(1), textH: +nb.height.toFixed(1) });
    const gapMax = Math.max(rules.gapMax, Math.round(ib.height * 0.35));
    if (gap < rules.gapMin || gap > gapMax) out.bad.push({ where: label, what: 'icon·text gap', value: gap });
    if (Math.abs(dy) > rules.centre) out.bad.push({ where: label, what: 'icon·text centre', value: dy });
  }
  // rows of chips, rows of buttons: same height, same centre
  for (const row of document.querySelectorAll('.chips, .actions, .section-head, .cal-nav, header nav, .note-head, .pick-row, ul.tasks > li, .vault-head')) {
    if (!vis(row)) continue;
    const kids = [...row.children].filter((k) => vis(k) && !['DIALOG'].includes(k.tagName));
    if (kids.length < 2) continue;
    const boxes = kids.map(r);
    const hs = boxes.map((b) => b.height), cs = boxes.map((b) => (b.top + b.bottom) / 2);
    const sameLine = Math.max(...boxes.map((b) => b.top)) < Math.min(...boxes.map((b) => b.bottom));
    if (!sameLine) { if (row.matches('header nav')) out.bad.push({ where: where(row), what: 'wraps', value: kids.length }); continue; }
    const dh = +(Math.max(...hs) - Math.min(...hs)).toFixed(1), dc = +(Math.max(...cs) - Math.min(...cs)).toFixed(1);
    out.pairs.push({ what: 'row', where: where(row), n: kids.length, dh, dc, hs: hs.map((h) => +h.toFixed(0)).join('/') });
    if (row.matches('.chips') && dh > rules.rowHeight) out.bad.push({ where: where(row), what: 'chip heights differ', value: dh });
    if (dc > rules.centre) out.bad.push({ where: where(row), what: 'row centres differ', value: dc });
  }
  // clipped text: a text element wider than its box, or a card column wider than the card
  for (const el of document.querySelectorAll('h1, h2, h3, a, button, .chip, .desc, .tag, .widget-head, .launcher')) {
    if (!vis(el)) continue;
    if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow !== 'visible') out.bad.push({ where: where(el), what: 'clipped', value: el.scrollWidth - el.clientWidth });
  }
  // the store card: the icon column's top aligns with the title's text top; the switch is vertically centred on the card
  for (const card of document.querySelectorAll('.store-card')) {
    const icon = card.querySelector('.app-icon'), h3 = card.querySelector('h3'), sw = card.querySelector('label.switch');
    if (!icon || !h3) continue;
    const cb = r(card), ib = r(icon), hb = r(h3);
    out.pairs.push({ what: 'card', where: `card ${card.dataset.app}`, iconTop: +(ib.top - cb.top).toFixed(1), titleTop: +(hb.top - cb.top).toFixed(1), iconH: +ib.height.toFixed(1), titleH: +hb.height.toFixed(1) });
    if (sw) { const sb = r(sw); const dc = +(((sb.top + sb.bottom) / 2) - ((cb.top + cb.bottom) / 2)).toFixed(1); if (Math.abs(dc) > 8) out.bad.push({ where: `card ${card.dataset.app}`, what: 'switch off centre', value: dc }); }
  }
  // widgets: a cell's head and body have the same left edge; the launcher's icon and name share a baseline line
  for (const w of document.querySelectorAll('.widget')) {
    const head = w.querySelector('.widget-head'), body = w.querySelector('.widget-body');
    if (head && body && vis(head) && vis(body)) { const d = +(r(head).left - r(body).left).toFixed(1); if (Math.abs(d) > 1) out.bad.push({ where: `widget ${w.dataset.app}/${w.dataset.widget}`, what: 'head/body left edge', value: d }); }
  }
  return out;
};

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx);
  mock.reset();
  mock.put('site', 'prefs', { lang: 'auto', theme: 'auto', start: '/', apps: ['eq-sandbox', 'calendar', 'vault', 'projects'],
                              home: [{ app: 'calendar', widget: 'today' }, { app: 'eq-sandbox', widget: 'boards' }, { app: 'vault', widget: 'recent' },
                                     { app: 'projects', widget: 'mine' }, { app: 'vault', widget: 'home' }, { app: 'eq-sandbox', widget: 'launcher' },
                                     { app: 'calendar', widget: 'tasks' }],
                              seen: ['eq-sandbox', 'wordgen', 'agents'] });
  mock.put('eq-sandbox', 'boards', [{ id: 'b1', title: '작업판 1', updated: Date.now() }]);
  const page = await ctx.newPage();
  const passes = [];
  const measure = async (name) => passes.push([name, await page.evaluate(MEASURE, RULES)]);
  const visit = async (p, sel) => { await page.goto(`${mock.ORIGIN}${p}`, { waitUntil: 'networkidle' }); await page.waitForSelector(sel); await page.waitForTimeout(100); };

  await visit('/calendar', '.cal-grid');
  await page.click('.cal-day.today .cal-num');
  await page.click('.cal-day-panel button:text-is("+ 일정")');
  await page.waitForSelector('dialog[open]');
  await page.fill('dialog input[name=summary]', '랩 미팅');
  await page.check('dialog label.check input');
  await page.click('dialog button:text-is("저장")');
  await page.waitForSelector('.cal-grid .cal-ev');
  await visit('/', '.widget[data-widget=home] .note-body');
  await page.waitForSelector('.widget[data-widget=today] .widget-list');
  await page.waitForSelector('.widget[data-widget=boards] .widget-list');
  await page.waitForSelector('.widget[data-widget=tasks] input[name=task]');
  await page.fill('.widget[data-widget=tasks] input[name=task]', '초록 고치기');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.widget[data-widget=tasks] ul.tasks li');
  await measure('home');
  await page.click('.widgets .widget:nth-child(2)', { button: 'right' });
  await page.waitForSelector('.menu[role=menu]');
  await measure('cell-menu');
  await page.keyboard.press('Escape');
  await page.click('.section-head button:text-is("위젯 고르기")');
  await page.waitForSelector('dialog[open] .pick-list');
  await page.hover('dialog .pick-row[data-app="calendar"][data-widget="today"]');
  await page.waitForSelector('dialog .pick-preview .widget');
  await measure('sheet');
  await page.keyboard.press('Escape');
  await visit('/apps', '.catalog .store-card');
  await measure('store');
  await visit('/app/vault', '.store-head');
  await measure('app');
  await visit('/settings', '.value');
  await measure('settings');
  await visit('/calendar', '.cal-grid');
  await page.click('.cal-day.today .cal-num');
  await page.waitForSelector('.day-list .cal-ev');
  await measure('calendar');
  await page.click('.cal-nav .chip:text-is("주")');
  await page.waitForSelector('.wk-body');
  await page.waitForTimeout(100);
  await measure('week');
  await visit('/vault', '.note-body .katex');
  await measure('notes');
  // the empty main page and the signed-out one
  mock.put('site', 'prefs', { lang: 'auto', theme: 'auto', start: '/', apps: [], home: [], seen: ['eq-sandbox', 'wordgen', 'agents'] });
  await visit('/', 'main');
  await measure('empty');
  mock.signOut();
  await visit('/', 'a.primary');
  await measure('signed-out');

  const bad = passes.flatMap(([p, m]) => m.bad.map((b) => ({ pass: p, ...b })));
  const pairs = passes.flatMap(([p, m]) => m.pairs.map((b) => ({ pass: p, ...b })));
  console.log(`layout pairs: ${pairs.length}; violations: ${bad.length}`);
  for (const b of bad) console.log(`BAD\t${b.pass}\t${b.where}\t${b.what}\t${b.value}`);
  const seen = new Set();
  for (const p of pairs) { const k = `${p.pass} ${p.what} ${p.where}`; if (seen.has(k)) continue; seen.add(k); console.log(`${p.pass}\t${p.what}\t${p.where}\t${Object.entries(p).filter(([k2]) => !['pass', 'what', 'where'].includes(k2)).map(([k2, v]) => `${k2}=${v}`).join(' ')}`); }
  await browser.close();
})();
