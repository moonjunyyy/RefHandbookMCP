// C7 measurement (docs/frame.md §7, docs/apps-vault-calendar.md §5): Chromium against the mock site. The
// main page with nothing on is the catalog; the catalog is a store (cards, chips, an app's page); turning
// an app on puts it in the header and on the main page; the widget module runs (eq-sandbox's recent
// boards); editing reorders by drag and by keyboard and removes; the calendar writes, shows, hides and
// removes an event and offers a subscription address; the notes page renders a vault's Home (wikilinks,
// mathematics), edits it in place, refuses a stale save, searches; the widgets of the calendar, the
// notes and the projects draw on the main page; the theme changes at once and survives a reload; an
// app's own page gets the same theme and header; an old account (hidden/order) wakes up with its apps on.
// Page errors and console errors must be 0.
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

  // (a) a new account: nothing on → the catalog is the page; the header holds only the person's menu
  await open(page, `${BASE}/`, '.catalog');
  step('새 계정의 홈은 카탈로그(검색 + 칩 + 카드)이다', !!(await page.$('.catalog input[type=search]')) && (await page.$$('.catalog .chips button.chip')).length >= 3 && (await cards(page)).length === 6, `cards ${(await cards(page)).length}`);
  step('홈에 인사·설명·버튼형 링크가 없다', !(await page.$('.hero')) && !(await page.$('main a.button')) && !(await page.$('main p.lead')));
  step('헤더에 켠 앱이 없고 이름 메뉴만 있다', (await navApps(page)).length === 0 && !!(await page.$('header details.me')));
  step('계정은 카탈로그의 카드가 아니라 이름 메뉴 안이다', !(await page.$('.catalog [data-app=account]')) && (await texts(page, 'header details.me div a')).includes('계정'));
  await shot(page, 'a-empty');

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
  await page.click('.section-head button:text-is("편집")');
  await page.click('.section-head button:text-is("+ 위젯")');
  await page.waitForSelector('dialog[open]');
  await page.check('dialog input[name="eq-sandbox/boards"]');
  await page.click('dialog button:text-is("적용")');
  await page.waitForSelector('.widget[data-widget=boards] .widget-list');
  const items = await texts(page, '.widget[data-widget=boards] .widget-list li a');
  step('위젯 모듈이 돌아 앱의 저장소를 보인다', JSON.stringify(items) === '["작업판 2","작업판 1"]', JSON.stringify(items));
  step('위젯 머리는 앱 이름 링크와 위젯 이름이다', (await texts(page, '.widget[data-widget=boards] .widget-head'))[0].includes('수식 플립플롭') && (await texts(page, '.widget[data-widget=boards] .widget-head'))[0].includes('최근 작업판'));
  step('배치가 저장되었다', JSON.stringify(mock.get('site', 'prefs').home) === '[{"app":"eq-sandbox","widget":"launcher"},{"app":"wordgen","widget":"launcher"},{"app":"agents","widget":"launcher"},{"app":"calendar","widget":"launcher"},{"app":"eq-sandbox","widget":"boards"}]', JSON.stringify(mock.get('site', 'prefs').home));
  await shot(page, 'c-widgets');

  // (d) editing: keyboard move, remove, and a drag
  await page.focus('.widgets .widget:nth-child(5)');
  await page.keyboard.press('Alt+ArrowLeft');
  await sleep(300);
  step('Alt+← 로 칸이 앞으로 간다', (await cells(page))[3] === 'eq-sandbox/boards', JSON.stringify(await cells(page)));
  await page.focus('.widgets .widget:nth-child(2)');
  await page.keyboard.press('Delete');
  await sleep(300);
  step('Delete 로 칸이 빠진다', JSON.stringify(await cells(page)) === '["eq-sandbox/launcher","agents/launcher","eq-sandbox/boards","calendar/launcher"]', JSON.stringify(await cells(page)));
  const from = await (await page.$('.widgets .widget:nth-child(3)')).boundingBox();
  const to = await (await page.$('.widgets .widget:nth-child(1)')).boundingBox();
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(to.x + 20, to.y + 20, { steps: 8 });
  await page.mouse.move(to.x + 30, to.y + 30, { steps: 4 });
  await page.mouse.up();
  await sleep(400);
  const dragged = JSON.stringify(await cells(page)) === '["eq-sandbox/boards","eq-sandbox/launcher","agents/launcher","calendar/launcher"]';
  step('끌어서 순서를 바꾼다', dragged, JSON.stringify(await cells(page)));
  await page.click('.section-head button:text-is("완료")');
  step('완료 뒤 칸의 도구가 사라진다', !(await page.$('.widgets.editing')));
  await shot(page, 'd-edited');

  // (e) the calendar: the grid, a day, an event written, shown, hidden with its calendar, removed; the subscription
  await open(page, `${BASE}/calendar`, '.cal-grid');
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
  await page.click('.cal-day-panel button:text-is("+ 일정")');
  await page.waitForSelector('dialog[open]');
  await page.fill('dialog input[name=summary]', '랩 미팅');
  await page.selectOption('dialog select[name=cal]', 'g-1');
  await page.check('dialog label.check input');
  await page.fill('dialog input[type=date] >> nth=0', todayKey);
  await page.fill('dialog input[type=date] >> nth=1', todayKey);
  await page.click('dialog button:text-is("저장")');
  await sleep(300);
  step('종일 일정은 날짜로 저장된다', mock.events().length === 2 && mock.events()[1].allday && /^\d{4}-\d{2}-\d{2}$/.test(mock.events()[1].start) && (await page.$$('.cal-day.selected .cal-ev')).length === 2, JSON.stringify(mock.events()[1]));
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
  await page.click('.cal-head button:text-is("폰에 구독")');
  await page.waitForSelector('dialog[open]');
  step('구독 주소는 대화상자 하나로 만들어 보인다', (await page.inputValue('dialog input[readonly]')).includes('/calendar/feed/'));
  await page.keyboard.press('Escape');
  await shot(page, 'e-calendar');

  // (f) the notes: Home rendered (wikilinks, mathematics), the tree, backlinks, search, an edit in place, a stale save refused
  await open(page, `${BASE}/vault`, '.note-body');
  step('노트의 첫 요소는 Home 노트다', (await texts(page, '.note-head h1'))[0] === 'Home' && (await texts(page, '.note-body h1'))[0] === 'Home');
  step('위키링크가 노트로 가고 없는 노트는 표시된다', (await page.$eval('.note-body a.wikilink', (a) => a.getAttribute('href'))) === '/vault/v1/Ideas/Operators.md'
    && (await texts(page, '.note-body a.wikilink'))[1] === 'the algebras');
  step('수식이 그려진다', (await page.$$('.note-body .katex')).length >= 2 && !!(await page.$('.note-body .katex-display')));
  step('트리에 폴더와 노트가 있고 끝 행이 새 노트다', (await texts(page, '.vault-side ul.tree summary')).includes('Ideas') && (await texts(page, '.vault-side ul.tree a')).includes('Home')
    && (await texts(page, '.vault-side .tree-foot button')).includes('새 노트'));
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
  await shot(page, 'f-vault');

  // (g) the widgets of the calendar, the notes and the projects on the main page
  mock.put('site', 'prefs', { ...mock.get('site', 'prefs'), apps: ['calendar', 'vault', 'projects'],
                              home: [{ app: 'calendar', widget: 'today' }, { app: 'vault', widget: 'recent' }, { app: 'projects', widget: 'mine' }, { app: 'vault', widget: 'home' }] });
  await open(page, `${BASE}/`, '.widget[data-widget=recent] .widget-list');
  await page.waitForSelector('.widget[data-widget=today] .widget-list, .widget[data-widget=today] p.muted');
  await page.waitForSelector('.widget[data-widget=home] .note-body');
  step('캘린더 위젯이 오늘의 일정을 보인다', (await texts(page, '.widget[data-widget=today] .widget-list li a')).includes('랩 미팅'), JSON.stringify(await texts(page, '.widget[data-widget=today]')));
  step('노트 위젯이 최근 노트와 Home 을 보인다', (await texts(page, '.widget[data-widget=recent] .widget-list li a')).length === 3 && (await texts(page, '.widget[data-widget=home] .note-body h1'))[0] === 'Home');
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
  step('새 브라우저도 계정의 테마와 배치를 받는다', (await theme(page2)) === 'dark' && (await cells(page2)).length === 4, `${await theme(page2)} ${JSON.stringify(await cells(page2))}`);
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
