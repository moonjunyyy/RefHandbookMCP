// Legibility measured, not eyeballed: WCAG contrast of every visible text element against the
// background actually behind it (first non-transparent ancestor), on a board of the pages app — the
// main page (widgets of the calendar, the notes, the projects and eq-sandbox), the name menu open,
// editing, the widget dialog, the store, an app's page, the settings, the calendar with a day open, its week,
// and the event dialog, the notes read and edited, the board and a share's copy. The first line is the total (run.sh reads it);
// then the worst offenders.
const { chromium } = require('playwright');
const mock = require('./mock');

const MEASURE = (scope) => {
  const parse = (c) => { const m = /rgba?\(([\d.]+), ([\d.]+), ([\d.]+)(?:, ([\d.]+))?\)/.exec(c); return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null; };
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const blend = (top, under) => top[3] >= 1 ? top : [0, 1, 2].map((i) => Math.round(top[i] * top[3] + under[i] * (1 - top[3]))).concat([1]);
  // an SVG text's backdrop is the shape its group paints before it (a flow block's rect), not a CSS background
  const shapeUnder = (el) => {
    if (!(el instanceof SVGElement)) return null;
    for (let s = el.previousElementSibling; s; s = s.previousElementSibling) {
      const c = s.tagName === 'rect' ? parse(getComputedStyle(s).fill) : null;
      if (c && c[3] > 0) return c;
    }
    return null;
  };
  const bgOf = (el) => {
    let acc = shapeUnder(el);
    if (acc && acc[3] >= 1) return acc;
    for (let e = el.tagName === 'text' ? el.closest('svg') : el; e; e = e.parentElement) {  // an SVG's own parts have no CSS background
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c[3] > 0) { acc = acc ? blend(acc, c) : c; if (acc[3] >= 1) return acc; }
    }
    return acc ? blend(acc, [255, 255, 255, 1]) : [255, 255, 255, 1];
  };
  const root = document.querySelector(scope);
  const out = [];
  for (const el of root.querySelectorAll('*')) {
    if (el.tagName === 'INPUT' && ['checkbox', 'radio', 'range'].includes(el.type)) continue;  // no text of its own
    if (!['BUTTON', 'SPAN', 'P', 'SUMMARY', 'H1', 'H2', 'H3', 'LABEL', 'A', 'LI', 'TD', 'TH', 'KBD', 'SMALL', 'B', 'STRONG', 'EM', 'text', 'INPUT', 'OUTPUT', 'OPTION', 'SELECT', 'TEXTAREA', 'CODE', 'DIV', 'TIME'].includes(el.tagName)) continue;  // a DIV counts when it has text of its own (the grid heads)
    const text = (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ? el.value || el.placeholder : el.tagName === 'SELECT' ? el.value : el.textContent || '').trim();
    if (!text) continue;
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!own && !['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    const fg0 = parse(el.tagName === 'text' ? cs.fill : cs.color); if (!fg0) continue;
    const bg = bgOf(el);
    const fg = blend(fg0, bg);
    const l1 = lum(fg), l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const key = `${el.tagName}.${el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className}`;
    const where = r.bottom > innerHeight - 10 || r.top < 0 ? 'off' : 'on';
    out.push({ key, text: text.slice(0, 18), ratio: +ratio.toFixed(2), fg: fg.slice(0, 3).join(','), bg: bg.slice(0, 3).join(','), size: cs.fontSize, where, op: cs.opacity, disabled: !!el.disabled });
  }
  return out;
};

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR', colorScheme: process.env.SCHEME || 'light' });
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
  const measure = async (name, scope = 'body') => passes.push([name, await page.evaluate(MEASURE, scope)]);
  const menuAt = async (sel) => { await page.click(sel, { button: 'right' }); await page.waitForSelector('.menu[role=menu]'); };
  const visit = async (p, sel) => { await page.goto(`${mock.ORIGIN}${p}`, { waitUntil: 'networkidle' }); await page.waitForSelector(sel); await page.waitForTimeout(100); };

  // the main page, with every kind of widget; the name menu; editing; the widget dialog
  await visit('/calendar', '.cal-grid');  // an event for today, so the calendar's widget has a row
  await page.click('.cal-day.today');
  await page.click('.cal-day-panel button:text-is("+ 일정")');
  await page.waitForSelector('dialog[open]');
  await page.fill('dialog input[name=summary]', '랩 미팅');
  await page.check('dialog label.check input');
  await page.click('dialog button:text-is("저장")');
  await page.waitForSelector('.cal-grid .cal-ev');
  await visit('/', '.widget[data-widget=home] .note-body');
  await page.waitForSelector('.widget[data-widget=today] .today-cols');
  await page.waitForSelector('.widget[data-widget=boards] .widget-list');
  await page.waitForSelector('.widget[data-widget=tasks] input[name=task]');
  await page.fill('.widget[data-widget=tasks] input[name=task]', '초록 고치기');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.widget[data-widget=tasks] ul.tasks li');
  await page.hover('.widget[data-widget=tasks] ul.tasks li');
  await measure('home');
  // a place's settings: the dialog a widget's declared parameters make
  await page.hover('.widget[data-widget=today]');
  await page.click('.widget[data-widget=today] .widget-tools button.more');
  await page.waitForSelector('.menu[role=menu]');
  await page.click('.menu[role=menu] .menu-item:has(strong:text-is("설정"))');
  await page.waitForSelector('dialog[open] select[name=calendar]');
  await measure('widget-settings', 'dialog');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(100);
  await menuAt('.widget[data-widget=tasks] ul.tasks li');
  await measure('task-menu', '.menu[role=menu]');
  await page.keyboard.press('Escape');
  await page.click('header details.me summary');
  await page.waitForTimeout(100);
  await measure('menu', 'header details.me');
  await page.click('header details.me summary');
  await page.hover('.widgets .widget:nth-child(2)');
  await page.waitForTimeout(100);
  await measure('hovered', 'main');
  await menuAt('.widgets .widget:nth-child(2)');
  await measure('cell-menu', '.menu[role=menu]');
  await page.keyboard.press('Escape');
  await page.click('.widgets > button.add-widget');
  await page.waitForSelector('dialog[open] .pick-list');
  await page.hover('dialog .pick-row[data-app="eq-sandbox"][data-widget="boards"]');
  await page.waitForSelector('dialog .pick-preview .widget-list');
  await measure('dialog', 'dialog');
  await page.keyboard.press('Escape');
  await page.keyboard.press('?');
  await page.waitForSelector('dialog[open] ul.keys');
  await measure('keys', 'dialog');
  await page.keyboard.press('Escape');

  // the store and an app's page (one new app, so the "new" tag shows)
  await visit('/apps', '.catalog .store-card');
  await measure('store');
  await visit('/app/vault', '.store-head');
  await measure('app');
  await visit('/settings', '.value');
  await measure('settings');

  // the calendar: the grid with a day open, and the event dialog
  await visit('/calendar', '.cal-grid');
  await page.click('.cal-day.today .cal-num');  // the number: the cell's middle may be the event itself
  await page.waitForSelector('.day-list .cal-ev');
  await page.hover('.day-list .day-row');
  await measure('calendar');
  await menuAt('.day-list .cal-ev');
  await measure('event-menu', '.menu[role=menu]');
  await page.keyboard.press('Escape');
  await menuAt('.cal-sources .chip:has-text("내 캘린더")');
  await measure('cal-menu', '.menu[role=menu]');
  await page.keyboard.press('Escape');
  await page.click('.cal-sources-row button.more');
  await page.waitForSelector('.menu[role=menu]');
  await page.click('.menu[role=menu] .menu-item:has(strong:text-is("기기 연결…"))');
  await page.waitForSelector('dialog[open] form.devices-add');
  await page.fill('dialog input[name=device]', '폰');
  await page.keyboard.press('Enter');
  await page.waitForSelector('dialog .device-made input');
  await measure('devices', 'dialog');
  await page.keyboard.press('Escape');
  await page.click('.cal-nav .chip:text-is("주")');
  await page.waitForSelector('.wk-body');
  await page.waitForTimeout(100);
  await measure('week');
  await page.click('.wk-col:not(:has(.wk-ev)) >> nth=0', { position: { x: 20, y: 44 * 9 + 6 } });
  await page.waitForSelector('.peek input[name=summary]');
  await measure('quick', '.peek');
  await page.keyboard.press('Escape');
  await page.keyboard.press('d');
  await page.waitForFunction(() => document.querySelectorAll('.wk-col').length === 1);
  await measure('day');
  await page.keyboard.press('a');
  await page.waitForSelector('.cal-list .cal-list-day');
  await measure('list');
  await page.keyboard.press('y');
  await page.waitForSelector('.cal-year .month');
  await measure('year');
  await page.click('.cal-nav .chip:text-is("월")');
  await page.waitForSelector('.day-list .cal-ev');
  await page.click('.day-list .cal-ev');
  await page.waitForSelector('.peek');
  await measure('peek', '.peek');
  await page.click('.peek button:text-is("편집")');
  await page.waitForSelector('dialog[open]');
  await measure('event', 'dialog');
  await page.keyboard.press('Escape');

  // the notes: read, with a search's hits; edited
  await visit('/vault', '.note-body .katex');
  await measure('notes');
  await page.fill('.vault-side input[type=search]', 'bracket');
  await page.waitForSelector('.tree.hits');
  await measure('hits', '.vault-side');
  await page.click('.note-head label.switch input');
  await page.waitForSelector('textarea.editor');
  await measure('editor', 'main');
  await page.click('.vault-side .vault-head button.more');
  await page.waitForSelector('.menu[role=menu]');
  await measure('vault-menu', '.menu[role=menu]');
  await page.keyboard.press('Escape');
  // a vault that is not ready: the status card; the add dialog
  await page.click('.vault-side .vault-head button.more');
  await page.waitForSelector('.menu[role=menu]');
  await page.click('.menu[role=menu] .menu-item:has(strong:text-is("볼트 추가…"))');
  await page.waitForSelector('dialog[open] input[name=sub]');
  await measure('vault-add', 'dialog');
  await page.fill('dialog input[name=sub]', 'Obsidian/Nowhere');
  await page.click('dialog button:text-is("추가")');
  await page.waitForTimeout(300);
  await visit('/vault/v2', '.vault-status');
  await measure('vault-status', 'main');
  // a run's page with its branches (agents/branches.py): the merged, kept and unchanged tags
  await visit('/agents/runs/run:b1', 'ul.branches');
  await measure('run-branches', 'main');

  // the public board: the notices, a hidden share's card as an administrator sees it, a share's copy
  mock.boardAdmin(true);
  Object.assign(mock.board().shares[0], { hidden: true, hidden_why: '확인 중' });
  await visit('/board', '.notice');
  await measure('board', 'main');
  await page.click('[data-share=s1] h3 button');
  await page.waitForSelector('dialog[open] .flow-canvas');
  await measure('share', 'dialog');
  await page.keyboard.press('Escape');
  mock.boardAdmin(false);

  // disabled controls are allowed to be dim (WCAG exempts them); everything else must reach 4.5:1
  const all = passes.flatMap(([pass, rows]) => rows.filter((r) => r.where === 'on' && !r.disabled).map((r) => ({ ...r, pass })));
  const bad = all.filter((r) => r.ratio < 4.5);
  console.log(`visible text elements: ${all.length} (${passes.map(([p, rows]) => `${p} ${rows.filter((r) => r.where === 'on' && !r.disabled).length}`).join(', ')}); below 4.5:1: ${bad.length}; min: ${Math.min(...all.map((r) => r.ratio))}`);
  const byKey = new Map();
  for (const r of all) { const k = `${r.pass} ${r.key}`; if (!byKey.has(k) || byKey.get(k).ratio > r.ratio) byKey.set(k, r); }
  for (const r of [...byKey.values()].sort((a, b) => a.ratio - b.ratio).slice(0, 12)) console.log(`${r.ratio}\t${r.pass}\t${r.key}\t"${r.text}"\tfg ${r.fg} bg ${r.bg} ${r.size}`);
  await browser.close();
})();
