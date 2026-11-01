// The notes (/vault, /vault/<vault>/<path>): a person's markdown vaults — the directories Obsidian opens —
// read and written here (docs/apps-vault-calendar.md §4.3). The first thing on the page is the note (Home
// when there is one); beside it the tree, with a search above it and "new note" as its last row. The
// note's head holds its path, the view/edit switch and its backlinks. Editing is in place: a text area
// and one button; the service refuses a save over a change made elsewhere (docs/vault.md), which shows
// as one line. With no vault yet, the page is the thing to do: add one.

import { api, button, choice, dialog, empty, flash, frame, go, h, link, main, message, pageHead, primaryLink, replace, title, toggle } from '/auth/static/site.js';
import type { Json } from '/auth/static/site.js';
import { t } from '../lib/i18n';

const vaults = api('/vault/api/v1');
const LAST = 'vault.last';  // the vault this browser opened last
const HOME = 'Home.md';

export const noteHref = (vid: string, path: string) => `/vault/${vid}/${path.split('/').map(encodeURIComponent).join('/')}`;
const rawHref = (vid: string, path: string) => `/vault/api/v1/vaults/${vid}/raw?path=${encodeURIComponent(path)}`;

/** Add a vault: a directory of the person's storage, by its path. True when one was added. */
async function addVault(roots: string[]): Promise<boolean> {
  const path = h('input', { type: 'text', name: 'path', required: true, placeholder: roots[0] ? `${roots[0]}/Obsidian/Research` : '', autofocus: true });
  const name = h('input', { type: 'text', name: 'name', maxlength: 60, placeholder: t('볼트 이름 (비우면 폴더 이름)') });
  const ok = await dialog(t('볼트 추가'), h('div', { class: 'fields' },
    h('label', null, t('폴더 경로'), path, h('span', { class: 'muted small' }, roots.map((r, i) => [i > 0 && ', ', h('code', null, r)]))),
    h('label', null, t('이름'), name)), { ok: t('추가') });
  if (!ok || !path.value.trim()) return false;
  await vaults.post('/vaults', { path: path.value.trim(), name: name.value.trim() });
  return true;
}

/** Every note of a tree, flat: [path, name]. */
function notesOf(node: Json, out: [string, string][] = []): [string, string][] {
  for (const c of node.children ?? []) {
    if (c.type === 'dir') notesOf(c, out);
    else if (c.type === 'note' || c.type === 'text') out.push([c.path, c.name]);
  }
  return out;
}

