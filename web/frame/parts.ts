// The parts every page is made of, in the terms of parts.css (docs/frame.md §1.2): the header, a page
// head, a section card, buttons that run an action, a switch, a choice, a link, a help mark, a toast,
// a dialog, the services' JSON APIs. Their signatures carry the rules of §5: a page head takes no
// explanation, an action's success shows in place (no "done" message), a change of state is a switch
// and a move is a link.

import { Child, h, replace } from './dom';
import { frame, onApps, prefs } from './frame';
import { lang, locale, t } from './i18n';

export const main = () => document.getElementById('main') as HTMLElement;

// ── the services' APIs ────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any

async function call(method: string, url: string, body?: unknown): Promise<Json> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') headers['X-Requested-With'] = 'fetch';
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let r: Response;
  try {
    r = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                           credentials: 'same-origin' });
  } catch {
    throw new ApiError(0, 'network', t('서버에 닿지 않습니다. 잠시 뒤 다시 시도하세요.'));
  }
  const text = await r.text();
  let data: Json = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* not JSON: an error page on the way */ }
  if (r.ok) return data;
  if (r.status === 401) {
    location.assign(`${frame.signin}/login?next=${encodeURIComponent(location.pathname + location.search)}`);
  }
  const e = data?.error;  // the services say {error: "why"} (portal/*.py); the handbook says {error: {code, message}}
  const why = typeof e === 'string' ? e : e?.message;
  throw new ApiError(r.status, e?.code ?? 'http', why || t('요청이 실패했습니다 ({status})', { status: r.status }));
}

/** One service's API at its prefix: api('/agents/api/v1').get('/runs'). */
export function api(prefix: string) {
  return {
    get: (path: string) => call('GET', prefix + path),
    post: (path: string, body: unknown = {}) => call('POST', prefix + path, body),
    put: (path: string, body: unknown) => call('PUT', prefix + path, body),
    patch: (path: string, body: unknown) => call('PATCH', prefix + path, body),
    del: (path: string) => call('DELETE', prefix + path),
  };
}

export const site = api('/auth/api/v1');
export const agents = api('/agents/api/v1');
/** The account portal's API: under the portal's root, which the frame says (/account). */
export const account = () => api(`${frame.portal}/api/v1`);

export function message(e: unknown): string {
  return e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
}

// ── the frame ─────────────────────────────────────────────────────────────

function current(href: string): boolean {
  const path = location.pathname.replace(/\/$/, '') || '/';
  const h = href.replace(/\/$/, '') || '/';
  return h === '/' ? path === '/' : path === h || path.startsWith(h + '/');
}

/** The header: the site's name (home), the apps the person has on, and their name — a menu with what is
 * theirs (the account and its pages, the apps catalog, the settings) and the way out. */
export function header(): void {
  const brand = document.getElementById('brand');
  if (brand) brand.textContent = frame.title;
  const nav = document.getElementById('nav') as HTMLElement | null;
  if (!nav) return;
  const own = frame.cards.filter(c => !c.optional);  // the account: not an app to turn on
  replace(nav,
    frame.uid && [
      onApps().map(c => h('a', { href: c.href, 'aria-current': current(c.href) ? 'page' : null },
        c.icon && h('span', { class: 'app-icon', 'aria-hidden': 'true' }, c.icon), c.title)),
      h('details', { class: 'me' },
        h('summary', { title: t('내 메뉴') }, h('code', null, frame.uid)),
        h('div', null,
          own.flatMap(c => [h('a', { href: c.href }, c.title), ...c.links.filter(l => l.href !== c.href).map(l => h('a', { href: l.href }, l.label))]),
          h('a', { href: '/apps' }, t('앱')),
          h('a', { href: '/settings' }, t('설정')),
          h('hr'),
          h('a', { href: `${frame.signin}/logout` }, t('로그아웃')))),
    ],
    !frame.uid && [
      h('a', { href: '/apps' }, t('앱')),
      h('a', { href: `${frame.signin}/login?next=${encodeURIComponent(location.pathname)}` }, t('로그인'))]);
  if (!closing) {
    closing = true;
    document.addEventListener('click', ev => {  // the menu closes when anything else is pressed
      const me = nav.querySelector('details.me[open]');
      if (me && !me.contains(ev.target as Node)) me.removeAttribute('open');
    });
  }
}
let closing = false;

