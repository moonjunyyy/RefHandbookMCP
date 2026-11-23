// The pages at tall and narrow windows, counted rather than eyeballed (run.sh sets the roots): a page wider than its
// window, an element that reaches past the window's right edge (outside anything that scrolls or clips sideways), a
// month whose days are taller than the style sheet lets them be (parts.css --cal-day-tall), a grid that leaves the
// window's lower part unused. First line: "responsive: N pages at windows, violations: M"; then each violation
// (BAD · window · page · what · value) and, for the eye, the month's and the hours' measures at each window.
const { chromium } = require('playwright');
const mock = require('./mock');
const LINES = require('./lines');

const BASE = mock.ORIGIN;
const WINDOWS = [[390, 844], [820, 1180], [1080, 1920], [1100, 820]];
const PAGES = [['/', '.widgets'], ['/calendar', '.cal-weeks .cal-week'], ['/calendar?v=week', '.wk-body'], ['/vault', '.note-body'], ['/board', 'main h1'],
               ['/handbook', '.kg-canvas[data-nodes]'], ['/apps', '.catalog .store-card .app-tools'], ['/settings', '.value'], ['/projects', 'main h1']];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const MEASURE = () => {
  const w = document.documentElement.clientWidth, bad = [], note = [];
  const where = (el) => el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim() ? '.' + el.className.trim().split(/\s+/).join('.') : '');
  if (document.documentElement.scrollWidth > w + 1) bad.push(['the page is wider than the window', `${document.documentElement.scrollWidth} > ${w}`]);
  const past = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0 && b.right > w + 1; };
  for (const el of document.querySelectorAll('body *')) {
    if (!past(el) || (el.parentElement && past(el.parentElement))) continue;  // the outermost one says it
    const cs = getComputedStyle(el);
    if (cs.position === 'fixed' || cs.visibility === 'hidden') continue;
    let inside = false;  // inside something that scrolls or clips sideways it may reach past: that is the scroller's business
    for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) if (getComputedStyle(p).overflowX !== 'visible') { inside = true; break; }
    if (!inside) bad.push(['reaches past the right edge', `${where(el)} ${Math.round(el.getBoundingClientRect().right)} > ${w}`]);
  }
  const weeks = document.querySelector('.cal-weeks');
  if (weeks && weeks.querySelector('.cal-day')) {
    const tall = Number.parseFloat(getComputedStyle(weeks).getPropertyValue('--cal-day-tall'));
    const ratios = [...weeks.querySelectorAll('.cal-day')].slice(0, 42).map((d) => { const b = d.getBoundingClientRect(); return b.height / b.width; }).sort((a, b) => a - b);
    const mid = ratios[Math.floor(ratios.length / 2)], b = weeks.getBoundingClientRect();
    note.push(`month: a day is ${mid.toFixed(2)} times as tall as wide (may be ${tall}); ${Math.round(b.height / (weeks.querySelector('.cal-day').getBoundingClientRect().height + 1))} weeks in sight`);
    if (!(tall > 0) || mid > tall + .03) bad.push(['a day of the month is taller than it may be', `${mid.toFixed(2)} > ${tall}`]);  // the middle one: a day with many events grows by itself
    if (window.innerHeight - b.bottom > 60) bad.push(['the month leaves the window unused below', `${Math.round(window.innerHeight - b.bottom)}px`]);
  }
  const hours = document.querySelector('.wk-body');
  if (hours && hours.offsetHeight) {
    const line = hours.querySelector('.wk-line'), col = hours.querySelector('.wk-col');
    if (line && col) note.push(`hours: an hour is ${Math.round(line.getBoundingClientRect().height)}px tall, a day ${Math.round(col.getBoundingClientRect().width)}px wide`);
  }
  return { bad, note };
};

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const bad = [], notes = [], errors = [];
  let seen = 0;
  for (const [width, height] of WINDOWS) {
    const ctx = await browser.newContext({ viewport: { width, height }, locale: 'ko-KR' });
    await mock.install(ctx);
    mock.reset();
    mock.put('site', 'prefs', { apps: ['projects', 'calendar', 'vault', 'board', 'refhandbook'] });  // an account past its first visit: no guide over the page
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(`${width}x${height} ${String(e)}`));
    const measure = async (name) => {
      seen++;
      const m = await page.evaluate(MEASURE);
      for (const [where, word] of await page.evaluate(LINES)) m.bad.push(['a line ends inside a word', `${where} ${word}`]);
      for (const [what, value] of m.bad) bad.push(`BAD\t${width}x${height}\t${name}\t${what}\t${value}`);
      for (const n of m.note) notes.push(`${width}x${height}\t${name}\t${n}`);
    };
    for (const [path, ready] of PAGES) {
      await page.goto(BASE + path, { waitUntil: 'networkidle' });
      await page.waitForSelector(ready, { timeout: 8000 }).catch(() => bad.push(`BAD\t${width}x${height}\t${path}\tthe page did not draw\t${ready}`));
      await sleep(250);
      await measure(path);
    }
    await ctx.close();
  }
  await browser.close();
  for (const e of errors) bad.push(`BAD\t-\t-\tpage error\t${e.slice(0, 200)}`);
  console.log(`responsive: ${seen} pages at windows, violations: ${bad.length}`);
  console.log(bad.join('\n'));
  console.log(notes.join('\n'));
  process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.log(`responsive: exception: ${e && e.stack || e}`); process.exit(2); });