export async function vault(vid = '', path = ''): Promise<void> {
  title(t('노트'));
  if (!frame.uid) {
    replace(main(), pageHead(t('노트')), h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/vault`, t('로그인'))));
    return;
  }
  const listed: Json = await vaults.get('/vaults');
  const have: Json[] = listed.vaults;
  if (!have.length) {  // nothing yet: adding one is the page
    replace(main(), pageHead(t('노트')), h('p', { class: 'actions' },
      button(t('볼트 추가'), async () => { if (await addVault(listed.roots)) await vault(); })));
    return;
  }
  let last = '';
  try { last = localStorage.getItem(LAST) ?? ''; } catch { /* storage may be off */ }
  const current: Json = have.find(v => v.id === vid) ?? have.find(v => v.id === last) ?? have[0];
  try { localStorage.setItem(LAST, current.id); } catch { /* storage may be off */ }
  const v = api(`/vault/api/v1/vaults/${current.id}`);
  if (current.status !== 'ok') {
    replace(main(), pageHead(t('노트')), vaultChips(), empty(current.status === 'pending' ? t('볼트를 준비하는 중입니다. 잠시 뒤 다시 여세요.') : current.status));
    return;
  }

  const tree: Json = await v.get('/tree');
  const notes = notesOf(tree);
  const paths = new Set(notes.map(([p]) => p));
  const md = await import('../lib/markdown');
  const render = md.renderer({
    note: target => {
      const name = target.replace(/^\/+|\/+$/g, '');
      for (const cand of [name, `${name}.md`]) if (paths.has(cand)) return noteHref(current.id, cand);
      const tail = `${name.split('/').pop()!.toLowerCase()}.md`;
      const hit = notes.find(([p]) => p.split('/').pop()!.toLowerCase() === tail);
      return hit ? noteHref(current.id, hit[0]) : null;
    },
    raw: p => rawHref(current.id, p.replace(/^\/+/, '')),
  });

  const aside = h('aside', { class: 'vault-side' });
  const article = h('article', { class: 'note' });
  let opened: Json | null = null;  // {path, text, sha256}
  let editing = false;
  let folder = '';

  function vaultChips(): HTMLElement | false {
    return have.length > 1 && choice(have.map(x => [x.id, x.name] as [string, string]), current.id, id => go(`/vault/${id}`), { 'aria-label': t('볼트') });
  }

  function treeList(node: Json): HTMLElement {
    return h('ul', { class: 'tree' }, (node.children ?? []).map((c: Json) => c.type === 'dir'
      ? h('li', null, h('details', { open: !!opened && opened.path.startsWith(c.path + '/') }, h('summary', null, c.name), treeList(c)))
      : c.type === 'note' || c.type === 'text'
        ? h('li', { class: opened?.path === c.path ? 'current' : null }, link(noteHref(current.id, c.path), c.type === 'note' ? c.name.replace(/\.md$/, '') : c.name))
        : h('li', { class: 'muted' }, h('a', { href: rawHref(current.id, c.path), target: '_blank', rel: 'noopener' }, c.name))));
  }

  function drawSide(hits?: Json[]): void {
    const search = h('input', { type: 'search', placeholder: t('노트 찾기'), 'aria-label': t('노트 찾기'),
                                value: (aside.querySelector('input[type=search]') as HTMLInputElement | null)?.value ?? '' });
    let timer = 0;
    search.addEventListener('input', () => {
      window.clearTimeout(timer);
      const q = search.value.trim();
      timer = window.setTimeout(async () => {
        if (!q) { drawSide(); return; }
        try { drawSide((await v.get(`/search?q=${encodeURIComponent(q)}`)).hits); } catch (e) { flash('error', message(e)); }
      }, 250);
    });
    replace(aside,
      vaultChips(),
      search,
      hits ? h('ul', { class: 'tree hits' }, hits.length ? hits.map(x => h('li', null, link(noteHref(current.id, x.path), x.title),
                                                                           h('p', { class: 'snippet small muted' }, x.snippet))) : h('li', { class: 'muted' }, t('없음')))
           : [treeList(tree), h('p', { class: 'tree-foot' }, button(t('새 노트'), newNote, 'link'), ' ',
                                button(t('볼트 추가'), async () => { if (await addVault(listed.roots)) await vault(current.id, opened?.path ?? ''); }, 'link'))]);
    const again = aside.querySelector('input[type=search]') as HTMLInputElement | null;
    if (hits && again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
  }

  async function newNote(): Promise<void> {
    const name = h('input', { type: 'text', required: true, value: folder ? `${folder}/` : '', autofocus: true });
    const ok = await dialog(t('새 노트'), h('div', { class: 'fields' }, h('label', null, t('이름 (폴더/이름)'), name)), { ok: t('만들기') });
    if (!ok) return;
    let p = name.value.trim().replace(/^\/+|\/+$/g, '');
    if (!p) return;
    if (!/\.\w+$/.test(p)) p += '.md';
    try {
      await v.put(`/file?path=${encodeURIComponent(p)}`, { text: `# ${p.split('/').pop()!.replace(/\.md$/, '')}\n\n` });
      go(noteHref(current.id, p));
    } catch (e) { flash('error', message(e)); }
  }

  async function backlinks(): Promise<HTMLElement> {
    try {
      const r = await v.get(`/links?path=${encodeURIComponent(opened!.path)}`);
      const list: string[] = r.backlinks;
      return h('details', { class: 'help backlinks' }, h('summary', null, t('백링크 {n}', { n: list.length })),
        list.length ? h('ul', { class: 'plain' }, list.map(p => h('li', null, link(noteHref(current.id, p), p.replace(/\.md$/, ''))))) : empty(t('없음')));
    } catch { return h('span'); }
  }

  async function drawNote(): Promise<void> {
    if (!opened) {
      replace(article, empty(t('노트가 없습니다.')), h('p', { class: 'actions' }, button(t('새 노트'), newNote)));
      return;
    }
    const o = opened;
    const head = h('div', { class: 'note-head' },
      h('h1', null, o.path.replace(/\.md$/, '')),
      h('span', { class: 'actions' },
        toggle(t('편집'), editing, async on => { editing = on; await drawNote(); }),
        await backlinks()));
    if (!editing) {
      const body = h('div', { class: 'note-body' });
      body.innerHTML = o.path.endsWith('.md') ? render(o.text) : `<pre class="wrap"></pre>`;
      if (!o.path.endsWith('.md')) body.querySelector('pre')!.textContent = o.text;
      replace(article, head, body);
      return;
    }
    const area = h('textarea', { class: 'editor', spellcheck: false, 'aria-label': o.path }, o.text);
    const saved = h('span', { class: 'muted small', role: 'status' });
    // the hash the note was read with goes along: a change made elsewhere is refused, never overwritten
    const save = button(t('저장'), async () => {
      const r = await fetchPut(`/file?path=${encodeURIComponent(o.path)}`, { text: area.value }, o.sha256);
      o.text = area.value; o.sha256 = r.sha256;
      replace(saved, t('저장됨 {time}', { time: new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }));
    });
    area.addEventListener('keydown', ev => { if ((ev.metaKey || ev.ctrlKey) && ev.key === 's') { ev.preventDefault(); save.click(); } });
    replace(article, head, area, h('p', { class: 'actions' }, save, ' ', saved, ' ', button(t('지우기'), async () => {
      if (!await dialog(t('노트 지우기'), h('p', null, o.path), { ok: t('지우기'), danger: true })) return;
      await v.del(`/file?path=${encodeURIComponent(o.path)}`);
      go(`/vault/${current.id}`);
    }, 'danger')));
    area.focus();
  }

  async function fetchPut(p: string, body: unknown, sha: string): Promise<Json> {
    const r = await fetch(`/vault/api/v1/vaults/${current.id}${p}`, { method: 'PUT', credentials: 'same-origin', body: JSON.stringify(body),
                                                                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch', 'If-Match': sha } });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error ?? t('요청이 실패했습니다 ({status})', { status: r.status }));
    return data;
  }

  async function open(p: string): Promise<void> {
    editing = false;
    if (!p) p = paths.has(HOME) ? HOME : (notes[0]?.[0] ?? '');
    if (!p) { opened = null; folder = ''; drawSide(); await drawNote(); return; }
    try {
      opened = await v.get(`/file?path=${encodeURIComponent(p)}`);
    } catch (e) {
      flash('error', message(e));
      opened = null;
    }
    folder = p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '';
    title(`${p.replace(/\.md$/, '')} · ${t('노트')}`);
    drawSide();
    await drawNote();
  }

  replace(main(), h('div', { class: 'vault' }, aside, article));
  await open(path);
}
