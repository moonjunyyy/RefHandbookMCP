// C7 measurement (docs/frame.md §7, docs/apps-vault-calendar.md §5): Chromium against the mock site. The
// main page with nothing on is one action, which goes to the store (cards, chips, an app's page); turning
// an app on puts it in the header and on the main page; the widget module runs (eq-sandbox's recent
// boards); editing reorders by drag and by keyboard and removes; the calendar writes, shows, hides and
// removes an event, moves one by dragging it onto another day (and, in the week, another hour), opens a
// slot of the week as a new event and offers a subscription address; the notes page renders a vault's Home (wikilinks,
// mathematics), edits it in place, refuses a stale save, searches; the widgets of the calendar, the
// notes and the projects draw on the main page; the theme changes at once and survives a reload; an
// app's own page gets the same theme and header; an old account (hidden/order) wakes up with its apps on.
// 5차 (docs/apps-vault-calendar.md §7.7, C22–C27): a new account starts with the calendar, the projects and
// the notes on, and an account that turned everything off stays empty; the widget sheet is rows with a
// switch, a description and a size, kept as switched; a cell's menu moves and removes; the calendar's
// events, days and chips have menus (duplicate, move to another calendar, delete; new event; rename, new
// calendar, delete with the name typed); the to-do list is written and checked in place, on the main page
// and in the day panel; a vault is added inside an offered root, refused with a reason, shown as a status
// card with a retry, renamed, taken off; a note is renamed from its menu. 6차 (§8, C29–C34): no edit mode —
// a widget is moved by its head and resized by its corner grip (snapping to the declared sizes), its ⋯ offers the
// sizes; the sheet draws the pointed-at widget beside the list; the note's body is drawn before the backlinks
// answer, KaTeX is fetched only for a note with mathematics, a wide table scrolls inside the note; a device
// password is made for CalDAV; Enter confirms a dialog from a select; each page's keys work and ? lists them;
// the default apps and the sizes come from /me. Page errors and console errors must be 0.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const mock = require('./mock');
const BASE = mock.ORIGIN;
const OUT = path.join(__dirname, 'out');
fs.mkdirSync(OUT, { recursive: true });

