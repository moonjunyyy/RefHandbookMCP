// The mock site as a Playwright route (no socket: the sandbox forbids listening): the sign-in's frame
// (/auth/api/v1/me, with the theme from the cookie as sso.py does), its static files (the real ones from
// src/portal/static), the pages app (web/dist) at every page path and its widgets, the pages' store
// (/apps/site/api/store/prefs, the real service's shapes), eq-sandbox's widget with its store, and the
// calendar's and the vault's APIs in memory (the real services' shapes: portal/calendar.py, portal/vault.py).
const fs = require('fs');
const path = require('path');

const ORIGIN = 'http://mock.local';
const STATIC = process.env.STATIC_ROOT;   // src/portal/static
const DIST = process.env.DIST_ROOT;       // web/dist
const EQ = process.env.EQ_ROOT;           // eq-sandbox public/ (widget.js)
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
                '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf' };

const store = { site: new Map(), 'eq-sandbox': new Map(), wordgen: new Map() };
const W = (app) => `/apps/site/widgets/${app}.js`;
// a widget's settings as /me carries them (deploy/site.toml's [[app.widget.param]])
const P_CAL = { id: 'calendar', label: '캘린더', default: '', from: { path: '/calendar/api/v1/calendars', list: 'calendars', value: 'id', label: 'name' }, all: '모든 캘린더' };
const P_DAYS = { id: 'days', label: '기간', default: '7', choices: [{ value: '3', label: '3일' }, { value: '7', label: '7일' }, { value: '14', label: '14일' }] };
const P_FORM_UP = { id: 'form', label: '모양', default: 'both', choices: [{ value: 'both', label: '띠와 목록' }, { value: 'list', label: '목록만' }, { value: 'strip', label: '띠만' }] };
const P_FORM_RECENT = { id: 'form', label: '모양', default: 'both', choices: [{ value: 'both', label: '흐름과 목록' }, { value: 'list', label: '목록만' }] };
const P_VAULT = { id: 'vault', label: '볼트', default: '', from: { path: '/vault/api/v1/vaults', list: 'vaults', value: 'id', label: 'name' }, all: '첫 볼트' };
const CARDS = [
  { id: 'account', title: '계정', description: '내 프로필과 비밀번호', about: '프로필과 비밀번호를 고칩니다.', tags: [], code: '', icon: '👤', href: '/account/', optional: false,
    links: [{ label: '내 계정', href: '/account/' }, { label: '사용자 관리', href: '/account/admin/users' }], widgets: [] },
  { id: 'projects', title: '프로젝트', description: '함께 쓰는 그룹', about: '프로젝트는 사람들이 직접 만드는 그룹입니다.', tags: ['자료'], code: '', icon: '🧩', href: '/projects', optional: true, default: true,
    links: [{ label: '프로젝트', href: '/projects' }], widgets: [{ id: 'mine', title: '내 프로젝트', description: '내가 든 프로젝트와 그 캘린더로 바로', href: W('projects'), size: '1x1' }] },
  { id: 'calendar', title: '캘린더', description: '내 일정과 프로젝트 일정을 한 달력에', about: '내 캘린더와 프로젝트의 캘린더를 한 달력에 겹쳐 봅니다. 구독 주소를 폰에 넣을 수 있습니다.', tags: ['일정'], code: '', icon: '📅', href: '/calendar', optional: true, default: true,
    links: [{ label: '캘린더', href: '/calendar' }], widgets: [{ id: 'today', params: [P_CAL], title: '오늘', description: '오늘의 일정과 마감인 할 일 — 넓은 칸', href: W('calendar'), size: '2x1' }, { id: 'upcoming', params: [P_DAYS, P_CAL, P_FORM_UP], title: '다가오는 일', description: '앞으로 7일의 일정', href: W('calendar'), size: '1x1' },
             { id: 'month', params: [P_CAL], title: '이번 달', description: '한 달을 한눈에', href: W('calendar'), size: '2x2' },
             { id: 'tasks', title: '할 일', description: '체크리스트 — 홈에서 바로 적고, 끝나면 체크', href: W('calendar'), size: '1x1' }] },
  { id: 'vault', title: '노트', description: 'Obsidian 볼트를 브라우저에서', about: '내 저장소의 마크다운 볼트를 읽고 고칩니다. 검색, 백링크, 최근 노트.', tags: ['글쓰기', '연구'], code: '', icon: '📝', href: '/vault', optional: true, default: true,
    links: [{ label: '노트', href: '/vault' }], widgets: [{ id: 'recent', params: [P_VAULT, P_FORM_RECENT], title: '최근 노트', description: '마지막으로 고친 노트 다섯', href: W('vault'), size: '1x1' },
                                                          { id: 'tags', params: [P_VAULT], title: '태그', description: '볼트의 태그', href: W('vault'), size: '1x1' }, { id: 'home', title: 'Home', description: '볼트의 Home 노트를 그대로 — 큰 칸', href: W('vault'), size: '2x2' }] },
  { id: 'eq-sandbox', title: '수식 플립플롭', description: '수식을 블록처럼 뒤집고 옮기는 작업판', about: '방정식의 항을 끌어 옮기고 뒤집어 정리합니다.', tags: ['연구', '도구'], code: '', icon: '🧮', href: '/apps/eq-sandbox/', optional: true,
    links: [{ label: '열기', href: '/apps/eq-sandbox/' }], widgets: [{ id: 'boards', title: '최근 작업판', description: '최근에 연 작업판으로 바로', href: '/apps/eq-sandbox/widget.js', size: '1x1' }] },
  { id: 'wordgen', title: '글타래', description: '소설을 위한 키워드와 집필 메모', about: '무작위 키워드로 이야기를 틔웁니다.', tags: ['글쓰기'], code: '', icon: '✍️', href: '/apps/wordgen/', optional: true,
    links: [{ label: '열기', href: '/apps/wordgen/' }], widgets: [] },
  { id: 'agents', title: '에이전트', description: '내 API 키로 돌리는 에이전트 팀과 샌드박스', about: '에이전트 팀을 실행합니다.', tags: ['AI', '도구'], code: '', icon: '🤖', href: '/agents/', optional: true,
    links: [{ label: '에이전트 실행', href: '/agents/' }, { label: '프리셋', href: '/agents/presets' }, { label: '파일', href: '/agents/files' }], widgets: [] },
];
const PAGES = ['/', '/apps', '/settings', '/account', '/account/', '/agents', '/agents/', '/calendar', '/vault', '/projects', '/board', '/handbook'];
// the handbook's graph (/handbook, refhandbook/graph_api.py): two topics, what joins them (a route, a row both reach, a
// tag of both), a card, and what one topic opens into
const GRAPH = {
  overview: {
    nodes: [{ id: 'n:geo', type: 'entry', title: '로그 차트', n: 3, ledger: 'geo' }, { id: 'n:num', type: 'entry', title: '자연수', n: 2, ledger: 'num' },
            { id: 'card:geo-where', type: 'card', title: 'Geo: where things are' }, { id: 'tag:charts', type: 'tag', title: 'charts' },
            { id: 'n:e1', type: 'row', kind: 'object', state: 'established', title: 'geo/E1 · the object', shared: true }],
    links: [{ s: 'n:geo', t: 'n:num', kind: 'route', n: 1 }, { s: 'n:geo', t: 'card:geo-where', kind: 'card', n: 1 }, { s: 'n:geo', t: 'n:e1', kind: 'shared', n: 1 },
            { s: 'n:num', t: 'n:e1', kind: 'shared', n: 1 }, { s: 'n:geo', t: 'tag:charts', kind: 'tag', n: 1 }, { s: 'n:num', t: 'tag:charts', kind: 'tag', n: 1 }],
  },
  entries: { 'n:geo': {
    nodes: [{ id: 'n:e1', type: 'row', kind: 'object', state: 'established', label: 'E1', title: 'E1 · the object', mark: true },
            { id: 'n:e2', type: 'row', kind: 'object', state: 'established', label: 'E2', title: 'E2 · its chart', mark: false },
            { id: 'n:h1', type: 'row', kind: 'claim', state: 'open', label: 'H1', title: 'H1 · the chart is smooth', mark: false },
            { id: 'tag:charts', type: 'tag', title: 'charts' }],
    links: [{ s: 'n:e2', t: 'n:e1', kind: 'basis' }, { s: 'n:h1', t: 'n:e2', kind: 'basis' }, { s: 'n:e2', t: 'tag:charts', kind: 'tag' }],
  } },
};
// the sizes a cell may have (portal/site.py SIZES, as /me carries them)
const SIZES = [{ id: '1x1', cols: 1, rows: 1 }, { id: '2x1', cols: 2, rows: 1 }, { id: '1x2', cols: 1, rows: 2 }, { id: '2x2', cols: 2, rows: 2 },
               { id: '3x1', cols: 3, rows: 1 }, { id: '3x2', cols: 3, rows: 2 }, { id: '4x2', cols: 4, rows: 2 }];
