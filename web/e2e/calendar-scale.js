// The calendar's head, scale and room (web/src/pages/calendar.ts), in Chromium against the mock site (run.sh sets
// the roots): what is pressed keeps its place from view to view, whatever the title's length; the hours take the room
// down to the window's edge, so the whole day shows with nothing to scroll; + shows fewer hours, larger, and − goes
// back; the month shows its six weeks in that room; no scrollbar is drawn; a smaller window is fitted again.
// First line of the output: "calendar scale: N steps, failed: M".
const { chromium } = require('playwright');
const mock = require('./mock');

const BASE = mock.ORIGIN;
const lines = [], failed = [], errors = [];
const step = (name, ok, detail) => { lines.push(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`); if (!ok) failed.push(name); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pressed = (page) => page.$$eval('.cal-nav > :not(h1)', (els) => els.map((e) => Math.round(e.getBoundingClientRect().left)));
const box = (page, sel) => page.$eval(sel, (b) => ({ scroll: b.scrollHeight, client: b.clientHeight, bar: b.offsetWidth - b.clientWidth,
  bottom: Math.round(b.getBoundingClientRect().bottom), window: window.innerHeight }));
const title = (page) => page.$eval('.cal-nav h1', (e) => e.textContent.trim());

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx);
  mock.reset();
  mock.put('site', 'prefs', { apps: ['calendar'] });  // an account past its first visit: no guide over the page
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const view = async (v) => { await page.goto(`${BASE}/calendar?v=${v}&d=${today}`, { waitUntil: 'networkidle' }); await page.waitForSelector('.wk-body'); await sleep(250); };
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(`${BASE}/calendar`, { waitUntil: 'networkidle' });
  await page.waitForSelector('.cal-weeks .cal-week');
  await sleep(200);

  const month = await pressed(page), monthTitle = await title(page);
  const m = await box(page, '.cal-weeks');
  const weeks = await page.$eval('.cal-weeks', (b) => { const r = b.getBoundingClientRect(), top = r.top + b.querySelector('.cal-wds').offsetHeight;
    return [...b.querySelectorAll('.cal-week')].filter((w) => { const x = w.getBoundingClientRect(); return x.top >= top - 1 && x.bottom <= r.bottom + 1; }).length; });
  step('달: 격자가 창 아래 끝까지이고 그 안에 여섯 주가 든다', m.bottom <= m.window && m.window - m.bottom < 60 && weeks === 6, JSON.stringify({ ...m, weeks }));
  step('달: 스크롤바를 그리지 않는다', m.bar === 0, String(m.bar));

  await view('week');
  const week = await pressed(page), weekTitle = await title(page);
  const w = await box(page, '.wk-body');
  step('주: 하루 전체가 스크롤 없이 든다', w.scroll <= w.client + 1 && w.bottom <= w.window, JSON.stringify(w));
  await view('day');
  const day = await pressed(page), dayTitle = await title(page);
  step('제목의 길이는 보기마다 다르다(점검의 전제)', new Set([monthTitle.length, weekTitle.length, dayTitle.length]).size > 1, [monthTitle, weekTitle, dayTitle].join(' | '));
  step('누르는 것의 자리는 달 · 주 · 일에서 같다', JSON.stringify(month) === JSON.stringify(week) && JSON.stringify(week) === JSON.stringify(day),
    JSON.stringify([month, week, day]));

  await page.click('.cal-scale button:last-child');
  await sleep(300);
  const zoomed = await box(page, '.wk-body');
  step('+ : 시간이 커져 넘치고(스크롤로 옮긴다) 막대는 없다', zoomed.scroll > zoomed.client + 40 && zoomed.bar === 0 && zoomed.bottom <= zoomed.window, JSON.stringify(zoomed));
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForSelector('.wk-body');
  await sleep(200);
  const kept = await box(page, '.wk-body');
  step('고른 크기는 다시 열어도 남는다', kept.scroll > kept.client + 40, JSON.stringify(kept));
  await page.click('.cal-scale button:first-child');
  await sleep(300);
  const back = await box(page, '.wk-body');
  step('− : 하루 전체로 돌아오고, 더 줄일 수 없다', back.scroll <= back.client + 1 && await page.$eval('.cal-scale button:first-child', (b) => b.disabled), JSON.stringify(back));

  await page.setViewportSize({ width: 1100, height: 560 });
  await sleep(400);
  const small = await box(page, '.wk-body');
  step('창이 낮아지면 다시 맞춘다', small.scroll <= small.client + 1 && small.bottom <= small.window && small.window === 560, JSON.stringify(small));
  step('쪽 오류 없음', errors.length === 0, errors.join(' / '));

  await browser.close();
  console.log(`calendar scale: ${lines.length} steps, failed: ${failed.length}`);
  console.log(lines.join('\n'));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.log(`calendar scale: exception: ${e && e.stack || e}`); process.exit(2); });
