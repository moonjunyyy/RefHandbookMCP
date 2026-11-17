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
const navApps = (page) => page.$$eval('header nav > a, header nav > details.nav-menu > summary > a', (as) => as.map((a) => a.textContent.trim()));
const cards = (page) => page.$$eval('.catalog .store-card', (r) => r.map((e) => e.dataset.app));
const tiles = (page) => page.$$eval('.catalog .my-app', (r) => r.map((e) => e.dataset.app));
const menuItems = (page) => texts(page, '.menu[role=menu] .menu-item strong');
const menuOf = async (page, sel) => { await page.click(sel, { button: 'right' }); await page.waitForSelector('.menu[role=menu]'); };
const weeksOk = (page) => page.$$eval('.cal-weeks .cal-week', (rows) => rows.length > 6 && rows.every((r) => r.querySelectorAll('.cal-day').length === 7));  // the month: a column of weeks of seven days
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
  step("'앱 추가'는 가게(/apps)로 간다: 검색 + 칩 + 추가할 앱의 카드", page.url().endsWith('/apps') && !!(await page.$('.catalog input[type=search]')) && (await page.$$('.catalog .chips button.chip')).length >= 3 && (await cards(page)).length === 6 && !(await page.$('.my-apps')), `${page.url()} cards ${(await cards(page)).length}`);
  step('계정은 가게의 카드가 아니라 이름 메뉴 안이다', !(await page.$('.catalog [data-app=account]')) && (await texts(page, 'header details.me div a')).includes('계정'));

  // (b) the store (round 7): the apps added come first as tiles that open them; the rest are cards with one action, 추가 — no switch
  step('카드는 아이콘·이름 링크·한 줄·태그와 행동 하나(추가)를 말하고, 가게에 스위치가 없다', (await texts(page, '.catalog [data-app=calendar] .desc'))[0] === '내 일정과 프로젝트 일정을 한 달력에'
    && (await texts(page, '.catalog [data-app=calendar] .tags .tag')).join() === '일정' && (await page.$eval('.catalog [data-app=calendar] h3 a', (a) => a.getAttribute('href'))) === '/app/calendar'
    && (await texts(page, '.catalog [data-app=calendar] .app-tools button')).join() === '추가' && !(await page.$('.catalog label.switch')));
  await page.click('.catalog .store-card[data-app=eq-sandbox] .app-tools button');
  await sleep(300);
  step('추가하면 저장되고, 그 앱은 위의 내 앱 타일로 옮겨 간다', JSON.stringify(mock.get('site', 'prefs') && mock.get('site', 'prefs').apps) === '["eq-sandbox"]'
    && JSON.stringify(await tiles(page)) === '["eq-sandbox"]' && !(await cards(page)).includes('eq-sandbox'), `${JSON.stringify(mock.get('site', 'prefs'))} ${JSON.stringify(await tiles(page))}`);
  await open(page, `${BASE}/`, '.widgets');
  step('추가한 앱의 위젯이 홈에 보인다(기본 = 실행기)', JSON.stringify(await cells(page)) === '["eq-sandbox/launcher"]', JSON.stringify(await cells(page)));
  step('헤더에 추가한 앱이 나타난다', JSON.stringify(await navApps(page)) === '["🧮수식 플립플롭"]', JSON.stringify(await navApps(page)));
  await open(page, `${BASE}/apps`, '.catalog');
  await page.click('.catalog .store-card[data-app=wordgen] .app-tools button');
  await sleep(200);
  await page.click('.catalog .store-card[data-app=agents] .app-tools button');
  await sleep(200);
  step('내 앱 타일은 추가한 순서, 남은 카드는 사이트 파일의 순서다', JSON.stringify(await tiles(page)) === '["eq-sandbox","wordgen","agents"]' && JSON.stringify(await cards(page)) === '["projects","calendar","vault"]',
    `${JSON.stringify(await tiles(page))} ${JSON.stringify(await cards(page))}`);
  step('타일은 아이콘과 이름이고, 누르면 그 앱이다', (await page.$eval('.my-app[data-app=wordgen] > a', (a) => a.getAttribute('href'))) === '/apps/wordgen/'
    && (await texts(page, '.my-app[data-app=wordgen] .my-app-name')).join() === '글타래' && !!(await page.$('.my-app[data-app=wordgen] .app-icon')));
  await menuOf(page, '.my-app[data-app=agents]');
  step('타일의 메뉴(우클릭·⋯): 앱 정보·빼기', JSON.stringify(await menuItems(page)) === '["앱 정보","빼기"]', JSON.stringify(await menuItems(page)));
  await pickItem(page, '빼기');
  step('빼면 저장되고 카드로 돌아간다', JSON.stringify(mock.get('site', 'prefs').apps) === '["eq-sandbox","wordgen"]' && JSON.stringify(await tiles(page)) === '["eq-sandbox","wordgen"]'
    && JSON.stringify(await cards(page)) === '["projects","calendar","vault","agents"]', `${JSON.stringify(await tiles(page))} ${JSON.stringify(await cards(page))}`);
  await page.click('.catalog .store-card[data-app=agents] .app-tools button');
  await sleep(200);
  step("칩은 '전체'와 태그다('내 앱'은 칩이 아니라 위의 타일)", !(await texts(page, '.catalog .chips button.chip')).includes('내 앱') && (await texts(page, '.catalog .chips button.chip'))[0] === '전체');
  await page.click('.catalog .chips button.chip:text-is("일정")');
  await sleep(100);
  step('태그 칩은 그 갈래만(타일도 카드도)', JSON.stringify(await cards(page)) === '["calendar"]' && (await tiles(page)).length === 0 && page.url().endsWith('?tag=%EC%9D%BC%EC%A0%95'), page.url());
  await page.click('.catalog .chips button.chip:text-is("전체")');
  await page.fill('.catalog input[type=search]', '글');
  await sleep(100);
  step('검색이 타일과 카드를 함께 거르고 주소에 남는다', JSON.stringify(await tiles(page)) === '["wordgen"]' && JSON.stringify(await cards(page)) === '["vault"]' && page.url().includes('q=%EA%B8%80'),
    `${JSON.stringify(await tiles(page))} ${JSON.stringify(await cards(page))} ${page.url()}`);
  await page.fill('.catalog input[type=search]', '');
  await sleep(100);
  await shot(page, 'b-store');
  await open(page, `${BASE}/app/calendar`, '.store-head');
  step('앱 페이지: 이름·한 줄·행동 하나(추가)·소개·위젯(cols×rows)·링크', (await texts(page, '.store-head h1'))[0] === '캘린더' && !(await page.$('main label.switch'))
    && (await texts(page, 'main p.actions button')).join() === '추가' && (await texts(page, 'main .about'))[0].startsWith('내 캘린더와')
    && (await texts(page, 'main ul.plain li')).join('|').includes('오늘 2×1') && !(await page.$('main a.primary')), (await texts(page, 'main ul.plain li')).join('|'));
  await page.click('main p.actions button');
  await sleep(300);
  step("앱 페이지에서 추가하면 '열기'가 첫 행동이고 '빼기'가 옆에 선다", (await texts(page, 'main a.primary')).join() === '열기' && (await texts(page, 'main p.actions button')).join() === '빼기'
    && mock.get('site', 'prefs').apps.includes('calendar'));
  await shot(page, 'b-app');

  // (b2) the header (round 7): an app with one page is a link; one with more opens its pages under the pointer, as the person's menu does
  await open(page, `${BASE}/`, '.widgets');
  step('한 쪽뿐인 앱은 헤더의 링크, 여러 쪽인 앱(에이전트)은 펼침 메뉴다', (await page.$$('header nav > a')).length === 3 && (await page.$$('header nav > details.nav-menu')).length === 1,
    JSON.stringify(await navApps(page)));
  await page.hover('header details.nav-menu > summary');
  await sleep(150);
  step('짚으면 그 앱의 쪽들이 아래로 펼쳐진다', (await texts(page, 'header details.nav-menu[open] > div a')).join() === '에이전트 실행,프리셋,파일', (await texts(page, 'header details.nav-menu > div a')).join());
  await page.hover('header details.nav-menu[open] > div a:text-is("파일")');
  await sleep(250);
  step('펼친 목록으로 내려가도 닫히지 않는다', !!(await page.$('header details.nav-menu[open]')));
  await page.mouse.move(5, 700);
  await sleep(350);
  step('포인터가 떠나면 닫힌다', !(await page.$('header details[open]')));
  await page.hover('header details.me > summary');
  await sleep(150);
  step('이름 메뉴도 짚으면 펼쳐진다(계정·사용자 관리·앱·설정·로그아웃)', JSON.stringify(await texts(page, 'header details.me[open] > div a')) === '["계정","사용자 관리","앱","설정","로그아웃"]', JSON.stringify(await texts(page, 'header details.me > div a')));
  await page.keyboard.press('Escape');
  await sleep(100);
  step('Esc 가 닫는다', !(await page.$('header details[open]')));
  await page.mouse.move(5, 700);
  await sleep(200);

  // (c) the widget module: eq-sandbox's recent boards, from its own store
  mock.put('eq-sandbox', 'boards', [{ id: 'b1', title: '작업판 1', updated: Date.now() - 1000 }, { id: 'b2', title: '작업판 2', updated: Date.now() }]);
  await open(page, `${BASE}/`, '.widgets');
  step("편집 모드가 없다: 격자 위에 도구 줄이 없고, 마지막 칸이 '위젯 고르기'다 (C29, 7차)", !(await page.$('main .section-head')) && !(await page.$('main button:text-is("편집")'))
    && (await page.$eval('.widgets', (g) => g.lastElementChild.matches('button.add-widget') && g.lastElementChild.textContent.includes('위젯 고르기'))) && (await page.$eval('main', (m) => m.firstElementChild.matches('.widgets'))));
  await page.keyboard.press('w');
  await page.waitForSelector('dialog[open] .pick-list');
  const rows = await page.$$eval('dialog .pick-row', (els) => els.map((e) => ({ app: e.dataset.app, w: e.dataset.widget, title: e.querySelector('.pick-title').textContent, desc: e.querySelector('.pick-desc').textContent, size: e.querySelector('.tag.size').textContent, h: e.getBoundingClientRect().height, on: e.querySelector('input').checked })));
  step('w 가 시트를 열고, 앱별 행마다 스위치·이름·설명·크기(cols×rows)다 (C24·C34)', rows.length === 9 && rows.every((r) => r.title && r.desc && r.size) && rows.filter((r) => r.w === 'launcher').length === 4
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
  step('칸의 메뉴가 키보드로 열리고 설정·선언된 크기·앞으로·뒤로·빼기다', JSON.stringify(await menuItems(page)) === '["설정","1×1","2×1","1×2","2×2","3×1","3×2","4×2","앞으로","뒤로","빼기"]' && (await page.evaluate(() => document.activeElement.classList.contains('menu-item'))), JSON.stringify(await menuItems(page)));
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
  step('? 가 이 페이지의 키 목록을 보인다(선언 12 + 목록 1)', (await page.$$('dialog ul.keys li')).length === 13 && (await texts(page, 'dialog ul.keys li span')).includes('오늘'), JSON.stringify(await texts(page, 'dialog ul.keys li')));
  await page.keyboard.press('Escape');
  await sleep(150);
  step('캘린더의 첫 요소는 달력이고 머리 한 줄이다', (await weeksOk(page)) && (await page.$$('.cal-sources .chip')).length === 2 && !(await page.$('main p.muted')));
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
  await page.waitForSelector('.peek');
  const pkFirst = await page.$eval('.peek', (e) => e.textContent);
  const pkNoDialog = !(await page.$('dialog[open]'));
  await page.click('.peek button:text-is("편집")');
  await page.waitForSelector('dialog[open]');
  step('일정을 누르면 그 카드가 뜨고(대화상자가 아니다), 편집이 같은 대화상자를 그 값으로 연다 (C51)', pkNoDialog && pkFirst.includes('치과') && !(await page.$('.peek'))
    && (await page.inputValue('dialog input[name=summary]')) === '치과', pkFirst);
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
  await drag('.cal-day.selected .cal-ev', `.cal-day[data-day="${nextKey}"]`);
  step('달력에서 일정을 다른 날로 끌면 그 날로 옮겨 저장된다', mock.events()[0].start === nextKey && (await texts(page, `.cal-day[data-day="${nextKey}"] .cal-ev`)).some((x) => x.includes('랩 미팅'))
    && !(await page.$('.cal-day.selected .cal-ev')), JSON.stringify(mock.events()[0]));
  await page.click('.cal-nav .chip:text-is("주")');
  await page.waitForSelector('.wk-body');
  step('주 보기: 일곱 날의 머리·종일 줄·시간 격자, 달력은 비고 주소가 기억한다', (await page.$$('.wk-head .wk-day')).length === 7 && (await page.$$('.wk-allcol')).length === 7 && (await page.$$('.wk-col')).length === 7
    && (await page.$$('.wk-hours .wk-hour')).length === 24 && (await page.$$('.cal-grid .cal-day')).length === 0 && page.url().includes('v=week')
    && (await page.$eval('.wk-body', (e) => e.scrollHeight <= e.clientHeight + 1)), page.url());  // the whole day shows: nothing to scroll
  const H = await page.$eval('.wk-body .wk-hour', (e) => e.getBoundingClientRect().height);  // an hour's height: the room over the 24 hours shown
  const allWk = await page.$(`.wk-allcol[data-day="${nextKey}"] .cal-ev`);
  const wkHasIt = !!allWk && (await allWk.textContent()).includes('랩 미팅');
  // the day it was moved to may be in the next week (moved on a Sunday: the weeks start on Monday) — then this week shows none
  const shownWeek = await page.$$eval('.wk-allcol', (els) => els.map((e) => e.dataset.day));
  step('종일 일정은 종일 줄의 그 날에 있다', wkHasIt || !shownWeek.includes(nextKey) && !(await page.$('.wk-allcol .cal-ev')) && (await page.$$('.wk-col')).length === 7, `${wkHasIt} ${nextKey} ${shownWeek.join()}`);
  // a slot pressed: 10:00 of today (the column is 24 hours tall, all of it in view)
  await page.click(`.wk-col[data-day="${todayKey}"]`, { position: { x: 10, y: 10 * H + H / 9 } });
  await page.waitForSelector('.peek input[name=summary]');
  const qGhostTop = await page.$eval(`.wk-col[data-day="${todayKey}"] .wk-ghost`, (e) => Math.round(parseFloat(e.style.top)));
  const qCount = mock.events().length;
  await page.keyboard.press('Enter');  // no title: nothing is written
  await sleep(150);
  step('빈 칸을 누르면 그 자리에 작은 카드다: 제목에 초점, 그 시각의 자리 표시, 대화상자는 아니다; 제목 없이는 쓰지 않는다 (C49)', qGhostTop === Math.round(10 * H) && !(await page.$('dialog[open]'))
    && (await page.evaluate(() => document.activeElement?.getAttribute('name'))) === 'summary' && mock.events().length === qCount && !!(await page.$('.peek')), `${qGhostTop}`);
  await page.keyboard.type('세미나');
  await page.keyboard.press('Enter');
  await page.waitForSelector(`.wk-col[data-day="${todayKey}"] .wk-ev`);
  const ev1 = mock.events()[1];
  step('주 보기의 일정은 그 시각 높이의 블록이다', (await page.$eval(`.wk-col[data-day="${todayKey}"] .wk-ev`, (e) => Math.round(parseFloat(e.style.top)))) === Math.round(10 * H)
    && (await page.$eval(`.wk-col[data-day="${todayKey}"] .wk-ev`, (e) => Math.round(parseFloat(e.style.height)))) === Math.round(Math.max(H - 2, 18))
    && new Date(ev1.start).getTime() === new Date(`${todayKey}T10:00`).getTime(), JSON.stringify(ev1));
  // dragged to 14:00 of the same day
  const col = await (await page.$(`.wk-col[data-day="${todayKey}"]`)).boundingBox();
  const blk = await (await page.$(`.wk-col[data-day="${todayKey}"] .wk-ev`)).boundingBox();
  await page.mouse.move(blk.x + blk.width / 2, blk.y + blk.height / 2);
  await page.mouse.down();
  await page.mouse.move(col.x + col.width / 2, col.y + 14 * H + H / 6, { steps: 8 });
  await page.mouse.move(col.x + col.width / 2, col.y + 14 * H + H / 5, { steps: 4 });
  await page.mouse.up();
  await sleep(400);
  const ev2 = mock.events()[1];
  step('주 보기에서 다른 시각으로 끌면 그 시각으로 옮겨 길이를 지킨다', new Date(ev2.start).getTime() === new Date(`${todayKey}T14:00`).getTime() && new Date(ev2.end) - new Date(ev2.start) === 3600e3
    && (await page.$eval(`.wk-col[data-day="${todayKey}"] .wk-ev`, (e) => Math.round(parseFloat(e.style.top)))) === Math.round(14 * H), JSON.stringify(ev2));
  // a repeating event is not dragged: its series is changed in the dialog
  await page.click(`.wk-col[data-day="${todayKey}"]`, { position: { x: 10, y: 16 * H + H / 9 } });
  await page.waitForSelector('.peek input[name=summary]');
  await page.fill('.peek input[name=summary]', '주간 회의');
  await page.click('.peek button:text-is("자세히")');
  await page.waitForSelector('dialog[open]');
  step('자세히는 적은 제목과 그 칸의 시각을 대화상자로 가져간다 (C50)', (await page.inputValue('dialog input[name=summary]')) === '주간 회의'
    && (await page.inputValue('dialog input[type=datetime-local] >> nth=0')) === `${todayKey}T16:00` && (await page.inputValue('dialog input[type=datetime-local] >> nth=1')) === `${todayKey}T17:00`
    && !(await page.$('.peek')) && !(await page.$('.wk-ghost')));
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
  step('월로 돌아오면 달력이고 주소에서 v가 빠진다', (await weeksOk(page)) && !page.url().includes('v='));

  // (e2) the time axis (C41–C46): the month scrolls on, the views are levels, the title goes up, a day goes down, g goes to a date
  const evBefore = mock.events().length;
  const calTitle = () => page.$eval('.cal-nav h1', (e) => e.textContent.trim());
  const monthName = (add) => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() + add); return d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long' }); };
  const scrollTo = async (dir, until) => {
    for (let i = 0; i < 400 && (await calTitle()) !== until; i++) {
      await page.$eval('.cal-weeks', (el, by) => { el.scrollTop += by * el.clientHeight / 2; }, dir);
      await sleep(30);
    }
    return calTitle();
  };
  await page.keyboard.press('t');
  await page.waitForSelector('.cal-day.today.selected');
  step('달은 주의 열이고 이 달의 첫 주가 요일 아래에 있다 (C42)', (await calTitle()) === monthName(0) && (await page.$eval('.cal-weeks', (el) => {
    const y = el.scrollTop + el.querySelector('.cal-wds').offsetHeight;
    const top = [...el.querySelectorAll('.cal-week')].find((r) => r.offsetTop + r.offsetHeight / 2 > y);
    return [...top.querySelectorAll('.cal-day:not(.other)')].some((c) => c.dataset.day.endsWith('-01'));
  })), await calTitle());
  step('버튼 없이 굴려서 열두 달 넘게 앞으로 간다: 제목과 주소와 흐림이 따라온다 (C42)', (await scrollTo(1, monthName(14))) === monthName(14) && /[?&]m=\d{4}-\d{2}/.test(page.url())
    && (await page.$$eval('.cal-day:not(.other)', (cells) => new Set(cells.map((c) => c.dataset.day.slice(0, 7))).size)) === 1, `${await calTitle()} ${page.url()}`);
  const farDay = await page.$eval('.cal-day:not(.other)', (c) => c.dataset.day.slice(0, 8) + '15');
  await page.click(`.cal-day[data-day="${farDay}"]`);
  await page.waitForSelector('.cal-day-panel h2');
  await page.click('.cal-day-panel button:text-is("+ 일정")');
  await page.waitForSelector('dialog[open]');
  await page.fill('dialog input[name=summary]', '먼 일정');
  await page.check('dialog label.check input');
  await page.click('dialog button:text-is("저장")');
  await page.waitForSelector(`.cal-day[data-day="${farDay}"] .cal-ev`);
  step('굴려서 나온 주에 쓴 일정이 그 날에 보인다 (C42)', (await texts(page, `.cal-day[data-day="${farDay}"] .cal-ev .cal-title`)).includes('먼 일정'));
  await menuOf(page, `.cal-day[data-day="${farDay}"] .cal-ev`);
  await pickItem(page, '지우기');
  await page.waitForSelector('dialog[open] h2:text-is("일정 지우기")');
  await page.click('dialog[open] button[type=submit].danger');
  await sleep(300);
  step('굴려서 열두 달 넘게 뒤로 간다 (C42)', (await scrollTo(-1, monthName(-14))) === monthName(-14), await calTitle());
  await page.keyboard.press('t');
  await page.waitForSelector('.cal-day.today.selected');
  await page.click('.cal-nav button:text-is("›")');
  await sleep(150);
  const afterNext = await calTitle();
  await page.keyboard.press('ArrowLeft');
  await sleep(150);
  step('› 와 ← 는 옆 달의 첫 주를 올린다 (C42)', afterNext === monthName(1) && (await calTitle()) === monthName(0), `${afterNext} ${await calTitle()}`);
  // the title goes up, a day goes down (C43)
  await page.click('.cal-nav h1 button');
  await page.waitForSelector('.cal-year .month');
  step('제목은 한 단계 위다: 달 → 연, 열두 달이고 연의 제목은 버튼이 아니다 (C43)', (await page.$$('.cal-year .month')).length === 12 && !(await page.$('.cal-nav h1 button'))
    && (await calTitle()) === String(new Date().getFullYear()) && page.url().includes('v=year'));
  step('연에서 일정 있는 날은 농도가 있다 (C45)', (await page.$$('.cal-year button.month-day[data-level="1"], .cal-year button.month-day[data-level="2"], .cal-year button.month-day[data-level="3"]')).length >= 1);
  await page.click(`.cal-year .month >> nth=${new Date().getMonth()} >> button.month-title`);
  await page.waitForSelector('.cal-weeks .cal-week');
  step('연에서 달의 이름을 누르면 그 달이다 (C43)', (await calTitle()) === monthName(0) && !page.url().includes('v='), `${await calTitle()} ${page.url()}`);
  await page.click('.cal-day.today .cal-num');
  await page.waitForSelector('.cal-day-panel h2 button');
  await page.click('.cal-day-panel h2 button');
  await page.waitForSelector('.wk-body');
  step('달에서 고른 날의 제목을 누르면 그 날의 일 보기다: 한 열, 24시간, 종일 줄 (C43, C45)', (await page.$$('.wk-col')).length === 1 && (await page.$$('.wk-hours .wk-hour')).length === 24 && (await page.$$('.wk-allcol')).length === 1
    && page.url().includes(`v=day&d=${todayKey}`) && (await page.$eval('.wk-col', (e) => e.dataset.day)) === todayKey, page.url());
  await page.$eval('.wk-body', (e) => { e.scrollTop = 0; });
  await page.click('.wk-col', { position: { x: 40, y: H * 5 + H / 11 } });
  await page.waitForSelector('.peek input[name=summary]');
  const slot = await page.$eval('.wk-col .wk-ghost', (e) => Math.round(parseFloat(e.style.top)));
  const qSlotDay = await page.$eval('.wk-col', (e) => e.dataset.day);
  const qCount2 = mock.events().length;
  await page.keyboard.press('Escape');
  await sleep(150);
  step('일 보기의 빈 칸은 그 시각의 새 일정 카드이고, Esc 는 아무것도 쓰지 않고 닫는다 (C45, C49)', slot === Math.round(5 * H) && qSlotDay === todayKey && !(await page.$('.peek')) && !(await page.$('.wk-ghost'))
    && mock.events().length === qCount2, `${slot}`);
  // (e3) the quick card and the event's card (C49–C52), in the day view
  for (const [hour, name] of [[5, '피크 하나'], [3, '피크 둘']]) {
    await page.$eval('.wk-body', (e) => { e.scrollTop = 0; });
    await page.click('.wk-col', { position: { x: 40, y: H * hour + H / 11 } });
    await page.waitForSelector('.peek input[name=summary]');
    await page.keyboard.type(name);
    await page.keyboard.press('Enter');
    await page.waitForSelector(`.wk-col .wk-ev:has-text("${name}")`);
  }
  const pkMade = mock.events().filter((e) => e.summary.startsWith('피크 '));
  step('빠른 만들기: 제목과 Enter 가 그 시각의 한 시간짜리 일정을 쓴다 (C49)', pkMade.length === 2 && pkMade.every((e) => !e.allday && new Date(e.end) - new Date(e.start) === 3600000)
    && (await page.$eval('.wk-col .wk-ev:has-text("피크 하나")', (e) => Math.round(parseFloat(e.style.top)))) === Math.round(5 * H)
    && (await page.$eval('.wk-col .wk-ev:has-text("피크 둘")', (e) => Math.round(parseFloat(e.style.top)))) === Math.round(3 * H) && !(await page.$('.peek')), JSON.stringify(pkMade));
  await page.click('.wk-col .wk-ev:has-text("피크 하나")');
  await page.waitForSelector('.peek h2:text-is("피크 하나")');
  const pkWhen = await page.$eval('.peek .peek-when', (e) => e.textContent);
  const pkCal = await page.$eval('.peek .peek-cal', (e) => e.textContent.trim());
  await page.click('.wk-col .wk-ev:has-text("피크 둘")');
  await page.waitForSelector('.peek h2:text-is("피크 둘")');
  step('일정을 누르면 그 카드가 제목·시각·캘린더를 보이고, 다른 일정을 누르면 그 일정의 카드 하나로 바뀐다 (C51)', pkWhen.includes('5:00') && pkWhen.includes('6:00') && pkCal.length > 0
    && (await page.$$('.peek')).length === 1 && !(await page.$('dialog[open]')), `${pkWhen} / ${pkCal}`);
  await page.keyboard.press('Escape');
  await sleep(100);
  const pkBack = await page.evaluate(() => document.activeElement?.textContent ?? '');
  const pkClosed = !(await page.$('.peek'));
  await page.click('.wk-col .wk-ev:has-text("피크 둘")');
  await page.waitForSelector('.peek');
  await page.click('.peek button.more');
  await page.waitForSelector('.menu[role=menu]');
  const pkMenu = await texts(page, '.menu[role=menu] .menu-item strong');
  await page.keyboard.press('Escape');
  await sleep(100);
  step('Esc 는 카드를 닫고 초점을 그 일정에 돌려준다; ⋯ 는 그 일정의 메뉴이고 메뉴를 닫아도 카드는 남는다 (C51)', pkClosed && pkBack.includes('피크 둘') && pkMenu.includes('복제') && pkMenu.includes('지우기')
    && !(await page.$('.menu[role=menu]')) && !!(await page.$('.peek')), `${pkBack} / ${pkMenu.join()}`);
  const pkWide = page.viewportSize();
  await page.setViewportSize({ width: 390, height: 780 });
  await sleep(200);
  const pkSheet = await page.$eval('.peek', (e) => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right), Math.round(r.bottom), innerWidth, innerHeight]; }).catch(() => null);
  await page.setViewportSize(pkWide);
  await sleep(200);
  const pkExported = await page.evaluate(async () => { const m = await import('/auth/static/site.js'); return typeof m.peek === 'function' && typeof m.closePeek === 'function'; });
  step('좁은 화면에서 카드는 아래 가장자리의 시트다; 프레임이 peek 과 closePeek 을 내보낸다 (C52)', !!pkSheet && pkSheet[0] === 0 && pkSheet[1] === pkSheet[3] && pkSheet[2] === pkSheet[4] && pkExported, JSON.stringify(pkSheet));
  for (const name of ['피크 둘', '피크 하나']) {
    if (!(await page.$(`.peek h2:text-is("${name}")`))) { await page.click(`.wk-col .wk-ev:has-text("${name}")`); await page.waitForSelector(`.peek h2:text-is("${name}")`); }
    await page.click('.peek button:text-is("지우기")');
    await page.waitForSelector('dialog[open] h2:text-is("일정 지우기")');
    await page.click('dialog[open] button[type=submit].danger');
    await page.waitForFunction((n) => ![...document.querySelectorAll('.wk-col .wk-ev')].some((e) => e.textContent.includes(n)), name);
  }
  step('카드의 지우기는 한 번 묻고 지운다 (C51)', !mock.events().some((e) => e.summary.startsWith('피크 ')) && !(await page.$('.peek')) && !(await page.$('dialog[open]')));
  await page.click('.cal-nav h1 button');
  await page.waitForFunction(() => document.querySelectorAll('.wk-col').length === 7);
  const upWeek = page.url().includes('v=week');
  await page.click(`.wk-day[data-day="${todayKey}"] button.wk-num`);
  await page.waitForFunction(() => document.querySelectorAll('.wk-col').length === 1);
  step('일의 제목은 주로 올라가고, 주의 날 머리는 그 날로 내려간다 (C43)', upWeek && page.url().includes(`v=day&d=${todayKey}`), page.url());
  // the keys and the other views (C41, C45)
  const reads = [];
  const onRead = (r) => { if (r.url().includes('/calendar/api/v1/events?')) reads.push(r.url()); };
  page.on('request', onRead);
  const spanDays = (u) => { const q = new URL(u).searchParams; return Math.round((new Date(q.get('to')) - new Date(q.get('from'))) / 86400000); };
  await page.keyboard.press('a');
  await page.waitForSelector('.cal-list .cal-list-day');
  step('a 는 목록이다: 일정 있는 날만, 날마다 묶여, 일정마다 메뉴 (C41, C45)', page.url().includes('v=list')
    && (await page.$$eval('.cal-list .cal-list-day', (days) => days.length >= 1 && days.every((d) => d.querySelectorAll('.day-row .cal-ev').length >= 1 && d.querySelectorAll('.day-row button.more').length === d.querySelectorAll('.day-row').length)))
    && !!(await page.$('.cal-list button:text-is("더 보기")')), page.url());
  const firstSpan = reads.length ? spanDays(reads[reads.length - 1]) : 0;
  await page.click('.cal-list button:text-is("더 보기")');
  await sleep(300);
  step('더 보기는 목록이 읽는 날을 늘린다 (C45)', firstSpan > 0 && spanDays(reads[reads.length - 1]) > firstSpan, `${firstSpan} → ${reads.length ? spanDays(reads[reads.length - 1]) : '-'}`);
  page.off('request', onRead);
  await page.keyboard.press('y');
  await page.waitForSelector('.cal-year .month');
  await page.click('.cal-year button.month-day[data-today]');
  await page.waitForFunction(() => document.querySelectorAll('.wk-col').length === 1);
  step('y 는 연이고, 연에서 날을 누르면 그 날의 일 보기다 (C41, C43)', page.url().includes(`v=day&d=${todayKey}`), page.url());
  await open(page, `${BASE}/calendar?v=day&d=${todayKey}`, '.wk-body');
  step('주소로 다시 열어도 그 보기와 그 날이다 (C41)', (await page.$$('.wk-col')).length === 1 && (await texts(page, '.cal-nav .chip[aria-pressed="true"]')).join() === '일'
    && JSON.stringify(await texts(page, '.cal-nav .chip')) === '["연","월","주","일","목록"]');
  // g goes to a date (C44)
  await page.keyboard.press('m');
  await page.waitForSelector('.cal-weeks .cal-week');
  await page.keyboard.press('g');
  await page.waitForSelector('dialog[open] input[type=date]');
  const gd = new Date(); gd.setDate(1); gd.setMonth(gd.getMonth() + 5);
  const goKey = `${gd.getFullYear()}-${String(gd.getMonth() + 1).padStart(2, '0')}-20`;
  await page.fill('dialog input[type=date]', goKey);
  await page.keyboard.press('Enter');
  await page.waitForSelector(`.cal-day.selected[data-day="${goKey}"]`);
  step('g 는 날짜로 간다: 그 달이 보이고 그 날이 골라져 아래 열린다 (C44)', (await calTitle()) === monthName(5) && page.url().includes(`d=${goKey}`) && !!(await page.$('.cal-day-panel h2'))
    && (await page.$eval(`.cal-day[data-day="${goKey}"]`, (c) => { const b = c.closest('.cal-weeks').getBoundingClientRect(), r = c.getBoundingClientRect(); return r.top >= b.top && r.bottom <= b.bottom + 1; })), `${await calTitle()} ${page.url()}`);
  // on the hours, a sideways wheel or swipe moves one range a gesture (C46)
  await page.keyboard.press('w');
  await page.waitForSelector('.wk-body');
  const wk0 = await calTitle();
  await page.hover('.wk-body');
  await page.mouse.wheel(200, 0);
  await sleep(250);
  const wk1 = await calTitle();
  await page.mouse.wheel(200, 0);
  await sleep(150);
  step('주에서 옆으로 굴리면 한 번에 한 주 간다 (C46)', wk1 !== wk0 && (await calTitle()) === wk1 && page.url().includes('v=week'), `${wk0} | ${wk1} | ${await calTitle()}`);
  await sleep(700);
  await page.$eval('.wk', (el) => {
    const at = (x) => new Touch({ identifier: 1, target: el, clientX: x, clientY: 300 });
    el.dispatchEvent(new TouchEvent('touchstart', { touches: [at(600)], changedTouches: [at(600)], bubbles: true }));
    el.dispatchEvent(new TouchEvent('touchend', { touches: [], changedTouches: [at(300)], bubbles: true }));
  });
  await sleep(250);
  step('주에서 왼쪽으로 쓸면 다음 주다 (C46)', (await calTitle()) !== wk1, await calTitle());
  await page.keyboard.press('t');
  await page.waitForSelector(`.wk-col[data-day="${todayKey}"]`);
  await page.keyboard.press('m');
  await page.waitForSelector('.cal-weeks .cal-week');
  step('시간 축의 단계들이 일정을 남기지 않았다', mock.events().length === evBefore, `${evBefore} → ${mock.events().length}`);

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
  const attemptedDraft = await page.inputValue('textarea.editor');
  const draftUrl = page.url();
  page.once('dialog', dialog => dialog.dismiss());
  await page.click('.vault-side a:has-text("Lie algebras")');
  step('미저장 상태에서 노트 이동을 취소하면 입력과 주소를 지킨다',
    (await page.inputValue('textarea.editor')) === attemptedDraft && page.url() === draftUrl);
  await page.click('.note-head label.switch input');
  await page.waitForSelector('dialog[open]');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => !document.querySelector('dialog[open]') && document.querySelector('.note-head label.switch input').checked);
  step('보기 전환 취소는 편집 스위치와 초안을 되돌린다',
    (await page.isChecked('.note-head label.switch input')) && (await page.inputValue('textarea.editor')) === attemptedDraft);
  page.once('dialog', dialog => dialog.accept());
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
                              home: [{ app: 'calendar', widget: 'today' }, { app: 'vault', widget: 'recent' }, { app: 'projects', widget: 'mine' }, { app: 'vault', widget: 'home' }, { app: 'calendar', widget: 'tasks' },
                                     { app: 'calendar', widget: 'upcoming' }, { app: 'calendar', widget: 'month' }, { app: 'vault', widget: 'tags' }] });
  await open(page, `${BASE}/`, '.widget[data-widget=recent] .items-list');
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
  await page.waitForSelector('.widget[data-widget=today] .today-cols');
  await page.waitForSelector('.widget[data-widget=home] .note-body');
  step('캘린더 위젯이 오늘의 일정을 보인다', (await texts(page, '.widget[data-widget=today] .items-list a.item-text')).includes('세미나') && !(await texts(page, '.widget[data-widget=today] .items-list a.item-text')).includes('랩 미팅'), JSON.stringify(await texts(page, '.widget[data-widget=today]')));
  step('오늘 위젯의 머리: 날짜와 일정·마감의 수 (PIM: 한눈에)', (await texts(page, '.widget[data-widget=today] .widget-top .stat')).length >= 2
    && !!(await page.$('.widget[data-widget=today] .widget-top a.widget-date')), JSON.stringify(await texts(page, '.widget[data-widget=today] .widget-top')));
  step('노트 위젯이 최근 노트와 Home 을 보인다', (await texts(page, '.widget[data-widget=recent] .items-list a.item-text')).length === 4 && (await texts(page, '.widget[data-widget=home] .note-body h1'))[0] === 'Home');
  step('최근 노트: 7일의 수와 14일의 흐름, 줄마다 언제', (await page.$$('.widget[data-widget=recent] .activity .act')).length === 14
    && (await texts(page, '.widget[data-widget=recent] .item-aside')).length === 4, JSON.stringify(await texts(page, '.widget[data-widget=recent] .item-aside')));
  step('프로젝트 위젯이 내 프로젝트를 보인다', (await texts(page, '.widget[data-widget=mine] .items-list a.item-text')).join() === '실험실'
    && (await page.$$('.widget[data-widget=mine] .faces .face')).length === 2);
  await page.waitForSelector('.widget[data-widget=upcoming] .day-strip');
  step('다가오는 일: 7일의 띠(오늘 표시)와 날마다 묶인 일정', (await page.$$('.widget[data-widget=upcoming] .day-strip .day')).length === 7
    && (await page.$$('.widget[data-widget=upcoming] .day-strip .day[data-today]')).length === 1
    && (await texts(page, '.widget[data-widget=upcoming] .items-group')).length >= 1, JSON.stringify(await texts(page, '.widget[data-widget=upcoming] .items-group')));
  await page.waitForSelector('.widget[data-widget=month] .month-grid');
  const busy = await page.$('.widget[data-widget=month] button.month-day:not([data-level="0"]):not([data-today])');
  step('이번 달: 일정이 있는 날은 칠해지고 오늘은 테두리', !!busy && (await page.$$('.widget[data-widget=month] button.month-day[data-today]')).length === 1);
  if (busy) { await busy.click(); await sleep(150); }
  step('이번 달: 날을 누르면 그 날의 일정이 아래에 선다', (await page.$$('.widget[data-widget=month] button.month-day[aria-pressed=true]')).length === 1
    && (await texts(page, '.widget[data-widget=month] .month-agenda a.item-text')).length >= 1, JSON.stringify(await texts(page, '.widget[data-widget=month] .month-agenda')));
  await page.waitForSelector('.widget[data-widget=tags] .bars');
  step('태그: 노트 수만큼의 막대, 누르면 그 태그로 찾기', (await texts(page, '.widget[data-widget=tags] .bar-label')).includes('#draft')
    && /^\/vault\/\w+\?q=/.test(await page.$eval('.widget[data-widget=tags] .bars a', (a) => a.getAttribute('href'))),
    JSON.stringify([await texts(page, '.widget[data-widget=tags] .bar-label'), await page.$eval('.widget[data-widget=tags] .bars a', (a) => a.getAttribute('href'))]));
  step('할 일: 마감별 묶음과 끝낸 정도', (await texts(page, '.widget[data-widget=tasks] .items-group')).length >= 1 && !!(await page.$('.widget[data-widget=tasks] .meter')));
  await shot(page, 'g-home');

  // (w9) a place's own settings (C56–C58): what a widget declares, kept with the place; the same widget twice
  const w9Prefs = mock.get('site', 'prefs');
  const [w9c1, w9c2] = mock.calendars();
  const w9d = new Date();  // today, all day: the first rows of the list
  const w9k = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const w9a = w9k(w9d); w9d.setDate(w9d.getDate() + 1); const w9b = w9k(w9d);
  const w9cell = '.widgets .widget[data-app=calendar][data-widget=upcoming]';
  const w9cells = () => page.$$eval(w9cell, (els) => els.map((e) => ({ days: e.querySelectorAll('.day-strip .day').length, text: e.textContent, head: e.querySelector('.widget-head').textContent })));
  const w9home = () => mock.get('site', 'prefs').home.filter((p) => p.widget === 'upcoming');
  const w9menu = async (n, label) => { await page.hover(`${w9cell} >> nth=${n}`); await page.click(`${w9cell} >> nth=${n} >> .widget-tools button.more`); await page.waitForSelector('.menu[role=menu]'); await pickItem(page, label); };
  mock.put('site', 'prefs', { ...w9Prefs, apps: ['calendar', 'vault'], home: [{ app: 'calendar', widget: 'upcoming', size: '2x2' }], homeCustomized: true });
  await open(page, `${BASE}/`, `${w9cell} .day-strip`);
  await page.evaluate(async (list) => { const { api } = await import('/auth/static/site.js'); for (const e of list) await api('/calendar/api/v1').post('/events', e); },
    [{ cal: w9c1.id, summary: '설정 하나', allday: true, start: w9a, end: w9b, location: '', description: '', rrule: '' },
     { cal: w9c2.id, summary: '설정 둘', allday: true, start: w9a, end: w9b, location: '', description: '', rrule: '' }]);
  await open(page, `${BASE}/`, `${w9cell} .day-strip`);
  await page.waitForFunction((sel) => document.querySelector(sel)?.textContent.includes('설정 둘'), w9cell);
  let w9 = await w9cells();
  step('설정을 둔 적 없는 칸은 전과 같다: 7일, 모든 캘린더, 머리는 위젯의 이름 (C58)', w9.length === 1 && w9[0].days === 7 && w9[0].text.includes('설정 하나') && w9[0].text.includes('설정 둘')
    && w9[0].head.endsWith('다가오는 일'), JSON.stringify(w9));
  await w9menu(0, '설정');
  await page.waitForSelector('dialog[open] select[name=days]');
  const w9form = await page.$eval('dialog[open]', (d) => ({ title: d.querySelector('input[name=title]').placeholder, size: !!d.querySelector('select[name=size]'),
    days: [...d.querySelectorAll('select[name=days] option')].map((o) => o.value), day: d.querySelector('select[name=days]').value,
    cals: [...d.querySelectorAll('select[name=calendar] option')].map((o) => o.textContent) }));
  step('⋯ 의 설정: 제목·크기와 위젯이 선언한 설정마다 고를 것 — 내 캘린더는 열 때 읽는다 (C56)', w9form.title === '다가오는 일' && w9form.size && w9form.days.join() === '3,7,14' && w9form.day === '7'
    && w9form.cals.join() === ['모든 캘린더', ...mock.calendars().map((c) => c.name)].join(), JSON.stringify(w9form));
  await page.selectOption('dialog[open] select[name=days]', '3');
  await page.selectOption('dialog[open] select[name=calendar]', w9c2.id);
  await page.click('dialog[open] button:text-is("저장")');
  await page.waitForFunction((sel) => document.querySelectorAll(sel).length === 3, `${w9cell} .day-strip .day`);
  await page.waitForFunction(([sel, name]) => document.querySelector(sel)?.textContent.includes(name), [`${w9cell} .widget-head`, w9c2.name]);
  w9 = await w9cells();
  step('저장하면 그 칸에 남고 그대로 다시 그린다: 3일, 그 캘린더의 일정만, 머리에 고른 설정의 말 (C56)', w9[0].days === 3 && w9[0].text.includes('설정 둘') && !w9[0].text.includes('설정 하나')
    && w9[0].head.includes('3일') && w9[0].head.includes(w9c2.name) && JSON.stringify(w9home()[0].params) === JSON.stringify({ days: '3', calendar: w9c2.id }), JSON.stringify([w9, w9home()]));
  await page.keyboard.press('w');
  await page.waitForSelector('dialog[open] .pick-row[data-app=calendar][data-widget=upcoming]');
  await page.click('dialog[open] .pick-row[data-app=calendar][data-widget=upcoming] button:text-is("하나 더")');
  await page.waitForSelector('dialog[open] .pick-row[data-app=calendar][data-widget=upcoming] .tag:text-is("×2")');
  const w9plain = !(await page.$('dialog[open] .pick-row[data-app=calendar][data-widget=tasks] button:text-is("하나 더")'));
  await page.keyboard.press('Escape');
  await page.waitForFunction((sel) => document.querySelectorAll(sel).length === 2 && [...document.querySelectorAll(sel)].every((e) => e.querySelector('.day-strip')), w9cell);
  await w9menu(1, '설정');
  await page.waitForSelector('dialog[open] input[name=title]');
  await page.fill('dialog[open] input[name=title]', '이번 주 전체');
  await page.click('dialog[open] button:text-is("저장")');
  await page.waitForFunction(([sel, name]) => [...document.querySelectorAll(sel)].some((e) => e.textContent.includes(name)), [`${w9cell} .widget-head`, '이번 주 전체']);
  w9 = await w9cells();
  step('하나 더: 같은 위젯이 두 칸에 서고 칸마다 제 설정이다; 설정이 없는 위젯에는 하나 더가 없다 (C57)', w9.length === 2 && w9[0].days === 3 && !w9[0].text.includes('설정 하나')
    && w9[1].days === 7 && w9[1].text.includes('설정 하나') && w9[1].head.endsWith('이번 주 전체') && w9home()[1].title === '이번 주 전체' && !w9home()[1].params && w9plain, JSON.stringify([w9, w9home()]));
  await w9menu(0, '빼기');
  await page.waitForFunction((sel) => document.querySelectorAll(sel).length === 1, w9cell);
  w9 = await w9cells();
  const w9left = w9.length === 1 && w9[0].days === 7 && w9[0].head.endsWith('이번 주 전체');
  await page.keyboard.press('w');
  await page.waitForSelector('dialog[open] .pick-row[data-app=calendar][data-widget=upcoming]');
  await page.click('dialog[open] .pick-row[data-app=calendar][data-widget=upcoming] input');
  await sleep(300);
  await page.keyboard.press('Escape');
  await sleep(200);
  step('한 칸을 빼면 다른 칸은 남고, 스위치를 끄면 그 위젯의 칸이 모두 빠진다 (C57)', w9left && (await page.$$(w9cell)).length === 0 && w9home().length === 0, JSON.stringify([w9, w9home()]));
  mock.put('site', 'prefs', { ...w9Prefs, apps: ['calendar', 'vault'], home: [{ app: 'calendar', widget: 'upcoming', size: '2x2', params: { days: '99', calendar: 'gone' } }], homeCustomized: true });
  await open(page, `${BASE}/`, `${w9cell} .day-strip`);
  await page.waitForFunction((sel) => document.querySelector(sel)?.textContent.includes('설정 둘'), w9cell);
  w9 = await w9cells();
  step('선언에 없는 값은 기본값으로, 없어진 캘린더는 전부로 그린다 (C58)', w9[0].days === 7 && w9[0].text.includes('설정 하나') && w9[0].text.includes('설정 둘') && w9[0].head.endsWith('다가오는 일'), JSON.stringify(w9));
  await page.evaluate(async (ids) => { const { api } = await import('/auth/static/site.js'); for (const id of ids) await api('/calendar/api/v1').del(`/events/${id}`); },
    mock.events().filter((e) => e.summary.startsWith('설정 ')).map((e) => e.id));
  mock.put('site', 'prefs', w9Prefs);

  // (w10) the forms say what they show; a form as a setting; an empty list's way in; larger sizes (C61–C64)
  mock.put('site', 'prefs', { ...w9Prefs, apps: ['calendar', 'vault'], homeCustomized: true,
                              home: [{ app: 'calendar', widget: 'upcoming', size: '4x2' }, { app: 'vault', widget: 'recent' }, { app: 'calendar', widget: 'month' }] });
  await open(page, `${BASE}/`, `${w9cell} .day-strip`);
  await page.waitForSelector('.widget[data-widget=recent] .activity');
  await page.waitForSelector('.widget[data-widget=month] .month-grid');
  const w10 = await page.evaluate(async () => {
    const said = (s) => document.querySelector(`${s} .form-said`)?.textContent ?? '';
    const scale = (s) => [...document.querySelectorAll(`${s} .form-scale i`)].map((i) => getComputedStyle(i).backgroundColor);
    const site = await import('/auth/static/site.js');
    const part = site.activity([{ date: new Date(Date.now() - 864e5), n: 2 }, { date: new Date(), n: 5 }], '말');  // the part itself: the mock's notes are older than the run
    return { busiest: part.querySelector('.form-said').textContent, levels: [...part.querySelectorAll('.act')].map((a) => a.dataset.level).join(),
             act: said('.widget[data-widget=recent] .form'), ends: [...document.querySelectorAll('.widget[data-widget=recent] .form-ends span')].map((e) => e.textContent),
             strip: said('.widget[data-widget=upcoming]'), days: scale('.widget[data-widget=upcoming]'), month: said('.widget[data-widget=month]'), shades: scale('.widget[data-widget=month]'),
             legend: typeof site.legend === 'function', sizes: site.frame.sizes.length };
  });
  step('형식이 무엇을 보이는지 제 밑에 적는다: 흐름의 처음·오늘과 말(가장 많은 날의 수), 띠와 달의 농도 범례 (C61)', w10.act.includes('고친 노트') && w10.ends.length === 2 && w10.ends[1] === '오늘'
    && w10.busiest === '말 · 가장 많은 날 5' && w10.levels === '2,3'
    && w10.strip.includes('적음') && w10.strip.includes('많음') && w10.days.length === 3 && new Set(w10.days).size === 3
    && w10.month.includes('많은 날') && w10.shades.length === 3 && new Set(w10.shades).size === 3 && w10.legend, JSON.stringify(w10));
  const w10span = () => page.$eval(w9cell, (e) => [e.style.gridColumn, getComputedStyle(e.parentElement).gridTemplateColumns.split(' ').length, document.documentElement.scrollWidth <= document.documentElement.clientWidth]);
  const w10wide = await w10span();
  const w10view = page.viewportSize();
  await page.setViewportSize({ width: 700, height: w10view.height });
  await sleep(400);
  const w10narrow = await w10span();
  await page.setViewportSize(w10view);
  await sleep(400);
  const w10back = await w10span();
  step('큰 크기: 칸은 격자의 열 수를 넘지 않는다 — 좁아지면 있는 열을 다 쓰고 옆으로 넘치지 않으며, 넓어지면 제 크기다 (C64)', w10.sizes === 7 && w10wide[0] === `span ${Math.min(4, w10wide[1])}` && w10wide[2]
    && w10narrow[1] < 4 && w10narrow[0] === `span ${w10narrow[1]}` && w10narrow[2] && w10back[0] === w10wide[0], JSON.stringify([w10wide, w10narrow, w10back]));
  await w9menu(0, '설정');
  await page.waitForSelector('dialog[open] select[name=form]');
  const w10forms = await page.$$eval('dialog[open] select[name=form] option', (os) => os.map((o) => o.textContent));
  await page.selectOption('dialog[open] select[name=form]', 'list');
  await page.click('dialog[open] button:text-is("저장")');
  await page.waitForFunction((sel) => document.querySelector(sel) && !document.querySelector(`${sel} .day-strip`) && document.querySelector(`${sel} .widget-head`).textContent.includes('목록만'), w9cell);
  step('모양을 설정으로 고른다: 목록만 고르면 띠와 그 범례가 빠지고 머리에 그 말이 선다 (C63)', w10forms.join() === '띠와 목록,목록만,띠만' && w9home()[0].params.form === 'list'
    && !(await page.$(`${w9cell} .form-scale`)), JSON.stringify([w10forms, w9home()]));
  const w10cal = await page.evaluate(async () => { const { api } = await import('/auth/static/site.js'); return api('/calendar/api/v1').post('/calendars', { name: '빈 캘린더' }); });
  mock.put('site', 'prefs', { ...w9Prefs, apps: ['calendar', 'vault'], homeCustomized: true, home: [{ app: 'calendar', widget: 'upcoming', params: { calendar: w10cal.id } }] });
  await open(page, `${BASE}/`, `${w9cell} .items-none`);
  const w10none = await page.$eval(`${w9cell} .items-none`, (e) => [e.textContent, e.querySelector('a')?.getAttribute('href'), e.querySelector('a')?.textContent]);
  step('빈 목록은 첫 항목으로 가는 길을 함께 적는다 (C62)', w10none[0].includes('일정이 없습니다') && w10none[1] === '/calendar' && w10none[2] === '일정 만들기', JSON.stringify(w10none));
  await page.evaluate(async (id) => { const { api } = await import('/auth/static/site.js'); await api('/calendar/api/v1').del(`/calendars/${id}`); }, w10cal.id);
  mock.put('site', 'prefs', w9Prefs);

  // (h) the theme: chosen in the settings, applied at once, kept as the cookie and in the account, survives a reload
  await open(page, `${BASE}/settings`, '.value');
  step('설정은 모양·홈 배치·일반으로 나뉘고 테마는 미리보기와 함께 있다', (await texts(page, '.settings-controls > section h2')).join() === '모양,홈 배치,일반'
    && !!(await page.$('section:has(.look-preview) select[name=theme]')));
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

  // (h2) the look (round 7, docs/frame.md §1.3): the colour, the corners, the type, the text size, the main page's columns, an image
  // under the page — the site file's choices as /me carries them, each kept with the account and put on at once as tokens on <html>
  const LOOK = JSON.parse(process.env.LOOK_JSON);
  const prop = (name) => page.evaluate((n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim(), name);
  const chipsOf = (kind) => texts(page, `[data-look=${kind}] button.chip`);
  const pickLook = async (kind, label) => { await page.click(`[data-look=${kind}] button.chip:text-is("${label}")`); await sleep(300); await page.waitForSelector(`[data-look=${kind}]`); };
  const fontsOf = (kind) => page.$$(`[data-look=${kind}] button.font-choice`);
  step('모양 묶음: 사이트 파일이 선언한 색·모서리·글꼴(본문·제목·코드)·글자 크기·홈 칸 수와 배경 이미지 칸', (await chipsOf('palette')).length === LOOK.palette.length && (await chipsOf('corner')).length === LOOK.corner.length
    && (await fontsOf('type')).length === LOOK.type.length && (await fontsOf('heading')).length === LOOK.heading.length && (await fontsOf('mono')).length === LOOK.mono.length
    && (await chipsOf('size')).length === LOOK.size.length && (await chipsOf('columns')).length === LOOK.columns.length
    && !!(await page.$('input[name=image]')) && (await page.$$('[data-look=palette] .swatch')).length === LOOK.palette.length,
    JSON.stringify([await chipsOf('palette'), await chipsOf('size'), await chipsOf('columns')]));
  const ownAccent = await prop('--accent');
  const ownRadius = await prop('--radius');
  const pal = LOOK.palette.find((c) => Object.keys(c.dark).length);
  await pickLook('palette', pal.label);
  step('색을 고르면 바로 그 팔레트의 토큰이 된다(어두운 테마 = dark 값)', (await prop('--accent')) === pal.dark.accent && (await prop('--accent-soft')) === pal.dark['accent-soft'], `${await prop('--accent')} vs ${pal.dark.accent}`);
  step('고른 모양은 계정에 남는다', mock.get('site', 'prefs').look.palette === pal.id, JSON.stringify(mock.get('site', 'prefs').look));
  await page.selectOption('select[name=theme]', 'light');
  await sleep(300);
  step('테마를 바꾸면 팔레트도 그 테마의 값이다', (await prop('--accent')) === pal.light.accent, await prop('--accent'));
  await page.selectOption('select[name=theme]', 'dark');
  await sleep(300);
  const corner = LOOK.corner.find((c) => c.tokens.radius);
  await pickLook('corner', corner.label);
  step('모서리: --radius 와 버튼·칸의 둥글기가 그 값이다', (await prop('--radius')) === corner.tokens.radius
    && (await page.$eval('main section .inline-field button', (b) => getComputedStyle(b).borderTopLeftRadius)) === corner.tokens['radius-s']
    && (await page.$eval('main section.card', (s) => getComputedStyle(s).borderTopLeftRadius)) === corner.tokens.radius,
    `${await prop('--radius')} ${await page.$eval('main section .inline-field button', (b) => getComputedStyle(b).borderTopLeftRadius)}`);
  const sheet = (id) => `${LOOK.fonts}${id}.css`;
  const linked = () => page.$$eval('link[data-look-font]', (ls) => ls.map((l) => l.getAttribute('href')).sort());
  const defaults = ['type', 'heading', 'mono'].flatMap((k) => LOOK[k][0].fonts).map(sheet).sort();
  step('기본 글꼴은 theme.css 가 앞에 둔 열린 글꼴(본문·제목·코드)을 불러온다', defaults.length === 3 && JSON.stringify(await linked()) === JSON.stringify(defaults), JSON.stringify(await linked()));
  const pickFont = async (kind, c) => {
    await page.click(`[data-look=${kind}] button.font-choice:has(.font-name:text-is("${c.label}"))`);
    await page.waitForFunction(() => !document.querySelector('.settings-controls').inert);
    await page.waitForSelector(`[data-look=${kind}] button.font-choice[aria-pressed=true]`);
  };
  const loaded = (family) => page.evaluate(async (f) => { await document.fonts.ready; return [...document.fonts].some((x) => x.family.replace(/"/g, '') === f && x.status === 'loaded'); }, family);
  const type = LOOK.type.find((c, i) => i > 0 && c.fonts.length === 1);  // not the first: theme.css's own, which loads its open font without tokens
  const typeFamily = type.tokens.sans.split(',')[0].replace(/"/g, '');
  await pickFont('type', type);
  step('본문 글꼴: 본문이 그 글꼴이고, 그 글꼴의 스타일시트만 붙고, 실제로 내려받아 쓴다', (await page.evaluate(() => getComputedStyle(document.body).fontFamily)).startsWith(type.tokens.sans.split(',')[0])
    && JSON.stringify(await linked()) === JSON.stringify([sheet(type.fonts[0]), ...defaults.filter((x) => !LOOK.type[0].fonts.map(sheet).includes(x))].sort())
    && (await loaded(typeFamily)) && mock.get('site', 'prefs').look.type === type.id,
    `${await page.evaluate(() => getComputedStyle(document.body).fontFamily)} ${JSON.stringify(await page.$$eval('link[data-look-font]', (ls) => ls.map((l) => l.getAttribute('href'))))}`);
  const heading = LOOK.heading.find((c) => c.group === 'display');
  await pickFont('heading', heading);
  step('제목 글꼴: 제목이 그 글꼴이고 본문은 그대로다', (await page.$eval('h1', (e) => getComputedStyle(e).fontFamily)).startsWith(heading.tokens.serif.split(',')[0])
    && (await page.evaluate(() => getComputedStyle(document.body).fontFamily)).startsWith(type.tokens.sans.split(',')[0])
    && (await linked()).includes(sheet(heading.fonts[0])) && !(await linked()).includes(sheet(LOOK.heading[0].fonts[0])) || false, await page.$eval('h1', (e) => getComputedStyle(e).fontFamily));
  const mono = LOOK.mono.find((c, i) => i > 0 && c.fonts.length === 1);
  await pickFont('mono', mono);
  step('코드 글꼴: --mono 가 그 글꼴이다', (await prop('--mono')).startsWith(mono.tokens.mono.split(',')[0]) && (await linked()).length === 3 && (await linked()).includes(sheet(mono.fonts[0])), await prop('--mono'));
  step('글꼴 고르기: 줄마다 그 글꼴로 쓰인 견본, 보이는 줄의 글꼴만 불러온다', (await page.$$eval('[data-look=type] .font-sample', (els) => new Set(els.map((e) => e.style.fontFamily)).size)) === new Set(LOOK.type.map((c) => c.tokens.sans ?? '')).size
    && (await page.$$('link[data-font-preview]')).length > 0 && (await page.$$('link[data-font-preview]')).length < LOOK.type.length + LOOK.heading.length + LOOK.mono.length);
  await page.$eval('[data-look=type]', (e) => e.scrollIntoView());
  await shot(page, 'h-fonts');
  const size = LOOK.size.find((c) => c.tokens['root-size']);
  await pickLook('size', size.label);
  step('글자 크기: 뿌리 글자 크기가 바뀌고 글이 따라 커지거나 작아진다', (await page.evaluate(() => getComputedStyle(document.documentElement).fontSize)) === `${16 * parseFloat(size.tokens['root-size']) / 100}px`,
    await page.evaluate(() => getComputedStyle(document.documentElement).fontSize));
  const n = LOOK.columns.find((x) => x >= 3);
  await pickLook('columns', `${n}칸`);
  step('홈 칸 수가 계정에 남는다', mock.get('site', 'prefs').look.columns === n);
  await page.fill('input[name=image]', 'javascript:alert(1)');
  await page.press('input[name=image]', 'Enter');
  await sleep(300);
  step('배경 이미지: 주소가 아닌 것은 받지 않는다', !mock.get('site', 'prefs').look.image && (await texts(page, '.toast.error')).length === 1);
  await page.fill('input[name=image]', '/e2e/look.png');
  await page.press('input[name=image]', 'Enter');
  await sleep(300);
  step('배경 이미지: 이 사이트의 주소(또는 https)는 페이지 밑에 깔린다', mock.get('site', 'prefs').look.image === '/e2e/look.png'
    && (await page.evaluate(() => getComputedStyle(document.body, '::before').backgroundImage)).includes('/e2e/look.png'), await page.evaluate(() => getComputedStyle(document.body, '::before').backgroundImage));
  await shot(page, 'h-look');
  await open(page, `${BASE}/`, '.widgets');
  step('홈은 고른 칸 수로 나뉜다', (await page.$eval('.widgets', (g) => getComputedStyle(g).gridTemplateColumns.split(' ').length)) === n, await page.$eval('.widgets', (g) => getComputedStyle(g).gridTemplateColumns));
  await shot(page, 'h-look-home');
  // before the first paint: a page with theme.js alone (no site.js, no pages) already wears the kept look
  await page.route(`${BASE}/prepaint`, (r) => r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8',
    body: '<!doctype html><html><head><link rel="stylesheet" href="/auth/static/theme.css"><script src="/auth/static/theme.js"></script></head><body></body></html>' }));
  await page.goto(`${BASE}/prepaint`, { waitUntil: 'load' });
  step('theme.js 혼자서(site.js 없이, 첫 칠 전) 고른 모양을 이미 입힌다', (await prop('--accent')) === pal.dark.accent && (await prop('--radius')) === corner.tokens.radius
    && (await page.$$('link[data-look-font]')).length === 3, `${await prop('--accent')} ${await prop('--radius')}`);
  await open(page, BASE + '/settings', '#accent-hex');
  await page.fill('#accent-hex', '#abc');
  step('HEX 입력은 저장 전에 피커와 미리보기에 반영된다', (await page.inputValue('#accent-picker')) === '#aabbcc'
    && (await page.$eval('.look-sample-accent', el => getComputedStyle(el).backgroundColor)) === 'rgb(170, 187, 204)'
    && !mock.get('site', 'prefs').look.accent);
  await page.press('#accent-hex', 'Enter');
  await page.waitForFunction(() => JSON.parse(localStorage.getItem('prefs')).look.accent === '#aabbcc');
  await page.locator('#accent-picker').evaluate(el => {
    el.value = '#1e65c2'; el.dispatchEvent(new Event('input')); el.dispatchEvent(new Event('change'));
  });
  await page.waitForFunction(() => JSON.parse(localStorage.getItem('prefs')).look.accent === '#1e65c2');
  const setRange = async (id, value) => {
    await page.locator('#' + id).evaluate((el, v) => { el.value = v; el.dispatchEvent(new Event('input')); }, value);
    const output = await page.locator('output[for=' + id + ']').textContent();
    await page.locator('#' + id).evaluate(el => el.dispatchEvent(new Event('change')));
    await page.waitForFunction(([k,v]) => JSON.parse(localStorage.getItem('prefs')).look[k] === v, [id, value]);
    return output;
  };
  const radiusOutput = await setRange('radius', 0);
  await setRange('imageBlur', 12);
  await setRange('imageDim', 63);
  step('피커와 슬라이더가 계정에 저장되고 배경 필터는 배경층에만 적용된다', radiusOutput === '0%'
    && (await prop('--radius')) === '0px' && mock.get('site', 'prefs').look.accent === '#1e65c2'
    && (await page.evaluate(() => getComputedStyle(document.body, '::before').filter)) === 'blur(12px) brightness(0.37)'
    && (await page.evaluate(() => getComputedStyle(document.querySelector('main')).filter)) === 'none');
  const contrast = () => page.$eval('.look-sample-accent', el => {
    const style = getComputedStyle(el);
    const lum = css => css.match(/[0-9.]+/g).map(Number).slice(0, 3).reduce((sum, c, i) => {
      c /= 255;
      return sum + [0.2126, 0.7152, 0.0722][i] * (c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
    }, 0);
    const [bright, dim] = [lum(style.color), lum(style.backgroundColor)].sort((a, b) => b - a);
    return (bright + .05) / (dim + .05);
  });
  const darkContrast = await contrast();
  await page.selectOption('select[name=theme]', 'light');
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
  step('사용자 지정 채움색과 글자의 대비는 밝은·어두운 테마에서 4.5:1 이상이다',
    darkContrast >= 4.5 && (await contrast()) >= 4.5 && (await prop('--accent-fill')) === '#1e65c2');
  await page.selectOption('select[name=theme]', 'dark');
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
  await page.goto(BASE + '/prepaint', { waitUntil: 'load' });
  step('직접 설정도 새로고침 첫 칠부터 적용된다', (await prop('--accent-fill')) === '#1e65c2'
    && (await prop('--radius')) === '0px' && (await prop('--page-blur')) === '12px' && (await prop('--page-dim')) === '63%');
  await page.unroute(`${BASE}/prepaint`);
  await open(page, `${BASE}/settings`, '[data-look=palette]');
  await page.click('.value:has([data-look=palette]) button.link');
  await sleep(300);
  step("'기본값'은 theme.css 의 제 색으로 돌린다", (await prop('--accent')) === ownAccent && !('palette' in mock.get('site', 'prefs').look), `${await prop('--accent')} vs ${ownAccent}`);
  // Exercise the reset through the real control, preserving the independent home layout.
  await page.click('button:text-is("모양 초기화")');
  await page.waitForFunction(() => document.querySelector('select[name=theme]').value === 'auto');
  step('모양 초기화는 테마와 모양을 되돌리고 홈 칸 수는 유지한다', (await prop('--radius')) === ownRadius
    && (await page.evaluate(() => getComputedStyle(document.documentElement).fontSize)) === '16px' && JSON.stringify(await linked()) === JSON.stringify(defaults)
    && mock.get('site', 'prefs').theme === 'auto' && JSON.stringify(mock.get('site', 'prefs').look) === JSON.stringify({ columns: n }));
  await page.click('[data-look=columns] button:text-is("자동")');
  await page.waitForFunction(() => !JSON.parse(localStorage.getItem('look')).both['home-grid']);
  await page.selectOption('select[name=theme]', 'dark');
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
  const check = await ctx.newPage();
  await check.setViewportSize({ width: 360, height: 800 });
  await open(check, BASE + '/settings', '.look-preview');
  step('모바일에서도 모양 설정이 화면 너비에 맞는다', await check.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await check.route(BASE + '/apps/site/api/store/prefs', route => route.request().method() === 'PUT'
    ? route.fulfill({ status: 503 }) : route.fallback());
  await check.selectOption('select[name=theme]', 'light');
  await check.waitForSelector('.toast.error');
  step('저장 실패 시 테마·선택·브라우저 캐시가 마지막 저장값을 유지한다', (await theme(check)) === 'dark'
    && (await check.inputValue('select[name=theme]')) === 'dark' && mock.get('site', 'prefs').theme === 'dark'
    && (await check.evaluate(() => JSON.parse(localStorage.getItem('prefs')).theme)) === 'dark');
  await check.unroute(BASE + '/apps/site/api/store/prefs');
  await check.route(BASE + '/invalid-image', route => route.fulfill({ status: 200, body: 'not an image' }));
  await check.fill('input[name=image]', '/invalid-image');
  await check.press('input[name=image]', 'Enter');
  await check.waitForFunction(() => document.querySelector('.toast.error')?.textContent.includes('배경 이미지를 불러올 수 없습니다'));
  step('이미지가 아닌 응답을 거부하고 주소 입력은 보존한다', !mock.get('site', 'prefs').look.image
    && (await check.inputValue('input[name=image]')) === '/invalid-image');
  const savedHome = mock.get('site', 'prefs');
  mock.put('site', 'prefs', { ...savedHome, home: [{ app: savedHome.apps[0], widget: 'launcher' }] });
  await open(check, BASE + '/', '.widgets .widget');
  await check.focus('.widgets .widget');
  await check.keyboard.press('Delete');
  await check.waitForFunction(() => !document.querySelector('.widgets .widget'));
  await open(check, BASE + '/', '.widgets .add-widget');
  step('마지막 위젯을 빼면 다시 열어도 홈이 비어 있다', (await cells(check)).length === 0
    && mock.get('site', 'prefs').homeCustomized === true);
  mock.put('site', 'prefs', savedHome);
  await check.close();

  // (i) an app's own page: the same frame (header with the apps that are on, the theme) from site.js
  await open(page, `${BASE}/apps/eq-sandbox/`, 'body[data-ready]');
  step('앱 페이지도 같은 테마다', (await theme(page)) === 'dark');
  step('앱 페이지의 헤더도 같은 프레임이다(켠 앱 셋·이름 메뉴)', (await navApps(page)).length === 3 && !!(await page.$('header details.me')), JSON.stringify(await navApps(page)));

  // (m) the agents' files: the workspace is the user's only way to the sandbox's files — each entry's menu downloads, renames or
  // moves, deletes; a folder is made; a folder downloads as a zip (site-agent-files U1). Only the workspace is set afresh: the
  // account's settings stay as the steps before left them (the steps after read them)
  mock.resetWork();
  await open(page, `${BASE}/agents/files`, 'main table');
  const rowsOf = () => texts(page, 'main table tbody tr td:nth-child(2)');
  step('파일: 폴더의 항목과 머리의 새 폴더·폴더 내려받기', JSON.stringify(await rowsOf()) === '["notes.txt","runs/"]'
       && (await texts(page, 'main section > div.actions button')).join() === '새 폴더,폴더 내려받기 (zip)', JSON.stringify(await rowsOf()));
  await menuOf(page, 'main table tbody tr:has-text("notes.txt")');
  step('파일 줄의 오른쪽 클릭: 열기·내려받기·이름 바꾸기·옮기기·지우기', JSON.stringify(await menuItems(page)) === '["열기","내려받기","이름 바꾸기·옮기기…","지우기"]', JSON.stringify(await menuItems(page)));
  let dl = page.waitForEvent('download');
  await pickItem(page, '내려받기');
  step('파일 내려받기는 그 이름으로 저장된다', (await dl).suggestedFilename() === 'notes.txt');
  dl = page.waitForEvent('download');
  await page.click('main table tbody tr:has-text("runs/") button.more');
  await page.waitForSelector('.menu[role=menu]');
  await pickItem(page, '내려받기');
  step('폴더 내려받기는 zip 이다 (⋯ 메뉴)', (await dl).suggestedFilename() === 'runs.zip');
  await page.click('main section .actions button:text-is("새 폴더")');
  await page.fill('dialog[open] input', 'keep');
  await page.keyboard.press('Enter');
  await page.waitForSelector('main table tbody tr:has-text("keep/")');
  step('새 폴더가 만들어지고 목록에 선다', mock.work().get('keep') === null && JSON.stringify(await rowsOf()) === '["keep/","notes.txt","runs/"]', JSON.stringify(await rowsOf()));
  await page.focus('main table tbody tr:has-text("notes.txt") a');
  await page.keyboard.press('Shift+F10');
  await page.waitForSelector('.menu[role=menu]');
  step('Shift+F10 이 같은 메뉴를 연다', (await menuItems(page)).includes('이름 바꾸기·옮기기…'));
  await pickItem(page, '이름 바꾸기·옮기기…');
  step('옮기기 칸은 지금 경로로 시작한다', (await page.inputValue('dialog[open] input')) === 'notes.txt');
  await page.fill('dialog[open] input', 'keep/notes.txt');
  await page.keyboard.press('Enter');
  await sleep(400);
  step('옮기면 줄이 이 폴더를 떠나고 새 경로에 있다', mock.work().has('keep/notes.txt') && !mock.work().has('notes.txt') && JSON.stringify(await rowsOf()) === '["keep/","runs/"]', JSON.stringify(await rowsOf()));
  await open(page, `${BASE}/agents/files?path=keep/notes.txt`, 'main pre');
  step('열린 파일: 내려받기 + ⋯, 그리고 그 글', (await texts(page, 'main section > div.actions button')).join() === '내려받기,⋯' && (await texts(page, 'main pre')).join() === 'remember the milk');
  await page.click('main section .actions button.more');
  await page.waitForSelector('.menu[role=menu]');
  step('열린 파일의 메뉴엔 열기가 없다', JSON.stringify(await menuItems(page)) === '["내려받기","이름 바꾸기·옮기기…","지우기"]', JSON.stringify(await menuItems(page)));
  await pickItem(page, '지우기');
  step('지우기는 되돌릴 수 없다고 묻는다', (await texts(page, 'dialog[open] p')).join().includes('되돌릴 수 없습니다') && !!(await page.$('dialog[open] button.danger')));
  await page.click('dialog[open] button.danger');
  await page.waitForSelector('main p.empty');
  step('열린 파일을 지우면 그 폴더로 돌아간다', !mock.work().has('keep/notes.txt') && page.url().endsWith('/agents/files?path=keep'), page.url());
  await open(page, `${BASE}/agents/files`, 'main table');
  await menuOf(page, 'main table tbody tr:has-text("runs/")');
  await pickItem(page, '지우기');
  step('폴더를 지울 땐 그 안의 모든 것이라고 말한다', (await texts(page, 'dialog[open] p')).join().includes('폴더와 그 안의 모든 것'));
  await page.click('dialog[open] button.danger');
  await page.waitForFunction(() => !document.querySelector('main table') || ![...document.querySelectorAll('main table tbody tr')].some((r) => r.textContent.includes('runs/')));
  step('폴더가 그 안의 것과 함께 지워진다', ![...mock.work().keys()].some((k) => k.startsWith('runs')), JSON.stringify([...mock.work().keys()]));
  // the pick: boxes, Shift-click for a run, the head's box for all; the bar downloads, moves, deletes them together
  mock.resetWork();
  mock.work().set('keep', null);
  await open(page, `${BASE}/agents/files`, 'main table');
  const headActs = () => texts(page, 'main section > div.actions > *');
  await page.click('main table tbody tr:has-text("notes.txt") td.pick input');
  await page.click('main table tbody tr:has-text("runs/") td.pick input', { modifiers: ['Shift'] });
  step('고르면 머리가 고른 것의 동작으로 바뀐다 (Shift 로 이어 고름)', JSON.stringify(await headActs()) === '["2개 고름","내려받기","옮기기…","지우기","고르기 해제"]'
       && (await page.$$('main table tbody tr.picked')).length === 2 && (await page.$eval('main table thead input', (e) => e.indeterminate)), JSON.stringify(await headActs()));
  dl = page.waitForEvent('download');
  await page.click('main section > div.actions button:text-is("내려받기")');
  step('고른 것은 한 zip 으로 내려받는다', (await dl).suggestedFilename() === 'work.zip');
  await page.keyboard.press('Escape');
  await sleep(150);
  step('Esc 가 고른 것을 풀고 머리를 돌려놓는다', (await headActs()).join() === '새 폴더,폴더 내려받기 (zip)' && (await page.$$('main table tbody tr.picked')).length === 0, JSON.stringify(await headActs()));
  await page.click('main table tbody tr:has-text("notes.txt") td.pick input');
  await page.click('main table tbody tr:has-text("runs/") td.pick input');
  await page.click('main section > div.actions button:text-is("옮기기…")');
  step('옮기기 창은 고른 것을 이름으로 보인다', JSON.stringify(await texts(page, 'dialog[open] li code')) === '["notes.txt","runs"]', JSON.stringify(await texts(page, 'dialog[open] li code')));
  await page.fill('dialog[open] input', 'keep');
  await page.keyboard.press('Enter');
  await sleep(400);
  step('고른 것이 한 폴더로 옮겨진다', mock.work().has('keep/notes.txt') && mock.work().has('keep/runs/r1/report.md') && JSON.stringify(await rowsOf()) === '["keep/"]', JSON.stringify([...mock.work().keys()]));
  await open(page, `${BASE}/agents/files?path=keep`, 'main table');
  await page.click('main table thead input');
  await page.keyboard.press('Delete');
  await page.waitForSelector('dialog[open]');
  step('머리의 칸이 모두 고르고, Delete 가 지우기를 묻는다', (await texts(page, 'dialog[open] h2')).join() === '2개 지우기' && !!(await page.$('dialog[open] button.danger')), (await texts(page, 'dialog[open] h2')).join());
  await page.click('dialog[open] button.danger');
  await page.waitForSelector('main p.empty');
  step('고른 것이 함께 지워진다', ![...mock.work().keys()].some((k) => k.startsWith('keep/')), JSON.stringify([...mock.work().keys()]));
  await shot(page, 'agents-files');
  // a run's branches (agents/branches.py): what became of each repository of its read-write mounts
  await open(page, `${BASE}/agents/runs/run:b1`, 'ul.branches');
  const brs = await page.$$eval('ul.branches li', (ls) => ls.map((l) => [l.querySelector('code').textContent, l.querySelector('.tag').textContent, l.querySelector('pre') ? l.querySelector('pre').textContent : '']));
  step('실행 페이지가 브랜치와 저장소마다 그 결과를 보인다(병합됨·브랜치에 남음+충돌 파일·바뀐 것 없음)', (await texts(page, 'main section h2 code')).includes('run/b1')
    && JSON.stringify(brs) === JSON.stringify([['/Workspace/RefHandbookMCP', '병합됨', ''], ['/Workspace/NNG-lean', '브랜치에 남음', 'conflicts:\nREADME.md'], ['/Workspace/OnlineViL', '바뀐 것 없음', '']]), JSON.stringify(brs));
  await shot(page, 'agents-run-branches');
  const live = await ctx.newPage();
  let checks = 0;
  await live.route(url => decodeURIComponent(url.pathname) === '/agents/api/v1/runs/run:live', route => {
    checks++;
    return route.fulfill({ json: { id: 'run:live', title: 'Live', phase: 'running', state: checks > 1 ? 'closed' : 'open',
      goal: 'work', requested_by: 'user', usage: { input: checks, output: 0, cache_read: 0 }, tree: [], board: [],
      recipe: { input: 'work', title: '', grant: {}, flow: null } } });
  });
  await open(live, BASE + '/agents/runs/run:live', 'input[name=name]');
  await live.fill('input[name=name]', 'draft-preset');
  await live.waitForFunction(() => document.querySelector('main').textContent.includes('입력 2'));
  step('실행 상태가 자동 갱신돼도 프리셋 입력과 초점을 지킨다',
    (await live.inputValue('input[name=name]')) === 'draft-preset'
    && await live.$eval('input[name=name]', el => el === document.activeElement));
  await live.close();

  const copyPage = await ctx.newPage();
  await copyPage.addInitScript(() => Object.defineProperty(navigator, 'clipboard', { value: undefined }));
  await open(copyPage, BASE + '/vault/v1/Home.md', '.note-body');
  await copyPage.click('.vault-side .vault-head button.more');
  await pickItem(copyPage, '경로');
  await copyPage.waitForSelector('dialog[open] textarea');
  step('클립보드가 없어도 경로를 직접 복사할 수 있고 가짜 성공을 표시하지 않는다',
    await copyPage.$eval('dialog[open] textarea', field => field.value.length > 0 && field.selectionEnd === field.value.length)
    && !(await copyPage.$('.toast.ok')));
  await copyPage.close();

  const journey = await ctx.newPage();
  await open(journey, BASE + '/calendar?v=week', '.cal-nav');
  let fetches = 0, releaseOld;
  const old = new Promise(resolve => { releaseOld = resolve; });
  await journey.route('**/calendar/api/v1/events?*', async route => {
    const n = ++fetches;
    const start = new Date(new URL(route.request().url()).searchParams.get('from'));
    start.setUTCDate(start.getUTCDate() + 3);
    const end = new Date(start.getTime() + 3600000);
    if (n === 1) await old;
    await route.fulfill({ json: { events: [{ id: 'race-' + n, cal: 'u-1', start: start.toISOString(), end: end.toISOString(),
      summary: 'Fetch ' + n, allday: false }] } });
  });
  const next = journey.locator('.cal-nav button').filter({ hasText: '›' });
  await next.click();
  await next.click();
  await journey.waitForSelector('.wk :text-is("Fetch 2")');
  releaseOld();
  await journey.waitForLoadState('networkidle');
  step('캘린더의 느린 이전 응답이 최신 화면을 덮지 않는다', (await journey.locator('.wk :text-is("Fetch 2")').count()) > 0);
  await journey.close();

  // (j) a new browser: the account's theme and apps arrive with load(), without the cookie
  const ctx2 = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx2);
  const page2 = await ctx2.newPage();
  watch(page2);
  await open(page2, `${BASE}/`, '.widgets');
  step('새 브라우저도 계정의 테마와 배치를 받는다', (await theme(page2)) === 'dark' && (await cells(page2)).length === 8, `${await theme(page2)} ${JSON.stringify(await cells(page2))}`);
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

  // (l) signed out: the site's name and one sign-in — nothing of the apps (docs/frame.md §1)
  mock.signOut();
  const ctx4 = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx4);
  const page4 = await ctx4.newPage();
  watch(page4);
  await open(page4, `${BASE}/`, 'a.primary');
  step('로그아웃 상태의 홈은 이름 + 로그인 하나다(앱은 하나도 없다)', (await texts(page4, 'a.primary')).join() === '로그인' && (await page4.$$('.widgets .widget')).length === 0 && !(await page4.$('main p.muted.small')));
  await ctx4.close();

  // (m) the public board (docs/board.md): the notices, the shares — a preset's blocks without its keys, taken under one's own name —
  // sharing one's own (a layer that cannot travel says why), an administrator's notice and hiding, the board's widget
  mock.reset();
  mock.addCard({ id: 'board', title: '공개 보드', description: '공지, 함께 쓰는 프리셋과 레이어, 들어갈 수 있는 프로젝트', about: '관리자의 공지를 읽고 공유된 것을 가져옵니다.', tags: ['AI', '도구'],
                 code: '', icon: '📌', href: '/board', optional: true, default: true, links: [{ label: '공개 보드', href: '/board' }],
                 widgets: [{ id: 'news', title: '공개 보드', description: '공지와 새 공유', href: '/apps/site/widgets/board.js', size: '1x1' }] });
  const ctx5 = await browser.newContext({ viewport: { width: 1100, height: 820 }, locale: 'ko-KR' });
  await mock.install(ctx5);
  const bp = await ctx5.newPage();
  watch(bp);
  const shareCard = (sel) => texts(bp, `.store-card.share${sel}`);
  await open(bp, `${BASE}/board`, '.notice');
  step('보드: 고정 공지가 그려지고, 공유 카드는 종류·올린 이·판·가져간 수를 말한다', !!(await bp.$('.notice.pinned .note-body strong'))
    && (await shareCard('[data-share=s1]')).join().includes('bob') && (await shareCard('[data-share=s1]')).join().includes('판 1'), (await shareCard('')).join(' | '));
  step('칩은 전체·공지·종류(서버가 말한 것)·프로젝트다', JSON.stringify(await texts(bp, '.chips button.chip')) === '["전체","공지","프리셋","레이어","프로젝트"]', JSON.stringify(await texts(bp, '.chips button.chip')));
  await bp.click('.chips button.chip:text-is("레이어")');
  step('레이어 칩: 프리셋 공유는 빠지고 공지도 빠지며 주소에 남는다', !(await bp.$('[data-share=s1]')) && !(await bp.$('.notice')) && bp.url().includes('view=layer'), bp.url());
  await bp.click('.chips button.chip:text-is("전체")');
  await bp.fill('.board-tools input[type=search]', '없는말');
  step('검색이 공지와 공유를 함께 거른다', !(await bp.$('.notice')) && !(await bp.$('[data-share]')) && bp.url().includes('q='));
  await bp.fill('.board-tools input[type=search]', '');
  await bp.click('[data-share=s1] h3 button');
  await bp.waitForSelector('dialog[open] .flow-canvas');
  await shot(bp, 'm-share');
  step('공유를 열면 블럭 그림·명령·한도가 보이고 키는 없다', (await texts(bp, 'dialog[open] .share-steps pre')).join() === '오늘의 보고를 쓴다'
    && (await texts(bp, 'dialog[open] .share-preview dt code')).includes('max_turns') && !(await texts(bp, 'dialog[open]')).join().includes('anthropic/'));
  await bp.click('dialog[open] button[type=submit]');
  await bp.waitForSelector('dialog[open] input[name=as]');
  step('가져올 이름은 공유의 이름이 기본이고, 내 키로 돈다고 말한다', (await bp.inputValue('dialog[open] input[name=as]')) === 'daily'
    && (await texts(bp, 'dialog[open]')).join().includes('anthropic'));
  allowed = 409;
  await bp.click('dialog[open] button[type=submit]');
  await bp.waitForSelector('.toast.error');
  step('이미 있는 이름이면 까닭을 말한다', (await texts(bp, '.toast.error')).join().includes('이미 있는'), (await texts(bp, '.toast.error')).join());
  allowed = 0;
  await bp.click('[data-share=s1] .app-tools button:text-is("가져오기")');
  await bp.waitForSelector('dialog[open] .share-detail');
  await bp.click('dialog[open] button[type=submit]');
  await bp.waitForSelector('dialog[open] input[name=as]');
  await bp.fill('dialog[open] input[name=as]', 'morning');
  await bp.click('dialog[open] button[type=submit]');
  await bp.waitForSelector('.toast.ok');
  await sleep(300);
  step('다른 이름이면 내 프리셋이 되고, 알림에 열기가 있으며 가져간 수가 오른다', mock.board().mine.preset.some((x) => x.name === 'morning')
    && (await texts(bp, '.toast.ok button')).join() === '열기' && (await shareCard('[data-share=s1]')).join().includes('1번 가져감'), (await shareCard('[data-share=s1]')).join());
  await bp.click('.board-tools button:text-is("공유하기")');
  await bp.waitForSelector('dialog[open] select[name=kind]');
  await bp.selectOption('dialog[open] select[name=kind]', 'layer');
  step('공유할 수 없는 레이어는 고를 수 없고 까닭이 보인다', JSON.stringify(await texts(bp, 'dialog[open] select[name=name] option')) === '["a hello tool (greeter)"]'
    && (await texts(bp, 'dialog[open] ul.plain li')).join().includes('child'), JSON.stringify(await texts(bp, 'dialog[open] select[name=name] option')));
  await bp.selectOption('dialog[open] select[name=kind]', 'preset');
  await bp.fill('dialog[open] textarea[name=about]', '내 아침 보고');
  await bp.click('dialog[open] button[type=submit]');
  const mineSel = '.store-card.share:has(.tag.ok)';  // mine: the one share that carries the ok tag (내 공유)
  await bp.waitForSelector(mineSel);
  step('내 프리셋을 공유하면 내 공유 카드가 맨 앞에 서고, 내 것에는 가져오기가 없다', (await texts(bp, `${mineSel} .desc`)).join() === '내 아침 보고' && (await bp.$eval('.store-card.share', (e) => !!e.querySelector('.tag.ok')))
    && !(await bp.$(`${mineSel} .app-tools button:text-is("가져오기")`)));
  await bp.click(`${mineSel} button.more`);
  await bp.waitForSelector('.menu[role=menu]');
  step('내 공유의 메뉴: 다시 공유·내리기 (관리자가 아니면 숨기기는 없다)', JSON.stringify(await menuItems(bp)) === '["다시 공유","내리기"]', JSON.stringify(await menuItems(bp)));
  await pickItem(bp, '다시 공유');
  await bp.waitForSelector('dialog[open] select[name=kind][disabled]');
  await bp.click('dialog[open] button[type=submit]');
  await bp.waitForFunction((sel) => document.querySelector(sel)?.textContent.includes('판 2'), mineSel);
  step('다시 공유하면 같은 카드의 판이 오른다', (await bp.$$(mineSel)).length === 1 && (await shareCard(':has(.tag.ok)')).join().includes('판 2') && (await texts(bp, `${mineSel} .tag.ok`)).join() === '내 공유');
  step('관리자가 아니면 공지 쓰기가 없다', !(await bp.$('.board-tools button:text-is("공지 쓰기")')) && !(await bp.$('.notice button.more')));
  mock.boardAdmin(true);
  await open(bp, `${BASE}/board`, '.notice');
  await bp.click('.board-tools button:text-is("공지 쓰기")');
  await bp.waitForSelector('dialog[open] textarea[name=body]');
  await bp.fill('dialog[open] input[name=title]', '새 기능');
  await bp.fill('dialog[open] textarea[name=body]', '**공개 보드**가 열렸습니다.\n\n- 프리셋\n- 레이어');
  await bp.click('dialog[open] button[type=submit]');
  await bp.waitForSelector('.notice:has(b:text-is("새 기능"))');
  step('관리자가 쓴 공지가 고정 공지 다음에 서고, 마크다운으로 그려진다', JSON.stringify(await texts(bp, '.notice .item-head b')) === '["점검 안내","새 기능"]'
    && !!(await bp.$('.notice:has(b:text-is("새 기능")) .note-body li')), JSON.stringify(await texts(bp, '.notice .item-head b')));
  await bp.click('[data-share=s1] button.more');
  await bp.waitForSelector('.menu[role=menu]');
  step('관리자의 남의 공유 메뉴: 숨기기·내리기', JSON.stringify(await menuItems(bp)) === '["숨기기","내리기"]', JSON.stringify(await menuItems(bp)));
  await pickItem(bp, '숨기기');
  await bp.waitForSelector('dialog[open] input[name=why]');
  await bp.fill('dialog[open] input[name=why]', '확인 중');
  await bp.click('dialog[open] button[type=submit]');
  await bp.waitForSelector('[data-share=s1][data-hidden]');
  step('숨기면 관리자에게는 까닭과 함께 숨김으로 보인다', (await shareCard('[data-share=s1]')).join().includes('숨김: 확인 중'));
  await shot(bp, 'm-board');
  mock.boardAdmin(false);
  await open(bp, `${BASE}/board`, '.notice');
  step('숨긴 공유는 다른 사람에게 보이지 않는다', !(await bp.$('[data-share=s1]')) && (await bp.$$('.store-card.share')).length === 1);
  mock.put('site', 'prefs', { apps: ['board'], home: [{ app: 'board', widget: 'news' }] });
  await open(bp, `${BASE}/`, '.widget[data-widget=news] .items');
  const news = await texts(bp, '.widget[data-widget=news] .item-text');
  step('보드 위젯: 공지(고정 먼저)와 새 공유를 보인다', news[0] === '점검 안내' && news.includes('아침 보고') && (await texts(bp, '.widget[data-widget=news] .stat-n')).join() === '2,1', JSON.stringify(news));
  await ctx5.close();

  step('페이지 오류 0', report.pageErrors.length === 0, report.pageErrors.join(' | '));
  step('콘솔 오류 0', report.consoleErrors.length === 0, report.consoleErrors.join(' | '));
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
  console.log(`\n${report.steps.filter((s) => s.ok).length}/${report.steps.length} ok`);
  await browser.close();
}

run().catch((e) => { console.error('exception:', e); report.failed.push(`exception: ${e}`); fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1)); process.exit(1); });