// the look's choices (the site file's [look], as /me carries them — run.sh reads them with portal/site.py)
const GUIDES = ['home', 'apps', 'calendar', 'vault', 'projects', 'agents', 'settings', 'account', 'wordgen'].map(id => id + ':1');
const LOOK = JSON.parse(process.env.LOOK_JSON || 'null') || { palette: [], corner: [], type: [], size: [], columns: [] };
let extraCards = [];
let slowLinks = 0;  // ms the /links answer is held back (the page must not wait for it)
let uid = 'tester';

// ── the public board, in memory (refhandbook/board.py, board_api.py) ─────────
let board;
function resetBoard() {
  const flow = { start: 'a', max_visits: 3, edges: [], steps: [{ id: 'a', title: '보고', provider: 'anthropic', model: 'claude-x', command: '오늘의 보고를 쓴다', team: false, x: 0, y: 0 }] };
  board = { admin: false, seq: 1,
    notices: [{ id: 'n1', title: '점검 안내', body: '토요일 밤 **두 시간** 멈춥니다.', author: 'root', pinned: true, created: 1, updated: 1 }],
    shares: [{ id: 's1', kind: 'preset', name: 'daily', author: 'bob', title: '아침 보고', about: '매일 아침 보고서', version: 1, imports: 0, created: 1, updated: 1,
               hidden: false, hidden_why: null, payload: { title: '아침 보고', goal: '오늘의 보고', limits: { policy: 'default', max_turns: 20 }, flow } }],
    mine: { preset: [{ name: 'daily', title: '아침 보고', why: '' }],
            layer: [{ name: 'greeter', title: 'a hello tool', why: '' }, { name: 'child', title: 'child', why: '이 레이어는 내 레이어 위에 쌓여 있어 공유할 수 없습니다: base@1' }] } };
}