const report = { steps: [], pageErrors: [], consoleErrors: [], failed: [] };
let allowed = 0;  // a status the scenario provokes on purpose (the stale save's 412): not an error then
const step = (name, ok, detail) => { report.steps.push({ name, ok, detail }); console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`); if (!ok) report.failed.push(name); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const shot = (page, name) => page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
const texts = (page, sel) => page.$$eval(sel, (els) => els.map((e) => e.textContent.trim()));
const theme = (page) => page.evaluate(() => document.documentElement.getAttribute('data-theme'));
const bg = (page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
const cells = (page) => page.$$eval('.widgets .widget', (els) => els.map((e) => `${e.dataset.app}/${e.dataset.widget}`));
const navApps = (page) => page.$$eval('header nav > a', (as) => as.map((a) => a.textContent.trim()));
const cards = (page) => page.$$eval('.catalog .store-card', (r) => r.map((e) => e.dataset.app));
const menuItems = (page) => texts(page, '.menu[role=menu] .menu-item strong');
const menuOf = async (page, sel) => { await page.click(sel, { button: 'right' }); await page.waitForSelector('.menu[role=menu]'); };
const pickItem = async (page, label) => { await page.click(`.menu[role=menu] .menu-item:has(strong:text-is("${label}"))`); await sleep(300); };

async function open(page, url, waitFor) {
  await page.goto(url, { waitUntil: 'networkidle' });
  if (waitFor) await page.waitForSelector(waitFor);
  await sleep(150);
}

function watch(page) {
  page.on('pageerror', (e) => report.pageErrors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !(allowed && m.text().includes(String(allowed)))) report.consoleErrors.push(m.text()); });
  page.on('response', (r) => { if (r.status() >= 400 && r.status() !== allowed) report.consoleErrors.push(`${r.status()} ${r.url()}`); });
}

async function run() {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx);
  mock.reset();
  const page = await ctx.newPage();
  watch(page);

  // (a0) a new account (no settings kept): the calendar, the projects and the notes are on — three launchers, three apps in the header (C22)
  await open(page, `${BASE}/`, '.widgets');
  step('새 계정은 사이트 파일이 default 로 표시한 앱(프로젝트·캘린더·노트, 그 순)이 켜진 채 시작한다 (C34)', JSON.stringify(await cells(page)) === '["projects/launcher","calendar/launcher","vault/launcher"]' && (await navApps(page)).length === 3, JSON.stringify(await cells(page)));
  step('켜진 것은 아직 저장되지 않았다(설정 없음 = 기본)', mock.get('site', 'prefs') === undefined);
  mock.put('site', 'prefs', { apps: [] });
  // (a) an account that turned everything off: the main page is one action, which goes to the store; the header holds only the person's menu
  await open(page, `${BASE}/`, 'main a.primary');
  step('다 끈 계정은 빈 채로 남는다(apps: [] 는 선택)', !(await page.$('.widgets')));
  step("빈 홈은 가게가 아니라 '앱 추가' 하나다", !(await page.$('.catalog')) && !(await page.$('.store-card')) && !(await page.$('.widgets'))
    && (await texts(page, 'main a.primary')).join() === '앱 추가' && (await page.$eval('main a.primary', (a) => a.getAttribute('href'))) === '/apps', (await texts(page, 'main')).join('|').slice(0, 80));
  step('홈에 인사·설명·버튼형 링크가 없다', !(await page.$('.hero')) && !(await page.$('main a.button')) && !(await page.$('main p.lead')) && !(await page.$('main p.muted')));
  step('헤더에 켠 앱이 없고 이름 메뉴만 있다', (await navApps(page)).length === 0 && !!(await page.$('header details.me')));
  await shot(page, 'a-empty');
  await page.click('main a.primary');
  await page.waitForSelector('.catalog .store-card');
  step("'앱 추가'는 가게(/apps)로 간다: 검색 + 칩 + 카드", page.url().endsWith('/apps') && !!(await page.$('.catalog input[type=search]')) && (await page.$$('.catalog .chips button.chip')).length >= 3 && (await cards(page)).length === 6, `${page.url()} cards ${(await cards(page)).length}`);
  step('계정은 가게의 카드가 아니라 이름 메뉴 안이다', !(await page.$('.catalog [data-app=account]')) && (await texts(page, 'header details.me div a')).includes('계정'));

  // (b) the store: a card says name, line and tags; the switch keeps at once; the chips pick a view
  step('카드는 아이콘·이름 링크·한 줄·태그를 말한다', (await texts(page, '.catalog [data-app=calendar] .desc'))[0] === '내 일정과 프로젝트 일정을 한 달력에'
    && (await texts(page, '.catalog [data-app=calendar] .tags .tag')).join() === '일정' && (await page.$eval('.catalog [data-app=calendar] h3 a', (a) => a.getAttribute('href'))) === '/app/calendar');
  await page.click('.catalog [data-app=eq-sandbox] label.switch input');
  await sleep(300);
  step('스위치로 켜면 저장된다', JSON.stringify(mock.get('site', 'prefs') && mock.get('site', 'prefs').apps) === '["eq-sandbox"]', JSON.stringify(mock.get('site', 'prefs')));
  await open(page, `${BASE}/`, '.widgets');
  step('켠 앱의 위젯이 홈에 보인다(기본 = 실행기)', JSON.stringify(await cells(page)) === '["eq-sandbox/launcher"]', JSON.stringify(await cells(page)));
  step('헤더에 켠 앱이 나타난다', JSON.stringify(await navApps(page)) === '["🧮수식 플립플롭"]', JSON.stringify(await navApps(page)));
  await open(page, `${BASE}/apps`, '.catalog');
  await page.click('.catalog [data-app=wordgen] label.switch input');
  await sleep(200);
  await page.click('.catalog [data-app=agents] label.switch input');
  await sleep(200);
  step('카드의 순서는 사이트 파일의 순서다', JSON.stringify(await cards(page)) === '["projects","calendar","vault","eq-sandbox","wordgen","agents"]', JSON.stringify(await cards(page)));
  await page.click('.catalog .chips button.chip:text-is("내 앱")');
  await sleep(100);
  step("'내 앱' 칩은 켠 것만, 켠 순서로", JSON.stringify(await cards(page)) === '["eq-sandbox","wordgen","agents"]' && page.url().endsWith('?tag=mine'), `${JSON.stringify(await cards(page))} ${page.url()}`);
  await page.click('.catalog .chips button.chip:text-is("일정")');
  await sleep(100);
  step('태그 칩은 그 갈래만', JSON.stringify(await cards(page)) === '["calendar"]');
  await page.click('.catalog .chips button.chip:text-is("전체")');
  await page.fill('.catalog input[type=search]', '글');
  await sleep(100);
  step('검색이 카드를 거르고 주소에 남는다', JSON.stringify(await cards(page)) === '["vault","wordgen"]' && page.url().includes('q=%EA%B8%80'), `${JSON.stringify(await cards(page))} ${page.url()}`);
  await shot(page, 'b-store');
  await open(page, `${BASE}/app/calendar`, '.store-head');
  step('앱 페이지: 이름·한 줄·스위치·소개·위젯·링크', (await texts(page, '.store-head h1'))[0] === '캘린더' && !!(await page.$('.store-head label.switch')) && (await texts(page, 'main .about'))[0].startsWith('내 캘린더와')
    && (await texts(page, 'main ul.plain li')).join('|').includes('오늘') && !(await page.$('main a.primary')), (await texts(page, 'main ul.plain li')).join('|'));
  await page.click('.store-head label.switch input');
  await sleep(300);
  step("앱 페이지에서 켜면 '열기'가 첫 행동이 된다", (await texts(page, 'main a.primary')).join() === '열기' && mock.get('site', 'prefs').apps.includes('calendar'));
  await shot(page, 'b-app');

  // (c) the widget module: eq-sandbox's recent boards, from its own store
  mock.put('eq-sandbox', 'boards', [{ id: 'b1', title: '작업판 1', updated: Date.now() - 1000 }, { id: 'b2', title: '작업판 2', updated: Date.now() }]);
  await open(page, `${BASE}/`, '.widgets');
  step("편집 모드가 없다: 머리의 도구는 '위젯 고르기' 하나 (C29)", !(await page.$('.section-head button:text-is("편집")')) && !!(await page.$('.section-head button:text-is("위젯 고르기")')));
  await page.keyboard.press('w');
  await page.waitForSelector('dialog[open] .pick-list');
  const rows = await page.$$eval('dialog .pick-row', (els) => els.map((e) => ({ app: e.dataset.app, w: e.dataset.widget, title: e.querySelector('.pick-title').textContent, desc: e.querySelector('.pick-desc').textContent, size: e.querySelector('.tag.size').textContent, h: e.getBoundingClientRect().height, on: e.querySelector('input').checked })));
  step('w 가 시트를 열고, 앱별 행마다 스위치·이름·설명·크기(cols×rows)다 (C24·C34)', rows.length === 8 && rows.every((r) => r.title && r.desc && r.size) && rows.filter((r) => r.w === 'launcher').length === 4
    && rows.find((r) => r.w === 'tasks').desc.startsWith('체크리스트') && rows.find((r) => r.w === 'today').size === '2×1' && rows.filter((r) => r.on).length === 4, JSON.stringify(rows.map((r) => [r.app, r.w, r.size, r.on])));
  step('행은 44px 를 넘지 않는다', rows.every((r) => r.h <= 44), JSON.stringify(rows.map((r) => Math.round(r.h))));
  await page.hover('dialog .pick-row[data-app="eq-sandbox"][data-widget="boards"]');
  await page.waitForSelector('dialog .pick-preview .widget[data-widget=boards] .widget-list li');
  step('행을 짚으면 옆에 그 위젯이 실제로 뜬다 (C30)', (await texts(page, 'dialog .pick-preview .widget-list li a')).join() === '작업판 2,작업판 1' && (await texts(page, 'dialog .pick-preview-title')).join().includes('1×1'));
  await page.hover('dialog .pick-row[data-app="wordgen"][data-widget="launcher"]');
  await sleep(400);
  step('다른 행을 짚으면 그것만 남는다', !!(await page.$('dialog .pick-preview .widget[data-app=wordgen] .launcher')) && !(await page.$('dialog .pick-preview .widget[data-widget=boards]')));
  await page.click('dialog .pick-row[data-app="eq-sandbox"][data-widget="boards"] input');
  await sleep(300);
  step('스위치를 켜면 바로 저장되고 칸이 생긴다', (await cells(page)).includes('eq-sandbox/boards') && mock.get('site', 'prefs').home.some((p) => p.widget === 'boards') && (await page.$$('dialog[open]')).length === 1);
  await page.keyboard.press('Escape');
  await sleep(200);
  step('Esc 가 시트를 닫는다 (C33)', !(await page.$('dialog[open]')));
  await page.waitForSelector('.widget[data-widget=boards] .widget-list');
  const items = await texts(page, '.widget[data-widget=boards] .widget-list li a');
  step('위젯 모듈이 돌아 앱의 저장소를 보인다', JSON.stringify(items) === '["작업판 2","작업판 1"]', JSON.stringify(items));
  step('위젯 머리는 앱 이름 링크와 위젯 이름이다', (await texts(page, '.widget[data-widget=boards] .widget-head'))[0].includes('수식 플립플롭') && (await texts(page, '.widget[data-widget=boards] .widget-head'))[0].includes('최근 작업판'));
  step('배치가 저장되었다', JSON.stringify(mock.get('site', 'prefs').home) === '[{"app":"eq-sandbox","widget":"launcher"},{"app":"wordgen","widget":"launcher"},{"app":"agents","widget":"launcher"},{"app":"calendar","widget":"launcher"},{"app":"eq-sandbox","widget":"boards"}]', JSON.stringify(mock.get('site', 'prefs').home));
  await shot(page, 'c-widgets');

  // (d) in place: keyboard move, remove, a drag by the head, a resize by the grip and by the menu
  await page.focus('.widgets .widget:nth-child(5)');
  await page.keyboard.press('Alt+ArrowLeft');
  await sleep(300);
  step('Alt+← 로 칸이 앞으로 간다', (await cells(page))[3] === 'eq-sandbox/boards', JSON.stringify(await cells(page)));
  await page.focus('.widgets .widget:nth-child(2)');
  await page.keyboard.press('Delete');
  await sleep(300);
  step('Delete 로 칸이 빠진다', JSON.stringify(await cells(page)) === '["eq-sandbox/launcher","agents/launcher","eq-sandbox/boards","calendar/launcher"]', JSON.stringify(await cells(page)));
  step('칸의 머리가 손잡이다(실행기는 칸)', (await page.$eval('.widgets .widget:nth-child(3) .widget-head', (e) => e.getAttribute('draggable'))) === 'true'
    && (await page.$eval('.widgets .widget:nth-child(1)', (e) => e.getAttribute('draggable'))) === 'true');
  const from = await (await page.$('.widgets .widget:nth-child(3) .widget-head')).boundingBox();
  const to = await (await page.$('.widgets .widget:nth-child(1)')).boundingBox();
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + 20, to.y + 20, { steps: 8 });
  await page.mouse.move(to.x + 30, to.y + 30, { steps: 4 });
  await page.mouse.up();
  await sleep(400);
  const dragged = JSON.stringify(await cells(page)) === '["eq-sandbox/boards","eq-sandbox/launcher","agents/launcher","calendar/launcher"]';
  step('머리를 끌어 순서를 바꾼다 (C29)', dragged, JSON.stringify(await cells(page)));
  // the cell's menu (C23·C29): by keyboard (Shift+F10) and by its ⋯; the sizes as declared, then move and remove
  await page.focus('.widgets .widget:nth-child(2)');
  await page.keyboard.press('Shift+F10');
  await page.waitForSelector('.menu[role=menu]');
  step('칸의 메뉴가 키보드로 열리고 크기 넷·앞으로·뒤로·빼기다', JSON.stringify(await menuItems(page)) === '["1×1","2×1","1×2","2×2","앞으로","뒤로","빼기"]' && (await page.evaluate(() => document.activeElement.classList.contains('menu-item'))), JSON.stringify(await menuItems(page)));
  await page.keyboard.press('Escape');
  await sleep(100);
  step('Esc 로 닫히고 초점이 칸으로 돌아온다', !(await page.$('.menu[role=menu]')) && (await page.evaluate(() => document.activeElement.classList.contains('widget'))));
  await page.hover('.widgets .widget:nth-child(2)');
  await page.click('.widgets .widget:nth-child(2) .widget-tools button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '1×2');
  step('메뉴의 크기로 칸이 커지고 배치에 남는다', mock.get('site', 'prefs').home[1].size === '1x2' && (await page.$eval('.widgets .widget:nth-child(2)', (e) => e.style.gridRow)) === 'span 2', JSON.stringify(mock.get('site', 'prefs').home));
  // the grip: dragged one column to the right, the cell snaps to 2×2 (the nearest declared size with its 2 rows)
  await page.hover('.widgets .widget:nth-child(2)');
  const g = await (await page.$('.widgets .widget:nth-child(2) .widget-grip')).boundingBox();
  const c2 = await (await page.$('.widgets .widget:nth-child(2)')).boundingBox();
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
  await page.mouse.down();
  await page.mouse.move(g.x + c2.width + 20, g.y, { steps: 6 });
  await page.mouse.up();
  await sleep(400);
  step('모서리를 끌면 가장 가까운 선언 크기로 스냅되어 저장된다 (C29)', mock.get('site', 'prefs').home[1].size === '2x2' && (await page.$eval('.widgets .widget:nth-child(2)', (e) => e.style.gridColumn)) === 'span 2', JSON.stringify(mock.get('site', 'prefs').home[1]));
  await page.hover('.widgets .widget:nth-child(3)');
  await page.click('.widgets .widget:nth-child(3) .widget-tools button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '빼기');
  step('⋯ 메뉴의 빼기로 칸이 빠진다', JSON.stringify(await cells(page)) === '["eq-sandbox/boards","eq-sandbox/launcher","calendar/launcher"]', JSON.stringify(await cells(page)));
  await shot(page, 'd-edited');

  // (e) the calendar: the grid, a day, an event written, shown, hidden with its calendar, removed; the subscription
  await open(page, `${BASE}/calendar`, '.cal-grid');
  // the page's keys (C33): t = today, m/w = the view, ? = the list
  await page.keyboard.press('w');
  await page.waitForSelector('.wk-body');
  step('w 가 주 보기로 간다 (C33)', (await page.$$('.wk-col')).length === 7);
  await page.keyboard.press('m');
  await page.waitForSelector('.cal-grid .cal-day');
  await page.keyboard.press('?');
  await page.waitForSelector('dialog[open] ul.keys');
  step('? 가 이 페이지의 키 목록을 보인다(선언 6 + 목록 1)', (await page.$$('dialog ul.keys li')).length === 7 && (await texts(page, 'dialog ul.keys li span')).includes('오늘'), JSON.stringify(await texts(page, 'dialog ul.keys li')));
  await page.keyboard.press('Escape');
  await sleep(150);
  step('캘린더의 첫 요소는 달력이고 머리 한 줄이다', (await page.$$('.cal-grid .cal-day')).length === 42 && (await page.$$('.cal-sources .chip')).length === 2 && !(await page.$('main p.muted')));
  await page.click('.cal-day.today');
  await page.waitForSelector('.cal-day-panel h2');
  const todayKey = await page.$eval('.cal-day.today', (e) => e.dataset.day);
  step('날을 누르면 그 날이 아래 열린다', (await page.$$('.cal-day.selected')).length === 1 && page.url().includes(`?d=${todayKey}`));
  await page.click('.cal-day-panel button:text-is("+ 일정")');
  await page.waitForSelector('dialog[open]');
  await page.fill('dialog input[name=summary]', '치과');
  await page.fill('dialog input[type=datetime-local] >> nth=0', `${todayKey}T10:00`);
  await page.fill('dialog input[type=datetime-local] >> nth=1', `${todayKey}T11:00`);
  await page.click('dialog button:text-is("저장")');
  await page.waitForSelector('.cal-grid .cal-ev');
  step('일정을 쓰면 격자와 그 날에 보이고 저장된다', (await texts(page, '.cal-day.selected .cal-ev .cal-title')).includes('치과') && (await texts(page, '.day-list .cal-ev')).some((x) => x.includes('치과'))
    && mock.events().length === 1 && mock.events()[0].cal === 'u-1' && /Z$/.test(mock.events()[0].start), JSON.stringify(mock.events()));
  await page.keyboard.press('n');
  await page.waitForSelector('dialog[open]');
  await page.fill('dialog input[name=summary]', '랩 미팅');
  await page.selectOption('dialog select[name=cal]', 'g-1');
  await page.check('dialog label.check input');
  await page.fill('dialog input[type=date] >> nth=0', todayKey);
  await page.fill('dialog input[type=date] >> nth=1', todayKey);
  await page.focus('dialog select[name=cal]');
  await page.keyboard.press('Enter');  // the focus is on a select: Enter still confirms (C33)
  await sleep(300);
  step('n 이 새 일정이고, select 에 초점을 둔 채 Enter 로 저장된다; 종일 일정은 날짜로 저장된다 (C33)', mock.events().length === 2 && mock.events()[1].allday && /^\d{4}-\d{2}-\d{2}$/.test(mock.events()[1].start) && (await page.$$('.cal-day.selected .cal-ev')).length === 2, JSON.stringify(mock.events()[1]));
  await page.click('.cal-sources .chip:has-text("lab")');
  await sleep(200);
  step('캘린더 칩을 끄면 그 일정이 숨는다(이 브라우저에 기억)', (await page.$$('.cal-day.selected .cal-ev')).length === 1 && (await page.evaluate(() => localStorage.getItem('cal.hidden'))) === '["g-1"]');
  await page.click('.cal-sources .chip:has-text("lab")');
  await page.click('.day-list .cal-ev:has-text("치과")');
  await page.waitForSelector('dialog[open]');
  step('일정을 누르면 같은 대화상자에 그 값이 있다', (await page.inputValue('dialog input[name=summary]')) === '치과');
  await page.click('dialog p.actions button:text-is("지우기")');
  await page.waitForSelector('dialog[open] h2:text-is("일정 지우기")');
  await page.click('dialog[open] button[type=submit].danger');
  await sleep(300);
  step('지우기는 두 걸음이고 그 뒤 사라진다', mock.events().length === 1 && !(await texts(page, '.cal-grid .cal-ev')).some((x) => x.includes('치과')));
  await page.click('.cal-sources-row button.more');
  await page.waitForSelector('.menu[role=menu]');
  step('캘린더 줄의 ⋯ 는 새 캘린더·모두 보이기·폰에 구독·기기 연결이다', JSON.stringify(await menuItems(page)) === '["새 캘린더…","모두 보이기","폰에 구독","기기 연결…"]', JSON.stringify(await menuItems(page)));
  await pickItem(page, '기기 연결…');
  await page.waitForSelector('dialog[open] form.devices-add');
  step('기기 연결: 서버 주소와 사용자명이 적혀 있다 (C32)', (await page.inputValue('dialog input[readonly] >> nth=0')).endsWith('/calendar/dav/') && (await page.inputValue('dialog input[readonly] >> nth=1')) === 'tester');
  await page.fill('dialog input[name=device]', '폰');
  await page.keyboard.press('Enter');
  await page.waitForSelector('dialog .device-made input');
  step('기기 이름 + Enter 로 비밀번호가 한 번 보인다', (await page.inputValue('dialog .device-made input')).startsWith('pw-') && mock.devices().length === 1 && (await texts(page, 'dialog ul.devices li .text')).join() === '폰');
  await page.click('dialog ul.devices li button:text-is("거두기")');
  await sleep(300);
  step('거두기로 기기가 빠진다', mock.devices().length === 0 && (await texts(page, 'dialog ul.devices li')).join().includes('없습니다'));
  await page.keyboard.press('Escape');
  await sleep(150);
  await page.click('.cal-sources-row button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '폰에 구독');
  await page.waitForSelector('dialog[open]');
  step('구독 주소는 대화상자 하나로 만들어 보인다', (await page.inputValue('dialog input[readonly]')).includes('/calendar/feed/'));
  await page.keyboard.press('Escape');
  await sleep(200);
  // (e1) the event's menu (C25): duplicate, move to another calendar, delete in two steps
  await menuOf(page, '.day-list .cal-ev:has-text("랩 미팅")');
  step('일정의 우클릭 메뉴: 열기·복제·옮기기·복사·지우기', JSON.stringify(await menuItems(page)) === '["열기","복제","다른 캘린더로 옮기기…","다른 캘린더에 복사…","지우기"]', JSON.stringify(await menuItems(page)));
  await pickItem(page, '복제');
  step('복제하면 같은 날에 하나 더 생긴다', mock.events().length === 2 && (await page.$$('.day-list .cal-ev')).length === 2, JSON.stringify(mock.events().map((e) => e.summary)));
  await page.hover('.day-list .day-row:nth-child(2)');
  await page.click('.day-list .day-row:nth-child(2) button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '지우기');
  await page.waitForSelector('dialog[open] h2:text-is("일정 지우기")');
  await page.click('dialog[open] button[type=submit].danger');
  await sleep(300);
  step('행의 ⋯ 에서 지우기는 두 걸음이다', mock.events().length === 1 && (await page.$$('.day-list .cal-ev')).length === 1);
  await menuOf(page, '.day-list .cal-ev');
  await pickItem(page, '다른 캘린더로 옮기기…');
  await page.waitForSelector('dialog[open] select[name=cal]');
  await page.selectOption('dialog select[name=cal]', 'u-1');
  await page.click('dialog button:text-is("옮기기")');
  await sleep(300);
  step('다른 캘린더로 옮기면 그 캘린더의 것이 된다', mock.events()[0].cal === 'u-1' && (await texts(page, '.day-list .cal-ev .muted')).join().includes('내 캘린더'), JSON.stringify(mock.events()[0]));
  // the day's menu, on the grid and in the panel's head
  await menuOf(page, '.cal-day.today .cal-num');
  step('날의 우클릭 메뉴: 새 일정·종일 일정·이 주 보기', JSON.stringify(await menuItems(page)) === '["새 일정","종일 일정","이 주 보기"]', JSON.stringify(await menuItems(page)));
  await page.keyboard.press('Escape');
  await page.click('.cal-day-panel .section-head button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '종일 일정');
  await page.waitForSelector('dialog[open]');
  step("'종일 일정'은 종일이 켜진 새 일정이다", (await page.isChecked('dialog label.check input')) && (await page.inputValue('dialog input[type=date] >> nth=0')) === todayKey);
  await page.keyboard.press('Escape');
  await sleep(200);
  // (e2) the calendar chip's menu (C25): rename, hide, its own address; a new calendar; deleted with its name typed
  await menuOf(page, '.cal-sources .chip:has-text("lab")');
  step('캘린더 칩의 메뉴: 숨기기·이것만·이름·색·구독 주소·지우기', JSON.stringify(await menuItems(page)) === '["숨기기","이것만 보기","이름·색 바꾸기…","구독 주소…","지우기"]'
    && (await texts(page, '.menu[role=menu] .menu-item .detail')).some((d) => d.includes('프로젝트 lab')), JSON.stringify(await menuItems(page)));
  await pickItem(page, '이름·색 바꾸기…');
  await page.waitForSelector('dialog[open] input[name=name]');
  await page.fill('dialog input[name=name]', 'Lab 2');
  await page.click('dialog button:text-is("저장")');
  await sleep(300);
  step('이름을 바꾸면 칩과 저장이 바뀐다', (await texts(page, '.cal-sources .chip')).includes('Lab 2') && mock.calendars()[1].name === 'Lab 2');
  await page.click('.cal-sources-row button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '새 캘린더…');
  await page.waitForSelector('dialog[open] input[name=name]');
  await page.fill('dialog input[name=name]', '개인');
  step('새 캘린더는 내 것이거나 프로젝트의 것이다', (await texts(page, 'dialog select[name=group] option')).join() === '내 것,프로젝트 lab');
  await page.click('dialog button:text-is("저장")');
  await sleep(300);
  step('새 캘린더가 칩으로 선다', (await page.$$('.cal-sources .chip')).length === 3 && mock.calendars().length === 3);
  await menuOf(page, '.cal-sources .chip:has-text("개인")');
  await pickItem(page, '지우기');
  await page.waitForSelector('dialog[open] h2:text-is("캘린더 지우기")');
  step('캘린더 지우기는 이름을 받아 적어야 한다', (await page.$eval('dialog[open] button[type=submit]', (b) => b.disabled)));
  await page.fill('dialog[open] input[type=text]', '개인');
  await page.click('dialog[open] button[type=submit]');
  await sleep(300);
  step('이름을 적으면 지워진다; 기본 캘린더의 지우기는 비활성', (await page.$$('.cal-sources .chip')).length === 2 && mock.calendars().length === 2);
  await menuOf(page, '.cal-sources .chip:has-text("내 캘린더")');
  step('기본 캘린더의 지우기는 비활성이고 이유를 말한다', (await page.$eval('.menu[role=menu] .menu-item.danger', (b) => b.disabled)) && (await texts(page, '.menu[role=menu] .menu-item.danger .detail')).join().includes('남습니다'));
  await pickItem(page, '구독 주소…');
  await page.waitForSelector('dialog[open] input[readonly]');
  step('캘린더 하나만의 구독 주소가 따로 난다', (await page.inputValue('dialog input[readonly]')).includes('/calendar/feed/') && (await texts(page, 'dialog h2'))[0].includes('내 캘린더'));
  await page.keyboard.press('Escape');
  await sleep(200);
  // (e3) the to-do list in the day panel (C26): written with Enter, due that day, checked off in place
  await page.waitForSelector('.cal-day-panel .day-tasks input[name=task]');
  await page.fill('.cal-day-panel .day-tasks input[name=task]', '리뷰 보내기');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.cal-day-panel ul.tasks li');
  step('날 패널에 적은 할 일은 그 날까지다', mock.tasks().length === 1 && mock.tasks()[0].due === todayKey && (await texts(page, '.cal-day-panel ul.tasks li .text')).join() === '리뷰 보내기' && (await texts(page, '.cal-day-panel ul.tasks li .tag')).join() === '오늘', JSON.stringify(mock.tasks()));
  await page.click('.cal-day-panel ul.tasks li input[type=checkbox]');
  await sleep(300);
  step('체크하면 끝난 것으로 저장되고 줄이 그어진다', mock.tasks()[0].done === true && !!(await page.$('.cal-day-panel ul.tasks li.done')));
  await shot(page, 'e-calendar');

  // (e2) the month: an event dragged onto another day moves there; the week: seven columns, the all-day row, the
  // hours; a slot pressed is a new event at that time; a timed event dragged to another hour moves; the view is kept
  const drag = async (fromSel, toSel, dy = 0) => {
    await page.$eval(fromSel, (e) => e.scrollIntoView({ block: 'center' }));  // the day panel below may have scrolled the grid away
    const from = await (await page.$(fromSel)).boundingBox();
    const to = await (await page.$(toSel)).boundingBox();
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await page.mouse.down();
    await page.mouse.move(to.x + to.width / 2, to.y + 10 + dy, { steps: 8 });
    await page.mouse.move(to.x + to.width / 2, to.y + 12 + dy, { steps: 4 });
    await page.mouse.up();
    await sleep(400);
  };
  const nextKey = await page.$eval('.cal-day.today', (e) => (e.nextElementSibling || e.previousElementSibling).dataset.day);
  const nextIsAfter = nextKey > todayKey;
  await drag('.cal-day.selected .cal-ev', `.cal-day[data-day="${nextKey}"]`);
  step('달력에서 일정을 다른 날로 끌면 그 날로 옮겨 저장된다', mock.events()[0].start === nextKey && (await texts(page, `.cal-day[data-day="${nextKey}"] .cal-ev`)).some((x) => x.includes('랩 미팅'))
    && !(await page.$('.cal-day.selected .cal-ev')), JSON.stringify(mock.events()[0]));
  await page.click('.cal-nav .chip:text-is("주")');
  await page.waitForSelector('.wk-body');
  step('주 보기: 일곱 날의 머리·종일 줄·시간 격자, 달력은 비고 주소가 기억한다', (await page.$$('.wk-head .wk-day')).length === 7 && (await page.$$('.wk-allcol')).length === 7 && (await page.$$('.wk-col')).length === 7
    && (await page.$$('.wk-hours .wk-hour')).length === 24 && (await page.$$('.cal-grid .cal-day')).length === 0 && page.url().includes('v=week')
    && (await page.$eval('.wk-body', (e) => e.scrollTop)) > 0, page.url());
  const allWk = await page.$(`.wk-allcol[data-day="${nextKey}"] .cal-ev`);
  const wkHasIt = !!allWk && (await allWk.textContent()).includes('랩 미팅');
  step('종일 일정은 종일 줄의 그 날에 있다', wkHasIt || !nextIsAfter && !(await page.$('.wk-allcol .cal-ev')) && (await page.$$('.wk-col')).length === 7, String(wkHasIt));
  // a slot pressed: 10:00 of today (the column is 24 hours tall; the body is scrolled to the morning)
  await page.click(`.wk-col[data-day="${todayKey}"]`, { position: { x: 10, y: 10 * 44 + 5 } });
  await page.waitForSelector('dialog[open]');
  step('빈 칸을 누르면 그 시각의 새 일정이다', (await page.inputValue('dialog input[type=datetime-local] >> nth=0')) === `${todayKey}T10:00`
    && (await page.inputValue('dialog input[type=datetime-local] >> nth=1')) === `${todayKey}T11:00`, await page.inputValue('dialog input[type=datetime-local] >> nth=0'));
  await page.fill('dialog input[name=summary]', '세미나');
  await page.click('dialog button:text-is("저장")');
  await page.waitForSelector(`.wk-col[data-day="${todayKey}"] .wk-ev`);
  const ev1 = mock.events()[1];
  step('주 보기의 일정은 그 시각 높이의 블록이다', (await page.$eval(`.wk-col[data-day="${todayKey}"] .wk-ev`, (e) => Math.round(parseFloat(e.style.top)))) === 440
    && (await page.$eval(`.wk-col[data-day="${todayKey}"] .wk-ev`, (e) => Math.round(parseFloat(e.style.height)))) === 42
    && new Date(ev1.start).getTime() === new Date(`${todayKey}T10:00`).getTime(), JSON.stringify(ev1));
  // dragged to 14:00 of the same day
  const col = await (await page.$(`.wk-col[data-day="${todayKey}"]`)).boundingBox();
  const blk = await (await page.$(`.wk-col[data-day="${todayKey}"] .wk-ev`)).boundingBox();
  await page.mouse.move(blk.x + blk.width / 2, blk.y + blk.height / 2);
  await page.mouse.down();
  await page.mouse.move(col.x + col.width / 2, col.y + 14 * 44 + 8, { steps: 8 });
  await page.mouse.move(col.x + col.width / 2, col.y + 14 * 44 + 10, { steps: 4 });
  await page.mouse.up();
  await sleep(400);
  const ev2 = mock.events()[1];
  step('주 보기에서 다른 시각으로 끌면 그 시각으로 옮겨 길이를 지킨다', new Date(ev2.start).getTime() === new Date(`${todayKey}T14:00`).getTime() && new Date(ev2.end) - new Date(ev2.start) === 3600e3
    && (await page.$eval(`.wk-col[data-day="${todayKey}"] .wk-ev`, (e) => Math.round(parseFloat(e.style.top)))) === 14 * 44, JSON.stringify(ev2));
  // a repeating event is not dragged: its series is changed in the dialog
  await page.click(`.wk-col[data-day="${todayKey}"]`, { position: { x: 10, y: 16 * 44 + 5 } });
  await page.waitForSelector('dialog[open]');
  await page.fill('dialog input[name=summary]', '주간 회의');
  await page.selectOption('dialog select[name=rrule]', 'FREQ=WEEKLY');
  await page.click('dialog button:text-is("저장")');
  await page.waitForSelector('.wk-ev.repeats');
  step('반복 일정은 끌 수 없고 표시가 있다', (await page.$eval('.wk-ev.repeats', (e) => e.getAttribute('draggable'))) === null && (await page.$eval('.wk-ev:not(.repeats)', (e) => e.getAttribute('draggable'))) === 'true'
    && mock.events()[2].rrule === 'FREQ=WEEKLY');
  await open(page, `${BASE}/calendar?v=week&d=${todayKey}`, '.wk-body');
  step('주소로 돌아와도 주 보기다', (await texts(page, '.cal-nav .chip[aria-pressed="true"]')).join() === '주' && (await page.$$('.wk-col')).length === 7
    && (await page.$eval('.cal-nav > a', (a) => a.getAttribute('href'))) === `/calendar?v=week&d=${todayKey}`);
  await shot(page, 'e-calendar-week');
  await page.click('.cal-nav .chip:text-is("월")');
  await page.waitForSelector('.cal-grid .cal-day');
  step('월로 돌아오면 달력이고 주소에서 v가 빠진다', (await page.$$('.cal-grid .cal-day')).length === 42 && !page.url().includes('v=week'));

  // (f) the notes: Home rendered (wikilinks, mathematics), the tree, backlinks, search, an edit in place, a stale save refused
  const fetched = [];
  page.on('request', (r) => fetched.push(r.url()));
  mock.slowLinks(1500);
  const t0 = Date.now();
  await page.goto(`${BASE}/vault`);
  await page.waitForSelector('.note-body', { timeout: 4000 });
  const bodyAt = Date.now() - t0;
  step('본문이 백링크 응답(1.5s 지연)을 기다리지 않는다 (C31)', bodyAt < 1200 && !(await page.$('details.backlinks')), `${bodyAt}ms`);
  await page.waitForSelector('details.backlinks', { timeout: 4000 });
  step('백링크는 그 뒤에 채워진다', (await texts(page, 'details.backlinks summary'))[0] === '백링크 1');
  mock.slowLinks(0);
  step('수식이 있는 노트가 KaTeX 청크를 가져왔다', fetched.some((u) => /katex/i.test(u)), fetched.filter((u) => /assets/.test(u)).join(' '));
  step('노트의 첫 요소는 Home 노트다', (await texts(page, '.note-head h1'))[0] === 'Home' && (await texts(page, '.note-body h1'))[0] === 'Home');
  step('위키링크가 노트로 가고 없는 노트는 표시된다', (await page.$eval('.note-body a.wikilink', (a) => a.getAttribute('href'))) === '/vault/v1/Ideas/Operators.md'
    && (await texts(page, '.note-body a.wikilink'))[1] === 'the algebras');
  step('수식이 그려진다', (await page.$$('.note-body .katex')).length >= 2 && !!(await page.$('.note-body .katex-display')));
  step('트리에 폴더와 노트가 있고 머리에 새 노트와 볼트의 ⋯ 가 있다', (await texts(page, '.vault-side ul.tree summary')).includes('Ideas') && (await texts(page, '.vault-side ul.tree a')).includes('Home')
    && (await texts(page, '.vault-side .tree-head button')).includes('새 노트') && !!(await page.$('.vault-side .vault-head button.more')));
  step('백링크가 ⓘ 한 줄이다', (await texts(page, 'details.backlinks summary'))[0] === '백링크 1');
  await page.fill('.vault-side input[type=search]', 'bracket');
  await page.waitForSelector('.tree.hits');
  step('검색 결과가 트리 자리에 온다', (await texts(page, '.tree.hits li a')).join() === 'Lie algebras');
  await page.fill('.vault-side input[type=search]', '');
  await page.waitForSelector('.vault-side ul.tree:not(.hits)');
  await page.click('.note-head label.switch input');
  await page.waitForSelector('textarea.editor');
  await page.fill('textarea.editor', '# Home\n\nchanged in the browser\n');
  await page.click('.note .actions button:text-is("저장")');
  await page.waitForSelector('.note .actions span:has-text("저장됨")');
  step('편집은 같은 자리에서, 저장은 버튼 하나, 결과는 제자리에', mock.files().get('Home.md').text === '# Home\n\nchanged in the browser\n');
  mock.setFile('Home.md', '# Home\n\nchanged elsewhere\n');
  await page.fill('textarea.editor', '# Home\n\nmine\n');
  allowed = 412;
  await page.click('.note .actions button:text-is("저장")');
  await page.waitForSelector('.toast.error');
  allowed = 0;
  step('그 사이 바뀐 노트는 덮어쓰지 않는다(412 → 한 줄)', mock.files().get('Home.md').text === '# Home\n\nchanged elsewhere\n' && (await texts(page, '.toast.error'))[0].includes('다른 데서'));
  await open(page, `${BASE}/vault/v1/Ideas/Operators.md`, '.note-body');
  step('주소로 노트를 연다', (await texts(page, '.note-head h1'))[0] === 'Ideas/Operators' && (await texts(page, '.vault-side li.current a'))[0] === 'Operators');
  // a wide note in a fresh page: no KaTeX fetched; the table scrolls inside the note, the page does not widen (C31)
  const page5 = await ctx.newPage();
  watch(page5);
  const fetched5 = [];
  page5.on('request', (r) => fetched5.push(r.url()));
  await open(page5, `${BASE}/vault/v1/Wide.md`, '.note-body table');
  const widths = await page5.$eval('article.note', (a) => ({ article: [a.scrollWidth, a.clientWidth], table: [a.querySelector('table').scrollWidth, a.querySelector('table').clientWidth], doc: [document.documentElement.scrollWidth, document.documentElement.clientWidth] }));
  step('수식 없는 노트는 KaTeX 를 가져오지 않는다 (C31)', !fetched5.some((u) => /katex/i.test(u)), fetched5.filter((u) => /assets/.test(u)).join(' '));
  step('넓은 표는 노트 안에서 스크롤되고 페이지는 넓어지지 않는다 (C31)', widths.article[0] <= widths.article[1] + 1 && widths.table[0] > widths.table[1] && widths.doc[0] <= widths.doc[1], JSON.stringify(widths));
  // the tree stays as drawn when another note opens; the keys: / finds, e edits, Esc leaves (asking when dirty)
  await page5.$eval('.vault-side ul.tree', (u) => { u.dataset.mark = 'kept'; });
  await page5.click('.vault-side ul.tree li[data-path="Lie algebras.md"] a');
  await page5.waitForSelector('.note-head h1:text-is("Lie algebras")');
  step('노트를 바꿔도 트리는 다시 만들어지지 않는다 (C31)', (await page5.$eval('.vault-side ul.tree', (u) => u.dataset.mark)) === 'kept' && (await texts(page5, '.vault-side li.current a'))[0] === 'Lie algebras');
  await page5.keyboard.press('/');
  step('/ 가 찾기에 초점을 둔다 (C33)', await page5.$eval('.vault-side input[type=search]', (e) => e === document.activeElement));
  await page5.keyboard.press('Escape');
  await page5.$eval('.vault-side input[type=search]', (e) => e.blur());
  await page5.keyboard.press('e');
  await page5.waitForSelector('textarea.editor');
  await page5.type('textarea.editor', 'x');
  await page5.$eval('textarea.editor', (e) => e.blur());
  await page5.keyboard.press('Escape');
  await page5.waitForSelector('dialog[open] h2:text-is("저장하지 않은 변경")');
  await page5.keyboard.press('Escape');
  await sleep(150);
  step('e 가 편집기를 열고, 고친 채 Esc 는 묻고, 취소하면 편집기가 남는다', !!(await page5.$('textarea.editor')));
  await page5.keyboard.press('Escape');
  await page5.waitForSelector('dialog[open]');
  await page5.keyboard.press('Enter');
  await page5.waitForSelector('.note-body');
  step('Enter 로 확인하면 보기로 돌아온다 (C33)', !(await page5.$('textarea.editor')));
  await page5.close();
  // (f1) the vault's menu (C27): rename, its path, retry (off when ready), take off, add
  await page.click('.vault-side .vault-head button.more');
  await page.waitForSelector('.menu[role=menu]');
  step('볼트의 ⋯: 이름·경로·다시 시도·빼기·추가', JSON.stringify(await menuItems(page)) === '["이름 바꾸기…","경로","다시 시도","볼트 빼기","볼트 추가…"]'
    && (await page.$eval('.menu[role=menu] .menu-item:has(strong:text-is("다시 시도"))', (b) => b.disabled)), JSON.stringify(await menuItems(page)));
  await pickItem(page, '이름 바꾸기…');
  await page.waitForSelector('dialog[open] input[name=name]');
  await page.fill('dialog input[name=name]', 'Lab notes');
  await page.click('dialog button:text-is("저장")');
  await page.waitForSelector('.vault-head .vault-name:text-is("Lab notes")');
  step('볼트 이름을 바꾸면 제자리에 보이고 저장된다', mock.vaults()[0].name === 'Lab notes');
  // (f2) the note's menu: rename or move; a tree row's menu opens another note
  await page.click('.note-head button.more');
  await page.waitForSelector('.menu[role=menu]');
  step('노트의 ⋯: 이름 바꾸기·옮기기, 파일 열기, 지우기', JSON.stringify(await menuItems(page)) === '["이름 바꾸기·옮기기…","파일 열기","지우기"]', JSON.stringify(await menuItems(page)));
  await pickItem(page, '이름 바꾸기·옮기기…');
  await page.waitForSelector('dialog[open] input[type=text]');
  await page.fill('dialog input[type=text]', 'Ideas/Ops');
  await page.click('dialog button:text-is("옮기기")');
  await page.waitForSelector('.note-head h1:text-is("Ideas/Ops")');
  step('노트를 옮기면 새 주소로 열린다', page.url().endsWith('/vault/v1/Ideas/Ops.md') && mock.files().has('Ideas/Ops.md') && !mock.files().has('Ideas/Operators.md'));
  await menuOf(page, '.vault-side ul.tree li[data-path="Lie algebras.md"]');
  await pickItem(page, '열기');
  await page.waitForSelector('.note-head h1:text-is("Lie algebras")');
  step('트리 행의 메뉴로 노트를 연다', (await texts(page, '.vault-side li.current a'))[0] === 'Lie algebras');
  // (f3) adding a vault: inside the offered root; refused with a reason; a missing folder is a status card with a retry; taken off
  await page.click('.vault-side .vault-head button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '볼트 추가…');
  await page.waitForSelector('dialog[open] input[name=sub]');
  step('볼트 추가는 자리(루트) 안의 경로를 받는다', (await texts(page, 'dialog code.root')).join() === '/data/tester' && !!(await page.$('dialog input[name=name]')));
  await page.fill('dialog input[name=sub]', '../etc');
  allowed = 400;
  await page.click('dialog button:text-is("추가")');
  await page.waitForSelector('.toast.error');
  allowed = 0;
  step('안 되는 경로는 이유 한 줄로 거절된다', (await texts(page, '.toast.error'))[0].includes('..'));
  await page.click('.vault-side .vault-head button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '볼트 추가…');
  await page.waitForSelector('dialog[open] input[name=sub]');
  await page.fill('dialog input[name=sub]', 'Obsidian/Nowhere');
  await page.click('dialog button:text-is("추가")');
  await page.waitForSelector('.vault-head .chips');
  step('등록된 볼트는 칩으로 선다', mock.vaults().length === 2 && mock.vaults()[1].path === '/data/tester/Obsidian/Nowhere' && mock.vaults()[1].status === 'error');
  await open(page, `${BASE}/vault/v2`, '.vault-status');
  step('준비 안 된 볼트는 상태 카드다: 상태·경로·이유·다음 행동', (await texts(page, '.vault-status .tag')).join() === '오류' && (await texts(page, '.vault-status .reason'))[0].includes('폴더가 없습니다')
    && JSON.stringify(await texts(page, '.vault-status .actions button')) === '["다시 시도","이름 바꾸기","볼트 빼기","다른 볼트 추가"]', JSON.stringify(await texts(page, '.vault-status')));
  await page.click('.vault-status button:text-is("다시 시도")');
  await page.waitForSelector('.note-body');
  step('폴더를 고친 뒤 다시 시도하면 열린다', mock.vaults()[1].status === 'ok' && (await texts(page, '.note-head h1'))[0] === 'Home');
  await page.click('.vault-side .vault-head button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '볼트 빼기');
  await page.waitForSelector('dialog[open] h2:text-is("볼트 빼기")');
  await page.click('dialog[open] button[type=submit].danger');
  await page.waitForSelector('.vault-head .vault-name');
  step('볼트를 빼면 목록에서 빠지고 다른 볼트가 열린다', mock.vaults().length === 1 && (await texts(page, '.vault-head .vault-name')).join() === 'Lab notes');
  await shot(page, 'f-vault');

  // (g) the widgets of the calendar, the notes and the projects on the main page
  mock.put('site', 'prefs', { ...mock.get('site', 'prefs'), apps: ['calendar', 'vault', 'projects'],
                              home: [{ app: 'calendar', widget: 'today' }, { app: 'vault', widget: 'recent' }, { app: 'projects', widget: 'mine' }, { app: 'vault', widget: 'home' }, { app: 'calendar', widget: 'tasks' }] });
  await open(page, `${BASE}/`, '.widget[data-widget=recent] .widget-list');
  await page.waitForSelector('.widget[data-widget=tasks] input[name=task]');
  await page.fill('.widget[data-widget=tasks] input[name=task]', '초록 고치기');
  await page.keyboard.press('Enter');
  await page.waitForSelector('.widget[data-widget=tasks] ul.tasks li:not(.done)');
  step('할 일 위젯: 홈에서 바로 적고 목록에 선다 (C26)', mock.tasks().length === 2 && (await texts(page, '.widget[data-widget=tasks] ul.tasks li:not(.done) .text')).join() === '초록 고치기'
    && (await texts(page, '.widget[data-widget=tasks] .tasks-foot')).join().includes('1개 남음'), JSON.stringify(await texts(page, '.widget[data-widget=tasks]')));
  await menuOf(page, '.widget[data-widget=tasks] ul.tasks li:not(.done)');
  step('할 일의 메뉴: 기한·고치기·끝남·지우기', JSON.stringify(await menuItems(page)) === '["오늘까지","내일까지","날짜 고르기…","기한 없애기","고치기…","끝남","지우기"]', JSON.stringify(await menuItems(page)));
  await pickItem(page, '내일까지');
  step('기한을 주면 그 표가 선다', mock.tasks().find((x) => x.text === '초록 고치기').due > todayKey && (await texts(page, '.widget[data-widget=tasks] ul.tasks li:not(.done) .tag')).join() === '내일');
  await page.click('.widget[data-widget=tasks] .tasks-foot button:text-is("끝난 것 치우기")');
  await sleep(300);
  step('끝난 것 치우기는 끝난 줄만 지운다', mock.tasks().length === 1 && (await page.$$('.widget[data-widget=tasks] ul.tasks li')).length === 1);
  await page.waitForSelector('.widget[data-widget=today] .widget-list, .widget[data-widget=today] p.muted');
  await page.waitForSelector('.widget[data-widget=home] .note-body');
  step('캘린더 위젯이 오늘의 일정을 보인다', (await texts(page, '.widget[data-widget=today] .widget-list li a')).includes('세미나') && !(await texts(page, '.widget[data-widget=today] .widget-list li a')).includes('랩 미팅'), JSON.stringify(await texts(page, '.widget[data-widget=today]')));
  step('노트 위젯이 최근 노트와 Home 을 보인다', (await texts(page, '.widget[data-widget=recent] .widget-list li a')).length === 4 && (await texts(page, '.widget[data-widget=home] .note-body h1'))[0] === 'Home');
  step('프로젝트 위젯이 내 프로젝트를 보인다', (await texts(page, '.widget[data-widget=mine] .widget-list li a')).join() === '실험실');
  await shot(page, 'g-home');

  // (h) the theme: chosen in the settings, applied at once, kept as the cookie and in the account, survives a reload
  await open(page, `${BASE}/settings`, '.value');
  step('설정은 값 셋이고 설명 문단이 없다', (await page.$$('.value')).length === 3 && (await page.$$('main p.muted')).length === 0 && !(await page.$('main a.button')));
  const before = await bg(page);
  await page.selectOption('select[name=theme]', 'dark');
  await sleep(300);
  step('테마를 고르면 바로 바뀐다', (await theme(page)) === 'dark' && (await bg(page)) !== before, `${before} → ${await bg(page)}`);
  step('테마가 계정에 저장된다', mock.get('site', 'prefs').theme === 'dark');
  step("값이 기본이 아니면 '기본값'이 그 옆에 선다", (await texts(page, '.value button')).includes('기본값'));
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForSelector('.value');
  step('새로고침 뒤에도 어둡다(쿠키 → 첫 칠)', (await theme(page)) === 'dark' && (await page.evaluate(() => document.cookie.includes('theme=dark'))));
  await shot(page, 'h-dark');

  // (i) an app's own page: the same frame (header with the apps that are on, the theme) from site.js
  await open(page, `${BASE}/apps/eq-sandbox/`, 'body[data-ready]');
  step('앱 페이지도 같은 테마다', (await theme(page)) === 'dark');
  step('앱 페이지의 헤더도 같은 프레임이다(켠 앱 셋·이름 메뉴)', (await navApps(page)).length === 3 && !!(await page.$('header details.me')), JSON.stringify(await navApps(page)));

  // (j) a new browser: the account's theme and apps arrive with load(), without the cookie
  const ctx2 = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx2);
  const page2 = await ctx2.newPage();
  watch(page2);
  await open(page2, `${BASE}/`, '.widgets');
  step('새 브라우저도 계정의 테마와 배치를 받는다', (await theme(page2)) === 'dark' && (await cells(page2)).length === 5, `${await theme(page2)} ${JSON.stringify(await cells(page2))}`);
  await ctx2.close();

  // (k) an older account: hidden/order become the apps that are on
  mock.reset();
  mock.put('site', 'prefs', { lang: 'auto', start: '/', order: ['agents', 'eq-sandbox'], hidden: ['wordgen', 'projects', 'calendar', 'vault'], seen: ['eq-sandbox', 'wordgen', 'agents'] });
  const ctx3 = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx3);
  const page3 = await ctx3.newPage();
  watch(page3);
  await open(page3, `${BASE}/`, '.widgets');
  step('옛 계정은 보이던 앱이 켜진 채 깨어난다', JSON.stringify(await cells(page3)) === '["agents/launcher","eq-sandbox/launcher"]', JSON.stringify(await cells(page3)));
  await ctx3.close();

  // (l) signed out: the site's name, one sign-in, the public launchers
  mock.signOut();
  const ctx4 = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx4);
  const page4 = await ctx4.newPage();
  watch(page4);
  await open(page4, `${BASE}/`, 'a.primary');
  step('로그아웃 상태의 홈은 이름 + 로그인 하나 + 실행기다', (await texts(page4, 'a.primary')).join() === '로그인' && (await page4.$$('.widgets .widget')).length === 7 && !(await page4.$('main p.muted.small')));
  await ctx4.close();

  step('페이지 오류 0', report.pageErrors.length === 0, report.pageErrors.join(' | '));
  step('콘솔 오류 0', report.consoleErrors.length === 0, report.consoleErrors.join(' | '));
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
  console.log(`\n${report.steps.filter((s) => s.ok).length}/${report.steps.length} ok`);
  await browser.close();
}

run().catch((e) => { console.error('exception:', e); report.failed.push(`exception: ${e}`); fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1)); process.exit(1); });