export function title(text: string): void {
  document.title = text ? `${text} · ${frame.title}` : frame.title;
}

/** The head of a page: its name, and its tabs when it has them. Nothing else: a page that needs a sentence
 * to be understood is a page to rename (docs/frame.md §5 R3). */
export function pageHead(heading: Child, tabs?: { href: string; label: string }[]): HTMLElement {
  if (typeof heading === 'string') title(heading);
  return h('div', { class: 'page-head' },
    h('h1', null, heading),
    tabs && h('nav', { class: 'chips' }, tabs.map(tab =>
      h('a', { class: `chip${tabCurrent(tab.href, tabs.map(x => x.href)) ? ' warn' : ''}`, href: tab.href }, tab.label))));
}

/** Whether a tab is the current page's: its own path, or the longest tab path the page is under. */
function tabCurrent(href: string, all: string[]): boolean {
  const path = location.pathname.replace(/\/$/, '');
  const norm = (x: string) => x.replace(/\/$/, '');
  const under = all.filter(x => path === norm(x) || path.startsWith(norm(x) + '/'));
  const best = under.sort((a, b) => norm(b).length - norm(a).length)[0];
  return best !== undefined && norm(best) === norm(href);
}

export function section(heading: Child, ...body: Child[]): HTMLElement {
  return h('section', { class: 'card section' }, heading && h('h2', null, heading), ...body);
}

export function empty(text: string): HTMLElement {
  return h('p', { class: 'empty muted' }, text);
}

/** One line of help, shown when asked for: the only place an explanation lives (§5 R3). */
export function help(text: Child): HTMLElement {
  return h('details', { class: 'help' }, h('summary', { title: t('도움말') }, 'i'), h('p', null, text));
}

/** What a thing says of itself under its name (its id, its state, its numbers): data, not an explanation. */
export function meta(...children: Child[]): HTMLElement {
  return h('p', { class: 'meta' }, ...children);
}

export function tag(text: string, kind = ''): HTMLElement {
  return h('span', { class: `tag ${kind}`.trim() }, text);
}

// ── messages ──────────────────────────────────────────────────────────────

let toastTimer: number | undefined;

/** A result from elsewhere than where it was asked (saved, failed), one at a time, gone on its own; with
 * one action when there is one (undo). The result of an action in place is shown in place, not here. */
export function flash(kind: 'ok' | 'error', text: string, action?: { label: string; run: () => void }): void {
  document.querySelector('.toast')?.remove();
  window.clearTimeout(toastTimer);
  const el = h('p', { class: `flash toast ${kind}`, role: kind === 'error' ? 'alert' : 'status' }, text,
    action && h('button', { type: 'button', class: 'link', onclick: () => { action.run(); el.remove(); } }, action.label));
  el.addEventListener('click', ev => { if ((ev.target as HTMLElement).tagName !== 'BUTTON') el.remove(); });
  document.body.appendChild(el);
  toastTimer = window.setTimeout(() => el.remove(), kind === 'error' || action ? 12000 : 4000);
}

let pending: ['ok' | 'error', string] | null = null;

/** A message for the page about to be shown (after go()): the router shows it once that page is drawn. */
export function flashNext(kind: 'ok' | 'error', text: string): void {
  pending = [kind, text];
}

export function showPending(): void {
  if (pending) flash(...pending);
  pending = null;
}

// ── actions ───────────────────────────────────────────────────────────────

/** Run an action: the button waits while it runs; a refusal is shown; what succeeded shows in place. */
export async function act<T>(button: HTMLButtonElement | null, fn: () => Promise<T>): Promise<T | undefined> {
  if (button) button.disabled = true;
  try {
    return await fn();
  } catch (e) {
    flash('error', message(e));
    return undefined;
  } finally {
    if (button) button.disabled = false;
  }
}

/** A button: one verb, and the action it runs (held while it runs). kind: '' | 'secondary' | 'danger' | 'link'. */
export function button(text: string, fn: (b: HTMLButtonElement) => void | Promise<unknown>, kind = ''): HTMLButtonElement {
  const b = h('button', { type: 'button', class: kind || null }, text);
  b.addEventListener('click', () => void act(b, async () => fn(b)));
  return b;
}