// ── the calendar, in memory ───────────────────────────────────────────────
let calendars, events, feeds, seq, tasks, devices;
const DAY = 86400_000;
const parse = (s, allday) => (allday || /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(`${s}T00:00:00Z`) : new Date(s));
const fmt = (d, allday) => (allday ? d.toISOString().slice(0, 10) : d.toISOString().replace(/\.\d{3}Z$/, 'Z'));
function expand(e, lo, hi) {
  const start = parse(e.start, e.allday), end = parse(e.end, e.allday), len = end - start;
  const freq = (/FREQ=(\w+)/.exec(e.rrule || '') || [])[1];
  const stepDays = { DAILY: 1, WEEKLY: 7 }[freq];
  const out = [];
  for (let s = start, n = 0; s < hi && n < 400; n++, s = stepDays ? new Date(s.getTime() + stepDays * DAY) : new Date(hi.getTime() + 1)) {
    if (s.getTime() + len <= lo) continue;
    if (!freq && n > 0) break;
    if ((e.exdates || []).includes(fmt(s, e.allday))) continue;
    out.push({ ...e, start: fmt(s, e.allday), end: fmt(new Date(s.getTime() + len), e.allday), first: e.start, recurring: !!freq });
    if (!freq) break;
  }
  return out;
}

// ── the vault, in memory ──────────────────────────────────────────────────
let vaults, files;
const sha = (text) => require('crypto').createHash('sha256').update(text).digest('hex');
function tree() {
  const top = { name: '', path: '', type: 'dir', children: [] };
  const nodes = { '': top };
  const folder = (rel) => {
    if (nodes[rel]) return nodes[rel];
    const parent = folder(rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '');
    const node = { name: rel.split('/').pop(), path: rel, type: 'dir', children: [] };
    parent.children.push(node); nodes[rel] = node; return node;
  };
  for (const rel of [...files.keys()].sort()) {
    const parent = folder(rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '');
    parent.children.push({ name: rel.split('/').pop(), path: rel, type: rel.endsWith('.md') ? 'note' : 'file', mtime: files.get(rel).mtime, size: files.get(rel).text.length });
  }
  return top;
}
const links = (text) => [...text.matchAll(/\[\[([^\[\]|#]+)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]/g)].map((m) => m[1].trim());
const resolve = (target) => { const t = target.replace(/^\/+|\/+$/g, ''); for (const c of [t, `${t}.md`]) if (files.has(c)) return c; const tail = `${t.split('/').pop().toLowerCase()}.md`; return [...files.keys()].find((p) => p.split('/').pop().toLowerCase() === tail) || null; };

// ── the agents' workspace (/work), in memory: path → text for a file, null for a folder ────────────
let work;
const under = (rel, top) => rel === top || rel.startsWith(`${top}/`);
function workEntries(dir) {
  const out = new Map();
  for (const [rel, text] of work) {
    if (dir && !rel.startsWith(`${dir}/`)) continue;
    const rest = dir ? rel.slice(dir.length + 1) : rel;
    if (!rest) continue;
    const name = rest.split('/')[0], deeper = rest.includes('/');
    if (!out.has(name)) out.set(name, deeper || text === null ? { name, kind: 'dir', size: 0 } : { name, kind: 'file', size: Buffer.byteLength(text) });
  }
  return [...out.values()].sort((a, b) => (a.name < b.name ? -1 : 1));
}
const workDir = (rel) => !rel || work.get(rel) === null || [...work.keys()].some((k) => k.startsWith(`${rel}/`));

function resetWork() {
  work = new Map([['notes.txt', 'remember the milk\n'], ['runs/r1/report.md', '# done\n'], ['runs/r1/data/x.csv', '1,2\n']]);
}

function reset() {
  for (const s of Object.values(store)) s.clear();
  extraCards = [];
  uid = 'tester';
  calendars = [{ id: 'u-1', owner: 'tester', kind: 'user', name: '내 캘린더', color: '', main: true, created: 1 },
               { id: 'g-1', owner: 'lab', kind: 'group', name: 'lab', color: '#33aa55', main: true, created: 2 }];
  events = []; feeds = []; seq = 0; tasks = []; devices = []; slowLinks = 0;
  resetWork();
  resetBoard();
  vaults = [{ id: 'v1', name: 'Research', path: '/data/tester/Research', status: 'ok', reason: '', created: 1 }];
  files = new Map([
    ['Home.md', { text: '# Home\n\nStart at [[Ideas/Operators]] and [[Lie algebras|the algebras]]. An operator $T$ acts. #math\n\n$$\\int_0^1 x\\,dx = \\tfrac12$$\n', mtime: 3 }],
    ['Ideas/Operators.md', { text: '# Operators\n\nSee [[Home]] and [[Missing note]]. #draft\n', mtime: 2 }],
    ['Lie algebras.md', { text: 'The algebras: $[x, y]$, a bracket. Back to [[Ideas/Operators#Chain]].\n', mtime: 1 }],
    ['Wide.md', { text: '# Wide\n\nA table wider than the page, and a long code line.\n\n| ' + [...Array(14)].map((_, i) => `column ${i + 1} with a long heading`).join(' | ') + ' |\n|' + ' --- |'.repeat(14) + '\n| ' + [...Array(14)].map((_, i) => `cell ${i + 1} of the only row`).join(' | ') + ' |\n\n```\n' + 'x'.repeat(400) + '\n```\n', mtime: 0 }],
  ]);
}
reset();

const json = (route, status, body) => route.fulfill({ status, contentType: 'application/json; charset=utf-8', body: JSON.stringify(body) });
const file = (route, root, rel) => {
  const p = path.join(root, rel);
  if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) return route.fulfill({ status: 404, body: 'not found' });
  return route.fulfill({ status: 200, contentType: TYPES[path.extname(p)] || 'application/octet-stream', body: fs.readFileSync(p) });
};
const cookie = (req, name) => (new RegExp(`(?:^|; )${name}=([^;]*)`).exec(req.headers().cookie || '') || [])[1];
const body = (req) => JSON.parse(req.postData() || '{}');

async function handle(route) {
  const req = route.request();
  const url = new URL(req.url());
  const p = url.pathname;
  const q = url.searchParams;
  if (p === '/e2e/look.png') {  // an image to put under the page (the look's image): one pixel
    return route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64') });
  }
  if (p === '/auth/api/v1/me') {
    const theme = ['light', 'dark'].includes(cookie(req, 'theme')) ? cookie(req, 'theme') : 'auto';
    return json(route, 200, { uid, title: '모의 사이트', signin: '/auth', portal: '/account', lang: 'ko', theme, frame: 1, cards: [...CARDS, ...extraCards], menu: [], sizes: SIZES, look: LOOK });
  }
  if (p === '/apps/wordgen/api/me') return json(route, 200, { uid });
  if (p.startsWith('/auth/static/')) return file(route, STATIC, p.slice('/auth/static/'.length));
  let m;
  if ((m = /^\/apps\/(site|eq-sandbox|wordgen)\/api\/store(?:\/([a-z0-9_.-]{1,64}))?$/.exec(p))) {
    const s = store[m[1]];
    if (!m[2]) return json(route, 200, { keys: [...s.keys()].map((key) => ({ key })) });
    if (req.method() === 'GET') { const v = s.get(m[2]); return v === undefined ? json(route, 404, { error: 'no such key' }) : route.fulfill({ status: 200, contentType: 'application/json', body: v }); }
    if (req.method() === 'PUT') { s.set(m[2], req.postData() || 'null'); return route.fulfill({ status: 204, body: '' }); }
    return json(route, 404, { error: 'no such api' });
  }
  if (p === '/account/api/v1/projects') return json(route, 200, { projects: [{ cn: 'lab', title: '실험실', member: true, role: 'owner', members: ['tester', 'bob'] }], may_create: true });
  // the calendar
  if (p.startsWith('/calendar/api/v1/')) {
    if (!uid) return json(route, 401, { error: 'sign in first' });
    const rest = p.slice('/calendar/api/v1/'.length);
    if (rest === 'calendars' && req.method() === 'GET') return json(route, 200, { calendars, projects: ['lab'] });
    if (rest === 'calendars' && req.method() === 'POST') {
      const d = body(req);
      if (!d.name) return json(route, 400, { error: 'name 을(를) 적으세요.' });
      const c = { id: `${d.group ? 'g' : 'u'}-${++seq}`, owner: d.group || uid, kind: d.group ? 'group' : 'user', name: d.name, color: d.color || '', main: false, created: 3 };
      calendars.push(c); return json(route, 201, c);
    }
    if ((m = /^calendars\/([\w-]+)$/.exec(rest))) {
      const c = calendars.find((x) => x.id === m[1]);
      if (!c) return json(route, 404, { error: '그런 캘린더가 없습니다.' });
      if (req.method() === 'PATCH') { const d = body(req); if ('name' in d) c.name = d.name; if ('color' in d) c.color = d.color; return json(route, 200, c); }
      if (req.method() === 'DELETE') { if (c.main) return json(route, 409, { error: '기본 캘린더는 지울 수 없습니다.' }); calendars = calendars.filter((x) => x !== c); events = events.filter((e) => e.cal !== c.id); return route.fulfill({ status: 204, body: '' }); }
    }
    if (rest === 'devices' && req.method() === 'GET') return json(route, 200, { devices: devices.map(({ password, ...d }) => d), url: `${ORIGIN}/calendar/dav/`, username: uid });
    if (rest === 'devices' && req.method() === 'POST') {
      const name = (body(req).name || '').trim();
      if (!name) return json(route, 400, { error: 'name 을(를) 적으세요.' });
      const d = { id: `d${++seq}`, name, created: seq, last_used: 0, password: `pw-${seq}-xxxxxxxxxxxxxxxxxxxx` };
      devices.push(d); return json(route, 201, { ...d, username: uid, url: `${ORIGIN}/calendar/dav/` });
    }
    if ((m = /^devices\/(\w+)$/.exec(rest)) && req.method() === 'DELETE') { const n = devices.length; devices = devices.filter((d) => d.id !== m[1]); return n === devices.length ? json(route, 404, { error: '그런 기기가 없습니다.' }) : route.fulfill({ status: 204, body: '' }); }
    if (rest === 'tasks' && req.method() === 'GET') {
      const out = tasks.slice().sort((a, b) => (a.done - b.done) || (a.done ? b.updated - a.updated : a.rank - b.rank));
      return json(route, 200, { tasks: out });
    }
    if (rest === 'tasks' && req.method() === 'POST') {
      const d = body(req), text = (d.text || '').trim();
      if (!text) return json(route, 400, { error: 'text 을(를) 적으세요.' });
      if (d.due && !/^\d{4}-\d{2}-\d{2}$/.test(d.due)) return json(route, 400, { error: 'due 는 날짜(2026-11-02)입니다.' });
      const x = { id: `t${++seq}`, text, done: false, due: d.due || '', rank: tasks.length + 1, created: seq, updated: seq };
      tasks.push(x); return json(route, 201, x);
    }
    if (rest === 'tasks/clear-done' && req.method() === 'POST') { const n = tasks.filter((x) => x.done).length; tasks = tasks.filter((x) => !x.done); return json(route, 200, { removed: n }); }
    if ((m = /^tasks\/(\w+)$/.exec(rest))) {
      const x = tasks.find((y) => y.id === m[1]);
      if (!x) return json(route, 404, { error: '그런 할 일이 없습니다.' });
      if (req.method() === 'PATCH') { const d = body(req); for (const k of ['text', 'done', 'due', 'rank']) if (k in d) x[k] = d[k]; x.updated = ++seq; return json(route, 200, x); }
      if (req.method() === 'DELETE') { tasks = tasks.filter((y) => y !== x); return route.fulfill({ status: 204, body: '' }); }
    }
    if (rest === 'events' && req.method() === 'GET') {
      const lo = parse(q.get('from')), hi = parse(q.get('to'));
      const want = (q.get('cal') || '').split(',').filter(Boolean);
      const out = events.filter((e) => !want.length || want.includes(e.cal)).flatMap((e) => expand(e, lo, hi)).sort((a, b) => a.start.localeCompare(b.start));
      return json(route, 200, { events: out });
    }
    if (rest === 'events' && req.method() === 'POST') {
      const d = body(req);
      if (!d.summary) return json(route, 400, { error: '제목 을(를) 적으세요.' });
      const e = { id: `e${++seq}`, cal: d.cal, summary: d.summary, description: d.description || '', location: d.location || '', start: d.start,
                  end: d.end || d.start, allday: !!d.allday, rrule: d.rrule || '', exdates: d.exdates || [], status: 'CONFIRMED', created: 1, created_by: uid, updated: 1, updated_by: uid, seq: 0 };
      events.push(e);
      return json(route, 201, e);
    }
    if ((m = /^events\/(\w+)$/.exec(rest))) {
      const e = events.find((x) => x.id === m[1]);
      if (!e) return json(route, 404, { error: '그런 일정이 없습니다.' });
      if (req.method() === 'GET') return json(route, 200, e);
      if (req.method() === 'PATCH') { Object.assign(e, body(req), { seq: e.seq + 1, updated_by: uid }); return json(route, 200, e); }
      if (req.method() === 'DELETE') { events = events.filter((x) => x !== e); return route.fulfill({ status: 204, body: '' }); }
    }
    if (rest === 'feeds' && req.method() === 'GET') return json(route, 200, { feeds: feeds.map((f) => ({ ...f, url: `${ORIGIN}/calendar/feed/${f.token}.ics` })) });
    if (rest === 'feeds' && req.method() === 'POST') { const f = { token: `tok${++seq}`, cals: body(req).cals || [], name: body(req).name || '', created: 1 }; feeds.push(f); return json(route, 201, { ...f, url: `${ORIGIN}/calendar/feed/${f.token}.ics` }); }
    if ((m = /^feeds\/(\w+)$/.exec(rest)) && req.method() === 'DELETE') { feeds = feeds.filter((f) => f.token !== m[1]); return route.fulfill({ status: 204, body: '' }); }
    return json(route, 404, { error: 'no such api' });
  }
  // the vault
  if (p.startsWith('/vault/api/v1/')) {
    if (!uid) return json(route, 401, { error: 'sign in first' });
    const rest = p.slice('/vault/api/v1/'.length);
    if (rest === 'vaults' && req.method() === 'GET') return json(route, 200, { vaults, roots: ['/data/tester'] });
    if (rest === 'vaults' && req.method() === 'POST') {
      const d = body(req), where = '/data/tester';
      if (d.path && d.path.split('/').includes('..')) return json(route, 400, { error: "경로에 '..' 은 쓰지 않습니다." });
      if (!d.path || !(d.path === where || d.path.startsWith(`${where}/`))) return json(route, 400, { error: `${d.path} 은(는) 볼트로 등록할 수 있는 곳이 아닙니다. 등록할 수 있는 곳: ${where} 안의 폴더` });
      const missing = /Nowhere/.test(d.path);
      const v = { id: `v${vaults.length + 1}`, name: d.name || d.path.split('/').pop(), path: d.path, status: missing ? 'error' : 'ok',
                  reason: missing ? '그 폴더가 없습니다. 폴더를 만들거나, 경로를 고쳐 다시 등록하세요.' : '', created: 2 };
      vaults.push(v); return json(route, 201, v);
    }
    if ((m = /^vaults\/(\w+)$/.exec(rest))) {
      const v = vaults.find((x) => x.id === m[1]);
      if (!v) return json(route, 404, { error: '그런 볼트가 없습니다.' });
      if (req.method() === 'PATCH') { const name = (body(req).name || '').trim(); if (!name) return json(route, 400, { error: '이름을 적으세요.' }); v.name = name; return json(route, 200, v); }
      if (req.method() === 'DELETE') { vaults = vaults.filter((x) => x !== v); return route.fulfill({ status: 204, body: '' }); }
    }
    if ((m = /^vaults\/(\w+)\/retry$/.exec(rest)) && req.method() === 'POST') {
      const v = vaults.find((x) => x.id === m[1]);
      if (!v) return json(route, 404, { error: '그런 볼트가 없습니다.' });
      v.status = 'ok'; v.reason = '';  // the folder was made meanwhile
      return json(route, 200, v);
    }
    if ((m = /^vaults\/(\w+)\/move$/.exec(rest)) && req.method() === 'POST') {
      const d = body(req);
      if (!files.has(d.from)) return json(route, 404, { error: `그런 노트가 없습니다: ${d.from}` });
      if (files.has(d.to)) return json(route, 409, { error: `이미 있는 이름입니다: ${d.to}` });
      files.set(d.to, files.get(d.from)); files.delete(d.from); return json(route, 200, { from: d.from, to: d.to });
    }
    if ((m = /^vaults\/(\w+)\/(\w+)$/.exec(rest))) {
      if (!vaults.find((v) => v.id === m[1])) return json(route, 404, { error: '그런 볼트가 없습니다.' });
      const what = m[2], rel = q.get('path') || '';
      if (what === 'tree') return json(route, 200, tree());
      if (what === 'file' && req.method() === 'GET') { const f = files.get(rel); return f ? json(route, 200, { path: rel, text: f.text, sha256: sha(f.text), mtime: f.mtime, size: f.text.length }) : json(route, 404, { error: `그런 노트가 없습니다: ${rel}` }); }
      if (what === 'file' && req.method() === 'PUT') {
        const f = files.get(rel), given = req.headers()['if-match'];
        if (f && !given) return json(route, 409, { error: '이미 있는 노트입니다. 지금 내용을 읽은 뒤 고치세요.' });
        if (f && given !== sha(f.text)) return json(route, 412, { error: '그 사이 다른 데서 고쳐졌습니다. 다시 읽은 뒤 고치세요.' });
        const text = body(req).text; files.set(rel, { text, mtime: Date.now() / 1000 });
        return json(route, 200, { path: rel, sha256: sha(text), mtime: Date.now() / 1000, size: text.length });
      }
      if (what === 'file' && req.method() === 'DELETE') { if (!files.delete(rel)) return json(route, 404, { error: 'no such note' }); return json(route, 200, { path: rel, trash: `.trash/${rel}` }); }
      if (what === 'search') { const s = (q.get('q') || '').toLowerCase(); const hits = s ? [...files].filter(([, f]) => f.text.toLowerCase().includes(s)).map(([path_, f]) => ({ path: path_, title: path_.split('/').pop().replace(/\.md$/, ''), snippet: f.text.slice(0, 60) })) : []; return json(route, 200, { q: s, hits }); }
      if (what === 'links' && slowLinks) { await new Promise((r) => setTimeout(r, slowLinks)); }
      if (what === 'links') { const own = links((files.get(rel) || { text: '' }).text).map((x) => ({ path: resolve(x), text: x })); const back = [...files].filter(([src, f]) => src !== rel && links(f.text).some((x) => resolve(x) === rel)).map(([src]) => src).sort(); return json(route, 200, { path: rel, links: own, backlinks: back }); }
      if (what === 'recent') return json(route, 200, { notes: [...files].filter(([k]) => k.endsWith('.md')).sort((a, b) => b[1].mtime - a[1].mtime).slice(0, +(q.get('n') || 10)).map(([k, f]) => ({ path: k, title: k.split('/').pop().replace(/\.md$/, ''), mtime: f.mtime, size: f.text.length })) });
      if (what === 'tags') {  // portal/vault.py tags(): each tag with the notes that carry it, the most first
        const count = new Map();
        for (const [, f] of files) for (const tag of new Set([...f.text.matchAll(/(?:^|\s)#([\w/-]+)/g)].map((x) => x[1]))) count.set(tag, (count.get(tag) || 0) + 1);
        return json(route, 200, { tags: [...count].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([tag, notes]) => ({ tag, notes })) });
      }
      if (what === 'raw') return route.fulfill({ status: 404, body: 'not found' });
    }
    return json(route, 404, { error: 'no such api' });
  }
  if (decodeURIComponent(p) === '/agents/api/v1/runs/run:b1' && req.method() === 'GET') {  // a run that ended, with its branches (agents/branches.py)
    return json(route, 200, { id: 'run:b1', title: '노트 정리', phase: 'done', state: 'closed', requested_by: 'user', goal: '노트 정리', input: '노트 정리',
      recipe: { input: '노트 정리', title: '', grant: {}, flow: null }, error: null, grant: null, flow: null, flow_path: [], flow_end: null, proposal: null, approve_url: null,
      usage: { input: 10, output: 20, cache_read: 0 }, tree: [], result: { outcome: 'done', text: '정리했습니다', notes: [] }, board: [],
      branches: { branch: 'run/b1', why: '', repos: [
        { repo: '/Workspace/RefHandbookMCP', state: 'merged', files: 3, why: '' },
        { repo: '/Workspace/NNG-lean', state: 'kept', files: 1, why: 'conflicts:\nREADME.md' },
        { repo: '/Workspace/OnlineViL', state: 'unchanged', files: 0, why: '' }] } });
  }
  if (p.startsWith('/agents/api/v1/files')) {
    if (!uid) return json(route, 401, { error: { code: 'unauthorized', message: 'sign in first' } });
    const rel = (q.get('path') || '').replace(/^\/+|\/+$/g, '');
    const no = (what) => json(route, 400, { error: { code: 'invalid', message: what } });
    if (p === '/agents/api/v1/files' && req.method() === 'GET') {
      if (workDir(rel)) return json(route, 200, { path: rel, kind: 'dir', entries: workEntries(rel) });
      return work.has(rel) ? json(route, 200, { path: rel, kind: 'file', size: Buffer.byteLength(work.get(rel)), text: work.get(rel) })
        : json(route, 404, { error: { code: 'not_found', message: `${rel}: no such file or directory` } });
    }
    if (p === '/agents/api/v1/files/download' && q.getAll('path').length > 1) {
      const ps = q.getAll('path'), parents = [...new Set(ps.map((x) => x.slice(0, Math.max(0, x.lastIndexOf('/')))))];
      const name = (parents.length === 1 && parents[0].split('/').pop()) || 'work';
      if (ps.some((x) => !work.has(x) && !workDir(x))) return json(route, 404, { error: { code: 'not_found', message: 'no such file' } });
      return route.fulfill({ status: 200, contentType: 'application/zip', headers: { 'Content-Disposition': `attachment; filename="${name}.zip"` }, body: 'PK\u0005\u0006' + '\u0000'.repeat(18) });
    }
    if (p === '/agents/api/v1/files/download') {
      const name = rel.split('/').pop() || 'work';
      if (workDir(rel)) return route.fulfill({ status: 200, contentType: 'application/zip', headers: { 'Content-Disposition': `attachment; filename="${name}.zip"` }, body: 'PK\u0005\u0006' + '\u0000'.repeat(18) });
      return route.fulfill({ status: 200, contentType: 'application/octet-stream', headers: { 'Content-Disposition': `attachment; filename="${name}"` }, body: work.get(rel) });
    }
    if (p === '/agents/api/v1/files/mkdir' && req.method() === 'POST') {
      const d = body(req).path;
      if (work.has(d) || workDir(d)) return no(`'${d}' already exists`);
      work.set(d, null); return json(route, 201, { path: d });
    }
    if (p === '/agents/api/v1/files/move' && req.method() === 'POST' && Array.isArray(body(req).from)) {
      const { from, into } = body(req);
      const pairs = from.map((f) => [f, (into ? `${into}/` : '') + f.split('/').pop()]);
      for (const [f, t] of pairs) {
        if (work.has(t) || workDir(t)) return no(`'${t}' already exists`);
        if (under(into, f)) return no(`'${into}' is '${f}' itself or inside it`);
      }
      for (const [f, t] of pairs) for (const k of [...work.keys()].filter((k) => under(k, f))) { work.set(t + k.slice(f.length), work.get(k)); work.delete(k); }
      return json(route, 200, { moved: pairs.map(([f, t]) => ({ from: f, path: t })) });
    }
    if (p === '/agents/api/v1/files/move' && req.method() === 'POST') {
      const { from, to } = body(req);
      if (work.has(to) || workDir(to)) return no(`'${to}' already exists`);
      if (under(to, from)) return no(`'${to}' is '${from}' itself or inside it`);
      const moving = [...work.keys()].filter((k) => under(k, from));
      if (!moving.length) return no(`no '${from}' in the workspace`);
      for (const k of moving) { work.set(to + k.slice(from.length), work.get(k)); work.delete(k); }
      return json(route, 200, { from, path: to });
    }
    if (p === '/agents/api/v1/files' && req.method() === 'DELETE') {
      const rels = q.getAll('path').map((x) => x.replace(/^\/+|\/+$/g, ''));
      if (!rels.length || rels.some((x) => !x)) return no('the workspace itself cannot be removed');
      if (rels.some((x) => ![...work.keys()].some((k) => under(k, x)))) return no('no such entry in the workspace');
      for (const x of rels) for (const k of [...work.keys()].filter((k) => under(k, x))) work.delete(k);
      return json(route, 200, { deleted: rels.length === 1 ? rels[0] : rels });
    }
    return json(route, 404, { error: { code: 'not_found', message: 'no such api' } });
  }
  if (p.startsWith('/handbook/api/v1/')) {  // the handbook's graph: read-only, {error: {code, message}} as the handbook says it
    if (!uid) return json(route, 401, { error: { code: 'unauthorized', message: 'sign in first' } });
    const id = new URL(req.url()).searchParams.get('id') || '';
    const none = () => json(route, 404, { error: { code: 'not_found', message: `no node '${id}'` } });
    if (p.endsWith('/graph')) return json(route, 200, GRAPH.overview);
    if (p.endsWith('/graph/entry')) return GRAPH.entries[id] ? json(route, 200, { id, ...GRAPH.entries[id] }) : none();
    const n = [...GRAPH.overview.nodes, ...Object.values(GRAPH.entries).flatMap(e => e.nodes)].find(x => x.id === id);
    return n ? json(route, 200, { id, type: n.kind || n.type, state: n.state || '', author: 'model', title: n.title, name: '', content: `${n.title}\n본문`, cut: false,
                                  out: { ref: 2 }, in: { ref: 1 } }) : none();
  }
  if (p.startsWith('/board/api/v1/')) {  // the handbook's board: {error: {code, message}} as the handbook says it
    if (!uid) return json(route, 401, { error: { code: 'unauthorized', message: 'sign in first' } });
    const B = board, admin = B.admin, rest = p.slice('/board/api/v1/'.length), method = req.method();
    const no = (status, message) => json(route, status, { error: { code: { 403: 'forbidden', 404: 'not_found', 409: 'conflict' }[status] || 'invalid', message } });
    const seen = (x) => !x.hidden || x.author === uid || admin;
    const bare = ({ payload, ...x }) => x;  // eslint-disable-line no-unused-vars
    const now = () => Date.now() / 1000;
    if (rest === '' && method === 'GET') {
      return json(route, 200, { me: { uid, admin }, kinds: ['preset', 'layer'], limits: { title: 80, about: 240, notice: 4000 },
        shares: B.shares.filter(seen).sort((a, b) => b.updated - a.updated).map(bare),
        notices: [...B.notices].sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.updated - a.updated) });
    }
    if (rest === 'mine' && method === 'GET') return json(route, 200, B.mine);
    if (rest === 'shares' && method === 'POST') {
      const d = body(req);
      const item = (B.mine[d.kind] || []).find((x) => x.name === d.name && !x.why);
      if (!item) return no(404, `no such ${d.kind}: ${d.name}`);
      let x = B.shares.find((y) => y.kind === d.kind && y.name === d.name && y.author === uid);
      if (x) Object.assign(x, { title: d.title || item.title, about: d.about || '', version: x.version + 1, updated: now() });
      else {
        x = { id: `s${++B.seq}`, kind: d.kind, name: d.name, author: uid, title: d.title || item.title, about: d.about || '', version: 1, imports: 0, created: now(), updated: now(),
              hidden: false, hidden_why: null, payload: d.kind === 'preset' ? B.shares[B.shares.length - 1].payload : { script: 'echo hi\n', parents: ['sys:python@3'], env: {}, description: item.title } };
        B.shares.push(x);
      }
      return json(route, 201, bare(x));
    }
    let b;
    if ((b = /^shares\/([^/]+)(?:\/(import|hide|show))?$/.exec(rest))) {
      const x = B.shares.find((y) => y.id === b[1]);
      if (!x || !seen(x)) return no(404, '그런 공유가 없습니다.');
      if (!b[2] && method === 'GET') return json(route, 200, x);
      if (!b[2] && method === 'DELETE') {
        if (x.author !== uid && !admin) return no(403, '자기 공유만 내릴 수 있습니다.');
        B.shares.splice(B.shares.indexOf(x), 1);
        return json(route, 200, { deleted: x.id });
      }
      if (b[2] === 'import') {
        const name = String(body(req).as || x.name).trim().toLowerCase();
        if (B.mine[x.kind].some((y) => y.name === name)) return no(409, `이미 있는 프리셋 이름입니다: ${name}`);
        B.mine[x.kind].push({ name, title: x.title, why: '' });
        x.imports += 1;
        return json(route, 201, { kind: x.kind, name });
      }
      if (!admin) return no(403, '관리자만 숨길 수 있습니다.');
      if (b[2] === 'hide') {
        const why = String(body(req).why || '').trim();
        if (!why) return no(400, '숨기는 까닭 을(를) 적으세요.');
        Object.assign(x, { hidden: true, hidden_why: why });
      } else Object.assign(x, { hidden: false, hidden_why: null });
      return json(route, 200, bare(x));
    }
    if (rest === 'notices' && method === 'POST') {
      if (!admin) return no(403, '공지는 관리자가 씁니다.');
      const d = body(req);
      const n = { id: `n${++B.seq}`, title: d.title, body: d.body, author: uid, pinned: !!d.pinned, created: now(), updated: now() };
      B.notices.push(n);
      return json(route, 201, n);
    }
    if ((b = /^notices\/([^/]+)$/.exec(rest))) {
      if (!admin) return no(403, '공지는 관리자가 씁니다.');
      const n = B.notices.find((y) => y.id === b[1]);
      if (!n) return no(404, '그런 공지가 없습니다.');
      if (method === 'DELETE') { B.notices.splice(B.notices.indexOf(n), 1); return json(route, 200, { deleted: n.id }); }
      const d = body(req);
      for (const k of ['title', 'body', 'pinned']) if (d[k] !== undefined) n[k] = d[k];
      n.updated = now();
      return json(route, 200, n);
    }
    return no(404, 'no such api');
  }
  if (p === '/apps/eq-sandbox/widget.js') return file(route, EQ, 'widget.js');
  if (p.startsWith('/apps/site/')) return file(route, DIST, p.slice('/apps/site/'.length));
  if (p.startsWith('/apps/wordgen/') && process.env.WORDGEN_ROOT) return file(route, process.env.WORDGEN_ROOT, p.slice('/apps/wordgen/'.length) || 'index.html');
  if (p.startsWith('/apps/eq-sandbox/')) return route.fulfill({ status: 200, contentType: TYPES['.html'], body: '<!doctype html><html><head><script src="/auth/static/theme.js"></script><link rel="stylesheet" href="/auth/static/style.css"></head><body><header><a class="brand" id="brand" href="/"></a><nav id="nav"></nav></header><main id="main"><h1>eq</h1></main><script type="module">import { load, header } from "/auth/static/site.js"; await load(); header(); document.body.dataset.ready = "1";</script></body></html>' });
  if (PAGES.includes(p) || p.startsWith('/account/') || p.startsWith('/app/') || p.startsWith('/vault/') || p.startsWith('/projects/') || p.startsWith('/agents/')) return file(route, DIST, 'index.html');
  return route.fulfill({ status: 404, body: 'not found' });
}

module.exports = {
  ORIGIN,
  addCard: card => extraCards.push(card),
  install: (context) => context.route(`${ORIGIN}/**`, handle),
  reset,
  signOut: () => { uid = null; },
  put: (app, key, value) => { store[app].set(key, JSON.stringify(app === 'site' && key === 'prefs' ? { guides: GUIDES, ...value } : value)); },
  get: (app, key) => { const v = store[app].get(key); return v === undefined ? undefined : JSON.parse(v); },
  events: () => events.slice(),
  tasks: () => tasks.slice(),
  vaults: () => vaults.slice(),
  calendars: () => calendars.slice(),
  files: () => files,
  work: () => work,
  resetWork,
  setFile: (rel, text) => { files.set(rel, { text, mtime: Date.now() / 1000 }); },
  devices: () => devices.slice(),
  slowLinks: (ms) => { slowLinks = ms; },
  board: () => board,
  boardAdmin: (on) => { board.admin = on; },
};
