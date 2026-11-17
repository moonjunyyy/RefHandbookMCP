// The notes (/vault, /vault/<vault>/<path>): a person's markdown vaults — the directories Obsidian opens —
// read and written here (docs/apps-vault-calendar.md §4.3, §7.5). The first thing on the page is the
// note (Home when there is one); beside it the tree, with a search above it, "new note" at its head and
// the vault's menu (⋯: rename, its path, retry, take it off, add another). The note's head holds its
// path, the view/edit switch, its backlinks and its menu (rename or move, the file itself, delete); every
// row of the tree has one too (R10). Editing is in place: a text area and one button; the service refuses
// a save over a change made elsewhere (docs/vault.md), which shows as one line. With no vault yet, the
// page is the thing to do: add one — a folder inside the storage the site offers, chosen from its roots.
// A vault that is not ready is a card: its standing, why, and what to do next (R11).

import { api, button, choice, dialog, empty, flash, frame, go, h, help, keys, main, menuButton, message, onMenu, pageHead, primaryLink, replace, tag, title, toggle } from '/auth/static/site.js';
import type { Json, MenuSection } from '/auth/static/site.js';
import { n_, t } from '../lib/i18n';
import { copyText } from '../lib/clipboard';
import { canLeave, watchDraft } from '../lib/navigation';

const vaults = api('/vault/api/v1');
const LAST = 'vault.last';  // the vault this browser opened last
const HOME = 'Home.md';

export const noteHref = (vid: string, path: string) => `/vault/${vid}/${path.split('/').map(encodeURIComponent).join('/')}`;
const rawHref = (vid: string, path: string) => `/vault/api/v1/vaults/${vid}/raw?path=${encodeURIComponent(path)}`;

/** Add a vault: a folder inside one of the roots the site offers (the person's storage), by the rest of
 * its path. True when one was added. */
async function addVault(roots: string[]): Promise<boolean> {
  const root = roots.length > 1
    ? h('select', { name: 'root' }, roots.map(r => h('option', { value: r }, r)))
    : h('code', { class: 'root' }, roots[0] ?? '');
  const sub = h('input', { type: 'text', name: 'sub', required: true, placeholder: 'Obsidian/Research', autofocus: true });
  const name = h('input', { type: 'text', name: 'name', maxlength: 60, placeholder: t('볼트 이름 (비우면 폴더 이름)') });
  const body = h('div', { class: 'fields' },
    h('p', { class: 'small' }, t('내 저장소 안의 폴더가 볼트입니다 — Obsidian 이 여는 그 폴더. 아래 자리 안의 경로를 적으세요.')),
    h('label', null, t('어디의'), root),
    h('label', null, t('폴더 (그 안의 경로)'), sub),
    h('label', null, t('이름'), name));
  const ok = await dialog(t('볼트 추가'), body, { ok: t('추가') });
  if (!ok) return false;
  const rel = sub.value.trim().replace(/^\/+|\/+$/g, '');
  if (!rel) { flash('error', t('폴더의 경로를 적으세요.')); return false; }
  const base = roots.length > 1 ? (root as HTMLSelectElement).value : roots[0] ?? '';
  await vaults.post('/vaults', { path: base ? `${base}/${rel}` : rel, name: name.value.trim() });
  return true;
}

/** Call a vault something else. True when renamed. */
async function renameVault(v: Json): Promise<boolean> {
  const name = h('input', { type: 'text', name: 'name', required: true, maxlength: 60, value: v.name, autofocus: true });
  const ok = await dialog(t('볼트 이름'), h('div', { class: 'fields' }, h('label', null, t('이름'), name)), { ok: t('저장') });
  if (!ok || !name.value.trim()) return false;
  await vaults.patch(`/vaults/${v.id}`, { name: name.value.trim() });
  return true;
}