/** A switch: on or off, kept at once; it springs back when the keeping fails. */
export function toggle(label: Child, on: boolean, fn: (on: boolean) => Promise<unknown>, attrs: Record<string, unknown> = {}): HTMLLabelElement {
  const input = h('input', { type: 'checkbox', checked: on, ...attrs });
  input.addEventListener('change', () => {
    const want = input.checked;
    input.disabled = true;
    fn(want).catch(e => { input.checked = !want; flash('error', message(e)); }).finally(() => { input.disabled = false; });
  });
  return h('label', { class: 'switch' }, input, label);
}

/** One choice of several, kept at once. */
export function select(name: string, choices: [string, string][], value: string, fn: (v: string) => Promise<unknown>): HTMLSelectElement {
  const el = h('select', { name }, choices.map(([v, label]) => h('option', { value: v, selected: v === value }, label)));
  el.addEventListener('change', () => {
    const was = value;
    value = el.value;
    el.disabled = true;
    fn(el.value).catch(e => { el.value = was; value = was; flash('error', message(e)); }).finally(() => { el.disabled = false; });
  });
  return el;
}

/** One of several, as a row of chips (a filter, a view): the chosen one is pressed. */
export function choice(choices: [string, Child][], value: string, fn: (v: string) => void, attrs: Record<string, unknown> = {}): HTMLElement {
  const row = h('div', { class: 'chips', role: 'group', ...attrs });
  const draw = () => replace(row, choices.map(([v, label]) =>
    h('button', { type: 'button', class: 'chip', 'aria-pressed': v === value ? 'true' : 'false',
                  onclick: () => { if (v !== value) { value = v; draw(); fn(v); } } }, label)));
  draw();
  return row;
}

/** A form that, when submitted, runs `fn` with its button held. */
export function form(attrs: Record<string, unknown>, fn: (f: HTMLFormElement, b: HTMLButtonElement | null) => Promise<void>,
                     ...children: Child[]): HTMLFormElement {
  const f = h('form', { ...attrs }, ...children);
  f.addEventListener('submit', ev => {
    ev.preventDefault();
    const b = (ev as SubmitEvent).submitter as HTMLButtonElement | null;
    void fn(f, b);
  });
  return f;
}

/** A question (or a form) in a dialog: true when confirmed. `danger`: the confirming button is the red one;
 * `confirmWith`: a word the person must type (the name of what is being destroyed); `justClose`: the sheet
 * applies as the person goes (switches), so its one button closes it. */
export function dialog(heading: string, body: Child, opts: { ok?: string; cancel?: string; danger?: boolean; confirmWith?: string; justClose?: boolean } = {}): Promise<boolean> {
  return new Promise(resolve => {
    const okBtn = h('button', { type: 'submit', class: opts.danger ? 'danger' : opts.justClose ? 'secondary' : null, disabled: !!opts.confirmWith },
                    opts.ok ?? (opts.justClose ? t('닫기') : t('확인')));
    const typed = opts.confirmWith && h('input', { type: 'text', autocomplete: 'off', 'aria-label': opts.confirmWith,
                                                 oninput: (ev: Event) => { okBtn.disabled = (ev.target as HTMLInputElement).value.trim() !== opts.confirmWith; } });
    const d = h('dialog', null,
      form({ method: 'dialog' }, async () => { d.close('ok'); },
        h('h2', null, heading), body, typed && h('label', null, typed),
        h('div', { class: 'actions' },
          !opts.justClose && h('button', { type: 'button', class: 'secondary', onclick: () => d.close('') }, opts.cancel ?? t('취소')), okBtn)));
    d.addEventListener('close', () => { resolve(d.returnValue === 'ok'); d.remove(); });
    // Enter confirms wherever the focus is — a select, a checkbox, a switch, the dialog itself — not only in a text
    // input (the form's implicit submission); a textarea keeps Enter, a button keeps its own; Esc is the dialog's own
    d.addEventListener('keydown', ev => {
      if (ev.key !== 'Enter' || ev.isComposing) return;
      const el = ev.target as HTMLElement;
      if (el.tagName === 'TEXTAREA' || el.tagName === 'BUTTON' || el.tagName === 'A' || el.closest('.menu')) return;
      if (el.closest('form') !== d.firstElementChild) return;  // a form of its own inside the sheet (a line to add): its Enter is its own
      ev.preventDefault();
      if (!okBtn.disabled) okBtn.click();
    });
    document.body.appendChild(d);
    d.showModal();
    // a question with no field: the confirming button has the focus, so Enter confirms (and Esc cancels)
    if (!d.querySelector('input, select, textarea') && !okBtn.disabled) okBtn.focus();
  });
}

