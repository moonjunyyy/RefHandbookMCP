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

const store = { site: new Map(), 'eq-sandbox': new Map() };
const W = (app) => `/apps/site/widgets/${app}.js`;
const CARDS = [
  { id: 'account', title: '계정', description: '내 프로필과 비밀번호', about: '프로필과 비밀번호를 고칩니다.', tags: [], code: '', icon: '👤', href: '/account/', optional: false,
    links: [{ label: '내 계정', href: '/account/' }, { label: '사용자 관리', href: '/account/admin/users' }], widgets: [] },
  { id: 'projects', title: '프로젝트', description: '함께 쓰는 그룹', about: '프로젝트는 사람들이 직접 만드는 그룹입니다.', tags: ['자료'], code: '', icon: '🧩', href: '/projects', optional: true,
    links: [{ label: '프로젝트', href: '/projects' }], widgets: [{ id: 'mine', title: '내 프로젝트', href: W('projects'), size: '1x1' }] },
  { id: 'calendar', title: '캘린더', description: '내 일정과 프로젝트 일정을 한 달력에', about: '내 캘린더와 프로젝트의 캘린더를 한 달력에 겹쳐 봅니다. 구독 주소를 폰에 넣을 수 있습니다.', tags: ['일정'], code: '', icon: '📅', href: '/calendar', optional: true,
    links: [{ label: '캘린더', href: '/calendar' }], widgets: [{ id: 'today', title: '오늘', href: W('calendar'), size: '2x1' }, { id: 'upcoming', title: '다가오는 일', href: W('calendar'), size: '1x1' }] },
  { id: 'vault', title: '노트', description: 'Obsidian 볼트를 브라우저에서', about: '내 저장소의 마크다운 볼트를 읽고 고칩니다. 검색, 백링크, 최근 노트.', tags: ['글쓰기', '연구'], code: '', icon: '📝', href: '/vault', optional: true,
    links: [{ label: '노트', href: '/vault' }], widgets: [{ id: 'recent', title: '최근 노트', href: W('vault'), size: '1x1' }, { id: 'home', title: 'Home', href: W('vault'), size: '2x2' }] },
  { id: 'eq-sandbox', title: '수식 플립플롭', description: '수식을 블록처럼 뒤집고 옮기는 작업판', about: '방정식의 항을 끌어 옮기고 뒤집어 정리합니다.', tags: ['연구', '도구'], code: '', icon: '🧮', href: '/apps/eq-sandbox/', optional: true,
    links: [{ label: '열기', href: '/apps/eq-sandbox/' }], widgets: [{ id: 'boards', title: '최근 작업판', href: '/apps/eq-sandbox/widget.js', size: '1x1' }] },
  { id: 'wordgen', title: '글타래', description: '소설을 위한 키워드와 집필 메모', about: '무작위 키워드로 이야기를 틔웁니다.', tags: ['글쓰기'], code: '', icon: '✍️', href: '/apps/wordgen/', optional: true,
    links: [{ label: '열기', href: '/apps/wordgen/' }], widgets: [] },
  { id: 'agents', title: '에이전트', description: '내 API 키로 돌리는 에이전트 팀과 샌드박스', about: '에이전트 팀을 실행합니다.', tags: ['AI', '도구'], code: '', icon: '🤖', href: '/agents/', optional: true,
    links: [{ label: '에이전트 실행', href: '/agents/' }, { label: '프리셋', href: '/agents/presets' }], widgets: [] },
];
const PAGES = ['/', '/apps', '/settings', '/account', '/account/', '/agents', '/agents/', '/calendar', '/vault', '/projects'];
let uid = 'tester';

// ── the calendar, in memory ───────────────────────────────────────────────
let calendars, events, feeds, seq;
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