/** Take a vault off the list (the files stay where they are). True when taken off. */
async function removeVault(v: Json): Promise<boolean> {
  if (!await dialog(t('볼트 빼기'), h('p', null, t('{name} 을(를) 목록에서 뺍니다. 파일은 그대로 남습니다.', { name: v.name }), ' ', h('code', null, v.path)),
                    { ok: t('빼기'), danger: true })) return false;
  await vaults.del(`/vaults/${v.id}`);
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

const STATUS: Record<string, [string, string]> = { pending: [n_('준비 중'), 'warn'], error: [n_('오류'), 'bad'], ok: [n_('준비됨'), 'ok'] };

export async function vault(vid = '', path = ''): Promise<void> {
  title(t('노트'));
  keys([]);
  if (!frame.uid) {
    replace(main(), pageHead(t('노트')), h('p', { class: 'actions' }, primaryLink(`${frame.signin}/login?next=/vault`, t('로그인'))));
    return;
  }
  const listed: Json = await vaults.get('/vaults');
  const have: Json[] = listed.vaults;
  const roots: string[] = listed.roots ?? [];
  if (!have.length) {  // nothing yet: adding one is the page
    replace(main(), pageHead(t('노트')),
      h('p', { class: 'actions' }, button(t('볼트 추가'), async () => { if (await addVault(roots)) await vault(); }),
        help(t('볼트는 내 저장소 안의 폴더입니다 — Obsidian 이 여는 그 폴더. 하나 등록하면 여기서 읽고 씁니다.'))));
    return;
  }
  let last = '';
  try { last = localStorage.getItem(LAST) ?? ''; } catch { /* storage may be off */ }
  const current: Json = have.find(v => v.id === vid) ?? have.find(v => v.id === last) ?? have[0];
  try { localStorage.setItem(LAST, current.id); } catch { /* storage may be off */ }
  const v = api(`/vault/api/v1/vaults/${current.id}`);
  let opened: Json | null = null;  // {path, text, sha256}
  let editing = false;
  let folder = '';

  /** The vault's own actions (R10): its name, its path, a retry, taking it off; and another one. */
  const vaultMenu = (): MenuSection[] => [
    { title: current.name, items: [
      { label: t('이름 바꾸기…'), run: async () => { if (await renameVault(current)) await vault(current.id, opened?.path ?? ''); } },
      { label: t('경로'), detail: current.path, run: () => copyText(current.path) },
      { label: t('다시 시도'), detail: t('폴더를 고친 뒤'), disabled: current.status === 'ok', run: async () => { await vaults.post(`/vaults/${current.id}/retry`); await vault(current.id); } },
      { label: t('볼트 빼기'), danger: true, detail: t('파일은 남습니다'), run: async () => { if (await removeVault(current)) { try { localStorage.removeItem(LAST); } catch { /* off */ } await vault(); } } } ] },
    { items: [{ label: t('볼트 추가…'), run: async () => { if (await addVault(roots)) await vault(current.id, opened?.path ?? ''); } }] }];

  function vaultHead(): HTMLElement {
    return h('div', { class: 'vault-head' },
      have.length > 1 ? choice(have.map(x => [x.id, x.name] as [string, string]), current.id, id => go(`/vault/${id}`), { 'aria-label': t('볼트') })
        : h('span', { class: 'vault-name' }, current.name),
      menuButton(vaultMenu, t('볼트 설정')));
  }

  if (current.status !== 'ok') {  // not ready: the card says where it stands and what to do (R11)
    const [word, kind] = STATUS[current.status] ?? STATUS.error;
    replace(main(), pageHead(t('노트')), vaultHead(),
      h('div', { class: 'card vault-status' },
        h('div', { class: 'item-head' }, h('h2', null, current.name), tag(t(word), kind)),
        h('p', { class: 'vault-path' }, h('code', null, current.path)),
        h('p', { class: 'reason' }, current.reason || t('볼트를 준비하는 중입니다. 잠시 뒤 다시 여세요.')),
        h('p', { class: 'actions' },
          button(t('다시 시도'), async () => { await vaults.post(`/vaults/${current.id}/retry`); await vault(current.id); }),
          button(t('이름 바꾸기'), async () => { if (await renameVault(current)) await vault(current.id); }, 'secondary'),
          button(t('볼트 빼기'), async () => { if (await removeVault(current)) { try { localStorage.removeItem(LAST); } catch { /* off */ } await vault(); } }, 'secondary'),
          button(t('다른 볼트 추가'), async () => { if (await addVault(roots)) await vault(); }, 'link'))));
    return;
  }

  const tree: Json = await v.get('/tree');
  const notes = notesOf(tree);
  const paths = new Set(notes.map(([p]) => p));
  // a bare [[name]] is the first note of that name: looked up, not searched for among every note at every link
  const byName = new Map<string, string>();
  for (const [p] of notes) { const name = p.split('/').pop()!.toLowerCase(); if (!byName.has(name)) byName.set(name, p); }
  const md = await import('../lib/markdown');  // markdown-it; KaTeX comes with the first note that has mathematics
  const render = md.renderer({
    note: target => {
      const name = target.replace(/^\/+|\/+$/g, '');
      for (const cand of [name, `${name}.md`]) if (paths.has(cand)) return noteHref(current.id, cand);
      const hit = byName.get(`${name.split('/').pop()!.toLowerCase()}.md`);
      return hit ? noteHref(current.id, hit) : null;
    },
    raw: p => rawHref(current.id, p.replace(/^\/+/, '')),
  });

  const aside = h('aside', { class: 'vault-side' });
  const article = h('article', { class: 'note' });

  /** Rename or move a note: its new path (folder/name). */
  async function moveNote(p: string): Promise<void> {
    const to = h('input', { type: 'text', required: true, value: p, autofocus: true });
    const ok = await dialog(t('이름 바꾸기·옮기기'), h('div', { class: 'fields' }, h('label', null, t('새 경로 (폴더/이름)'), to)), { ok: t('옮기기') });
    if (!ok) return;
    let q = to.value.trim().replace(/^\/+|\/+$/g, '');
    if (!q || q === p) return;
    if (p.endsWith('.md') && !/\.\w+$/.test(q)) q += '.md';
    if (dirty() && !await leaveEditor()) return;
    try { await v.post('/move', { from: p, to: q }); go(noteHref(current.id, q)); } catch (e) { flash('error', message(e)); }
  }

  async function trashNote(p: string): Promise<void> {
    if (!await dialog(t('노트 지우기'), h('p', null, p, ' ', h('span', { class: 'muted small' }, t('(.trash 로 옮깁니다)'))), { ok: t('지우기'), danger: true })) return;
    try { await v.del(`/file?path=${encodeURIComponent(p)}`); go(opened?.path === p ? `/vault/${current.id}` : location.pathname); } catch (e) { flash('error', message(e)); }
  }

  /** A note's actions, at the note and at its row in the tree. */
  const noteMenu = (p: string, here = false): MenuSection[] => [{ title: p.replace(/\.md$/, ''), items: [
    ...(here ? [] : [{ label: t('열기'), run: () => go(noteHref(current.id, p)) }]),
    { label: t('이름 바꾸기·옮기기…'), run: () => moveNote(p) },
    { label: t('파일 열기'), detail: t('원본, 새 탭'), run: () => { window.open(rawHref(current.id, p), '_blank', 'noopener'); } },
    { label: t('지우기'), danger: true, detail: '.trash', run: () => trashNote(p) } ] }];

  const folderMenu = (dir: string): MenuSection[] => [{ title: dir, items: [
    { label: t('여기에 새 노트…'), run: () => newNote(dir) } ] }];

  function treeList(node: Json): HTMLElement {
    return h('ul', { class: 'tree' }, (node.children ?? []).map((c: Json) => c.type === 'dir'
      ? h('li', null, h('details', { open: !!opened && opened.path.startsWith(c.path + '/') },
          onMenu(h('summary', null, c.name), () => folderMenu(c.path)), treeList(c)))
      : c.type === 'note' || c.type === 'text'
        ? onMenu(h('li', { class: opened?.path === c.path ? 'current' : null, 'data-path': c.path },
            h('a', { href: noteHref(current.id, c.path) }, c.type === 'note' ? c.name.replace(/\.md$/, '') : c.name)), () => noteMenu(c.path))
        : h('li', { class: 'muted' }, h('a', { href: rawHref(current.id, c.path), target: '_blank', rel: 'noopener' }, c.name))));
  }

  /** The tree stays as drawn; opening another note only moves the mark (and opens its folder). */
  function markCurrent(): void {
    for (const li of aside.querySelectorAll<HTMLElement>('ul.tree li.current')) li.classList.remove('current');
    if (!opened) return;
    const li = aside.querySelector<HTMLElement>(`ul.tree li[data-path="${CSS.escape(opened.path)}"]`);
    if (!li) return;
    li.classList.add('current');
    for (let d = li.parentElement?.closest('details'); d; d = d.parentElement?.closest('details')) d.open = true;
  }

  const search = h('input', { type: 'search', placeholder: t('노트 찾기'), 'aria-label': t('노트 찾기') });
  const found = h('div');
  let timer = 0, queryVersion = 0;
  search.addEventListener('input', () => {
    const version = ++queryVersion;
    window.clearTimeout(timer);
    const q = search.value.trim();
    if (!q) { drawTree(); return; }
    timer = window.setTimeout(async () => {
      try {
        const { hits } = await v.get('/search?q=' + encodeURIComponent(q));
        if (version !== queryVersion || !found.isConnected) return;
        replace(found, h('ul', { class: 'tree hits' }, hits.length ? hits.map((x: Json) => h('li', null,
          h('a', { href: noteHref(current.id, x.path) }, x.title), h('p', { class: 'snippet small muted' }, x.snippet)))
          : h('li', { class: 'muted' }, t('없음'))));
      } catch (e) { if (version === queryVersion && found.isConnected) flash('error', message(e)); }
    }, 250);
  });
  function drawTree(): void {
    replace(found, treeList(tree));
  }
  replace(aside, vaultHead(), search,
    h('p', { class: 'tree-head' }, button(t('새 노트'), () => newNote(folder), 'secondary')), found);
  drawTree();
  // ?q=… opens the page on a search (the main page's tags widget leads here with a tag)
  const asked = new URLSearchParams(location.search).get('q');
  if (asked) { search.value = asked; search.dispatchEvent(new Event('input')); }

  async function newNote(dir = ''): Promise<void> {
    const name = h('input', { type: 'text', required: true, value: dir ? `${dir}/` : '', autofocus: true });
    const ok = await dialog(t('새 노트'), h('div', { class: 'fields' }, h('label', null, t('이름 (폴더/이름)'), name)), { ok: t('만들기') });
    if (!ok) return;
    let p = name.value.trim().replace(/^\/+|\/+$/g, '');
    if (!p) return;
    if (!/\.\w+$/.test(p)) p += '.md';
    if (dirty() && !await leaveEditor()) return;
    try {
      await v.put(`/file?path=${encodeURIComponent(p)}`, { text: `# ${p.split('/').pop()!.replace(/\.md$/, '')}\n\n` });
      go(noteHref(current.id, p));
    } catch (e) { flash('error', message(e)); }
  }

  /** The backlinks, filled into their slot once the service answers — the note never waits for them (§8.2). */
  function backlinks(slot: HTMLElement, path: string): void {
    v.get(`/links?path=${encodeURIComponent(path)}`).then(r => {
      if (opened?.path !== path) return;  // another note meanwhile
      const list: string[] = r.backlinks;
      replace(slot, h('details', { class: 'help backlinks' }, h('summary', null, t('백링크 {n}', { n: list.length })),
        list.length ? h('ul', { class: 'plain' }, list.map(p => h('li', null, h('a', { href: noteHref(current.id, p) }, p.replace(/\.md$/, ''))))) : empty(t('없음'))));
    }).catch(() => { /* the links are a convenience: the note stands without them */ });
  }

  let area: HTMLTextAreaElement | null = null;
  const dirty = () => !!(editing && area && opened && area.value !== opened.text);

  /** Leave the editor: back to the view; a change not yet saved asks first. */
  async function leaveEditor(): Promise<boolean> {
    if (!editing) return true;
    if (dirty() && !await dialog(t('저장하지 않은 변경'), h('p', null, t('저장하지 않고 보기로 돌아갑니다.')), { ok: t('돌아가기'), danger: true })) return false;
    editing = false;
    await drawNote();
    return true;
  }

  async function drawNote(): Promise<void> {
    if (!opened) {
      replace(article, empty(t('노트가 없습니다.')), h('p', { class: 'actions' }, button(t('새 노트'), () => newNote(folder))));
      return;
    }
    const o = opened;
    const links = h('span', { class: 'backlinks-slot' });
    const editorToggle = toggle(t('편집'), editing, async on => {
      if (on) { editing = true; await drawNote(); }
      else if (!await leaveEditor()) editorToggle.querySelector('input')!.checked = true;
    });
    const head = onMenu(h('div', { class: 'note-head' },
      h('h1', null, o.path.replace(/\.md$/, '')),
      h('span', { class: 'actions' },
        editorToggle,
        links,
        menuButton(() => noteMenu(o.path, true)))), () => noteMenu(o.path, true));
    backlinks(links, o.path);
    if (!editing) {
      area = null;
      const body = h('div', { class: 'note-body' });
      if (o.path.endsWith('.md') && md.hasMath(o.text)) await md.loadMath();  // KaTeX, the first time a note needs it
      if (opened !== o || editing) return;
      body.innerHTML = o.path.endsWith('.md') ? render(o.text) : `<pre class="wrap"></pre>`;
      if (!o.path.endsWith('.md')) body.querySelector('pre')!.textContent = o.text;
      replace(article, head, body);
      return;
    }
    const ta = h('textarea', { class: 'editor', spellcheck: false, 'aria-label': o.path }, o.text);
    area = ta;
    const saved = h('span', { class: 'muted small', role: 'status' });
    // the hash the note was read with goes along: a change made elsewhere is refused, never overwritten
    const save = button(t('저장'), async () => {
      const submitted = ta.value;
      const r = await fetchPut(`/file?path=${encodeURIComponent(o.path)}`, { text: submitted }, o.sha256);
      o.text = submitted; o.sha256 = r.sha256;
      if (ta.value !== submitted) { replace(saved, t('아직 저장하지 않은 변경이 있습니다.')); return; }
      replace(saved, t('저장됨 {time}', { time: new Date().toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }));
    });
    ta.addEventListener('keydown', ev => { if ((ev.metaKey || ev.ctrlKey) && ev.key === 's') { ev.preventDefault(); save.click(); } });
    replace(article, head, ta, h('p', { class: 'actions' }, save, ' ', saved, ' ', button(t('지우기'), () => trashNote(o.path), 'danger')));
    ta.focus();
  }

  async function fetchPut(p: string, body: unknown, sha: string): Promise<Json> {
    const r = await fetch(`/vault/api/v1/vaults/${current.id}${p}`, { method: 'PUT', credentials: 'same-origin', body: JSON.stringify(body),
                                                                    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch', 'If-Match': sha } });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error ?? t('요청이 실패했습니다 ({status})', { status: r.status }));
    return data;
  }

  let noteVersion = 0;
  async function open(p: string): Promise<void> {
    const version = ++noteVersion;
    editing = false;
    if (!p) p = paths.has(HOME) ? HOME : (notes[0]?.[0] ?? '');
    if (!p) { opened = null; folder = ''; drawTree(); await drawNote(); return; }
    try {
      const next = await v.get(`/file?path=${encodeURIComponent(p)}`);
      if (version !== noteVersion || !article.isConnected) return;
      opened = next;
    } catch (e) {
      if (version !== noteVersion || !article.isConnected) return;
      flash('error', message(e));
      opened = null;
    }
    folder = p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '';
    title(`${p.replace(/\.md$/, '')} · ${t('노트')}`);
    markCurrent();
    await drawNote();
  }

  // a link to a note of this vault (the tree, a wikilink, the hits) opens it in place: the tree stays as drawn
  const within = (ev: MouseEvent) => {
    if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    const a = (ev.target as HTMLElement).closest('a');
    const base = `/vault/${current.id}/`;
    if (!a || !a.getAttribute('href')?.startsWith(base)) return;
    ev.preventDefault();
    if (!canLeave()) return;
    const url = new URL(a.href);
    history.pushState(null, '', url);
    document.dispatchEvent(new Event('vault-note-navigation'));
    void open(url.pathname.slice(base.length).split('/').map(decodeURIComponent).join('/'));
  };
  keys([
    { key: '/', label: t('노트 찾기'), run: () => { (aside.querySelector('input[type=search]') as HTMLInputElement | null)?.focus(); } },
    { key: 'n', label: t('새 노트'), run: () => newNote(folder) },
    { key: 'e', label: t('편집'), run: async () => { if (!opened) return; if (editing) await leaveEditor(); else { editing = true; await drawNote(); } }, when: () => !!opened },
    { key: 'Escape', label: t('보기로'), run: async () => { await leaveEditor(); }, when: () => editing },
  ]);
  const page = h('div', { class: 'vault', onclick: within }, aside, article);
  replace(main(), page);
  watchDraft(page, dirty);
  await open(path);
}