// ── the page's keys (docs/frame.md §5 R14): declared once, run from one place, shown with ? ──────────

export interface Key { key: string; label: string; run: () => void | Promise<unknown>; when?: () => boolean }
let pageKeys: Key[] = [];
let keysInstalled = false;

/** Where typing happens: a letter there is text, not a shortcut. */
function typing(el: EventTarget | null): boolean {
  const e = el as HTMLElement | null;
  return !!e && (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.tagName) || e.isContentEditable);
}

/** The page's shortcuts: `key` as KeyboardEvent.key ('t', '/', 'ArrowLeft', 'Escape'; 'Shift+?'-style modifiers
 * as 'Alt+ArrowLeft'); a letter is not taken while typing, Escape and the arrows with Alt are. Called by a page when
 * it draws; the next page replaces the set. ? (Shift+/) shows the list. */
export function keys(list: Key[]): void {
  pageKeys = list;
  if (keysInstalled) return;
  keysInstalled = true;
  document.addEventListener('keydown', ev => {
    if (ev.defaultPrevented || ev.isComposing || document.querySelector('dialog[open]') || openMenu) return;
    const combo = `${ev.altKey ? 'Alt+' : ''}${ev.ctrlKey || ev.metaKey ? 'Ctrl+' : ''}${ev.key}`;
    if (ev.key === '?' && !typing(ev.target)) { ev.preventDefault(); void keysDialog(); return; }
    const hit = pageKeys.find(k => k.key === combo && (!k.when || k.when()));
    if (!hit) return;
    if (typing(ev.target) && !(ev.key === 'Escape' || ev.altKey || ev.ctrlKey || ev.metaKey)) return;
    ev.preventDefault();
    void act(null, async () => hit.run());
  });
}

const KEY_WORDS: Record<string, string> = { ArrowLeft: '←', ArrowRight: '→', ArrowUp: '↑', ArrowDown: '↓', Escape: 'Esc', ' ': 'Space' };

/** The list of the page's keys, as declared — nothing is written here that the page did not declare. */
export function keysDialog(): Promise<boolean> {
  const word = (k: string) => k.split('+').map(p => KEY_WORDS[p] ?? p).join(' + ');
  const rows = pageKeys.filter(k => !k.when || k.when()).map(k => h('li', null, h('kbd', null, word(k.key)), h('span', null, k.label)));
  return dialog(t('이 페이지의 키'), h('ul', { class: 'keys' }, rows, h('li', null, h('kbd', null, '?'), h('span', null, t('이 목록')))), { justClose: true });
}

// ── the menu: an object's actions, at its place (docs/frame.md §5 R10) ────

export interface MenuItem { label: Child; detail?: Child; run: () => void | Promise<unknown>; danger?: boolean; disabled?: boolean; kbd?: string }
export interface MenuSection { title?: string; items: MenuItem[] }
export type MenuAt = { x: number; y: number } | HTMLElement;

let openMenu: HTMLElement | null = null;

export function closeMenu(): void {
  openMenu?.remove();
  openMenu = null;
}

/** The actions of a thing, where it is: a list under the pointer (a right-click), or under its ⋯ button.
 * One line per item — a bold keyword and a dim detail; ↑↓ move, Enter runs, Esc and a click outside close;
 * the focus goes back to where it came from. A menu with one item is still a menu: the place is the point. */