function reset() {
  for (const s of Object.values(store)) s.clear();
  uid = 'tester';
  calendars = [{ id: 'u-1', owner: 'tester', kind: 'user', name: '내 캘린더', color: '', main: true, created: 1 },
               { id: 'g-1', owner: 'lab', kind: 'group', name: 'lab', color: '#33aa55', main: true, created: 2 }];
  events = []; feeds = []; seq = 0;
  vaults = [{ id: 'v1', name: 'Research', path: '/data/tester/Research', status: 'ok', created: 1 }];
  files = new Map([
    ['Home.md', { text: '# Home\n\nStart at [[Ideas/Operators]] and [[Lie algebras|the algebras]]. An operator $T$ acts. #math\n\n$$\\int_0^1 x\\,dx = \\tfrac12$$\n', mtime: 3 }],
    ['Ideas/Operators.md', { text: '# Operators\n\nSee [[Home]] and [[Missing note]]. #draft\n', mtime: 2 }],
    ['Lie algebras.md', { text: 'The algebras: $[x, y]$, a bracket. Back to [[Ideas/Operators#Chain]].\n', mtime: 1 }],
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
  if (p === '/auth/api/v1/me') {
    const theme = ['light', 'dark'].includes(cookie(req, 'theme')) ? cookie(req, 'theme') : 'auto';
    return json(route, 200, { uid, title: '모의 사이트', signin: '/auth', portal: '/account', lang: 'ko', theme, frame: 1, cards: CARDS, menu: [] });
  }
  if (p.startsWith('/auth/static/')) return file(route, STATIC, p.slice('/auth/static/'.length));
  let m;
  if ((m = /^\/apps\/(site|eq-sandbox)\/api\/store(?:\/([a-z0-9_.-]{1,64}))?$/.exec(p))) {
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
    if (rest === 'calendars') return json(route, 200, { calendars, projects: ['lab'] });
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
    if (rest === 'vaults' && req.method() === 'POST') { const v = { id: `v${vaults.length + 1}`, name: body(req).name || 'x', path: body(req).path, status: 'ok', created: 2 }; vaults.push(v); return json(route, 201, v); }
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
      if (what === 'links') { const own = links((files.get(rel) || { text: '' }).text).map((x) => ({ path: resolve(x), text: x })); const back = [...files].filter(([src, f]) => src !== rel && links(f.text).some((x) => resolve(x) === rel)).map(([src]) => src).sort(); return json(route, 200, { path: rel, links: own, backlinks: back }); }
      if (what === 'recent') return json(route, 200, { notes: [...files].filter(([k]) => k.endsWith('.md')).sort((a, b) => b[1].mtime - a[1].mtime).slice(0, +(q.get('n') || 10)).map(([k, f]) => ({ path: k, title: k.split('/').pop().replace(/\.md$/, ''), mtime: f.mtime, size: f.text.length })) });
      if (what === 'raw') return route.fulfill({ status: 404, body: 'not found' });
    }
    return json(route, 404, { error: 'no such api' });
  }
  if (p === '/apps/eq-sandbox/widget.js') return file(route, EQ, 'widget.js');
  if (p.startsWith('/apps/site/')) return file(route, DIST, p.slice('/apps/site/'.length));
  if (p.startsWith('/apps/eq-sandbox/')) return route.fulfill({ status: 200, contentType: TYPES['.html'], body: '<!doctype html><html><head><script src="/auth/static/theme.js"></script><link rel="stylesheet" href="/auth/static/style.css"></head><body><header><a class="brand" id="brand" href="/"></a><nav id="nav"></nav></header><main id="main"><h1>eq</h1></main><script type="module">import { load, header } from "/auth/static/site.js"; await load(); header(); document.body.dataset.ready = "1";</script></body></html>' });
  if (PAGES.includes(p) || p.startsWith('/account/') || p.startsWith('/app/') || p.startsWith('/vault/') || p.startsWith('/projects/')) return file(route, DIST, 'index.html');
  return route.fulfill({ status: 404, body: 'not found' });
}

module.exports = {
  ORIGIN,
  install: (context) => context.route(`${ORIGIN}/**`, handle),
  reset,
  signOut: () => { uid = null; },
  put: (app, key, value) => { store[app].set(key, JSON.stringify(value)); },
  get: (app, key) => { const v = store[app].get(key); return v === undefined ? undefined : JSON.parse(v); },
  events: () => events.slice(),
  files: () => files,
  setFile: (rel, text) => { files.set(rel, { text, mtime: Date.now() / 1000 }); },
};