export function menu(at: MenuAt, sections: MenuSection[], opts: { label?: string } = {}): HTMLElement {
  closeMenu();
  const back = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const el = h('div', { class: 'menu', role: 'menu', 'aria-label': opts.label ?? t('메뉴') },
    sections.filter(s => s.items.length).map((s, i) => [
      i > 0 && h('hr'),
      s.title && h('div', { class: 'menu-title' }, s.title),
      s.items.map(it => h('button', { type: 'button', role: 'menuitem', class: `menu-item${it.danger ? ' danger' : ''}`, disabled: it.disabled || null,
                                      onclick: () => { done(); void act(null, async () => it.run()); } },
        h('strong', null, it.label), it.detail && h('span', { class: 'detail' }, it.detail), it.kbd && h('kbd', null, it.kbd))),
    ]));
  const done = () => { if (openMenu === el) { el.remove(); openMenu = null; back?.focus(); } };
  const items = () => Array.from(el.querySelectorAll<HTMLButtonElement>('.menu-item:not(:disabled)'));
  el.addEventListener('keydown', ev => {
    const list = items();
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); list[(i + (ev.key === 'ArrowDown' ? 1 : list.length - 1)) % list.length]?.focus(); }
    else if (ev.key === 'Home') { ev.preventDefault(); list[0]?.focus(); }
    else if (ev.key === 'End') { ev.preventDefault(); list[list.length - 1]?.focus(); }
    else if (ev.key === 'Escape' || ev.key === 'Tab') { ev.preventDefault(); done(); }
  });
  document.body.appendChild(el);
  openMenu = el;
  // where: under the pointer, or under the element it belongs to; never off the screen
  const r = at instanceof HTMLElement ? at.getBoundingClientRect() : null;
  const pt = at instanceof HTMLElement ? { x: 0, y: 0 } : at;
  let x = r ? r.left : pt.x, y = r ? r.bottom + 4 : pt.y;
  const w = el.offsetWidth, hgt = el.offsetHeight;
  if (x + w > innerWidth - 8) x = Math.max(8, (r ? r.right : pt.x) - w);
  if (y + hgt > innerHeight - 8) y = Math.max(8, (r ? r.top - 4 : pt.y) - hgt);
  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
  const outside = (ev: Event) => { if (!el.contains(ev.target as Node)) { done(); off(); } };
  const off = () => { document.removeEventListener('pointerdown', outside, true); window.removeEventListener('resize', done); window.removeEventListener('scroll', done, true); };
  setTimeout(() => { if (openMenu === el) { document.addEventListener('pointerdown', outside, true); window.addEventListener('resize', done); window.addEventListener('scroll', done, true); } });
  items()[0]?.focus();
  return el;
}

/** A thing that has a menu: the right-click, and Shift+F10 (or the menu key) while it has the focus, open the
 * same one. `build` says what the menu holds now; null for nothing. */
export function onMenu(el: HTMLElement, build: () => MenuSection[] | null, opts: { label?: string } = {}): HTMLElement {
  el.addEventListener('contextmenu', ev => {
    const sections = build();
    if (!sections) return;
    ev.preventDefault();
    ev.stopPropagation();
    menu({ x: ev.clientX, y: ev.clientY }, sections, opts);
  });
  el.addEventListener('keydown', ev => {
    if ((ev.shiftKey && ev.key === 'F10') || ev.key === 'ContextMenu') {
      const sections = build();
      if (!sections) return;
      ev.preventDefault();
      ev.stopPropagation();
      menu(el, sections, opts);
    }
  });
  return el;
}

/** The ⋯ button of a row or a head: the same menu, under it. */
export function menuButton(build: () => MenuSection[], label: string = t('더 보기')): HTMLButtonElement {
  const b = h('button', { type: 'button', class: 'more', 'aria-label': label, title: label, 'aria-haspopup': 'menu',
                          onclick: (ev: MouseEvent) => { ev.stopPropagation(); menu(b, build(), { label }); } }, '⋯');
  return b;
}

// ── moving about ──────────────────────────────────────────────────────────

/** Go to a page of the pages app without a reload. */
export function go(path: string): void {
  history.pushState(null, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

/** A move: a link. Inside the pages app it goes without a reload (an app's page reloads: it is another app). */
export function link(href: string, ...children: Child[]): HTMLAnchorElement {
  return h('a', { href, onclick: (ev: MouseEvent) => {
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0 || !href.startsWith('/') || href.startsWith('/apps/') || href.startsWith(frame.signin)) return;
    if (location.pathname.startsWith('/apps/')) return;  // this page is an app's: the pages are elsewhere
    ev.preventDefault();
    go(href);
  } }, ...children);
}

/** The first thing to do on a page that has nothing yet: the one link that looks like a button. */
export function primaryLink(href: string, text: string): HTMLAnchorElement {
  const a = link(href, text);
  a.className = 'primary';
  return a;
}

export const when = (ts: number | null | undefined): string =>
  ts ? new Date(ts * 1000).toLocaleString(locale(), { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-';
export const num = (n: number | null | undefined): string => (n ? n.toLocaleString(locale()) : '-');

export { lang, prefs };
