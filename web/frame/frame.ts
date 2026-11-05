// What every page starts from (docs/frame.md §1–§2): the frame (/auth/api/v1/me: who is signed in, the
// site's name, the apps and their widgets as this person may see them) and the person's own settings
// (/apps/site/api/store/prefs: language, theme, start page, the apps they turned on, their home). One
// load() for all of them; the language and the theme are applied at once and kept as site cookies so the
// server pages and the next first paint agree with the account.

import { setLang } from './i18n';

/** A widget's cells on the grid: one of the sizes the site declares (`frame.sizes`, from portal/site.py SIZES). */
export interface Size { id: string; cols: number; rows: number }
export interface Widget { id: string; title: string; description: string; href: string; size: string }
/** One way to connect to an app (site.toml's `code`): its value may name the person looking as {user}. */
export interface Address { label: string; value: string }
export interface Card { id: string; title: string; description: string; about: string; tags: string[]; code: Address[]; icon: string;
                        href: string; optional: boolean; default: boolean; links: { label: string; href: string }[]; widgets: Widget[] }
/** One choice of the person's look (docs/frame.md §1.3), as the site file declares it: the tokens it redeclares —
 * a palette for each theme, the others once. The first choice of a kind is theme.css's own (nothing redeclared). */
export interface LookChoice { id: string; label: string; tokens?: Record<string, string>; light?: Record<string, string>; dark?: Record<string, string> }
export interface Look { palette: LookChoice[]; corner: LookChoice[]; type: LookChoice[]; size: LookChoice[]; columns: number[] }
export const LOOK_KINDS = ['palette', 'corner', 'type', 'size'] as const;
export type LookKind = (typeof LOOK_KINDS)[number];
/** What the person picked: a choice of each kind (its id), the main page's columns (0: as many as fit), an image. */
export interface LookPrefs { palette?: string; corner?: string; type?: string; size?: string; columns?: number; image?: string }
export interface Frame { uid: string | null; title: string; signin: string; portal: string; lang: string;
                         theme: string; frame: number; cards: Card[]; menu: { label: string; href: string }[]; sizes: Size[]; look: Look }

export const THEMES = ['auto', 'light', 'dark'] as const;
export type Theme = (typeof THEMES)[number];

export interface Placement { app: string; widget: string; size?: string }  // size: the person's own, else the widget's declared one
export interface Prefs {
  lang: string;        // 'auto' (the browser's), or a language the site has
  theme: Theme;        // 'auto' (the OS's), 'light' or 'dark'
  start: string;       // '/' (the main page) or an address of the site to open after signing in
  apps: string[];      // the apps the person turned on, in their order; a new account starts with the apps the site file marks default
  home: Placement[];   // the main page's widgets, in their order; [] = each app's first widget, as turned on
  seen: string[];      // app ids the person has been shown: any other is new to them
  look: LookPrefs;     // the person's look over theme.css (docs/frame.md §1.3); {} = theme.css as it is
}

/** The settings an account starts with. `apps`: the apps the site file marks `default = true` (docs/frame.md §2
 * R13) — filled from the frame once it is loaded; a kept `apps`, an empty one too, is the person's own choice. */
export const DEFAULTS: Prefs = { lang: 'auto', theme: 'auto', start: '/', apps: [], home: [], seen: [], look: {} };
export const frame: Frame = { uid: null, title: '', signin: '/auth', portal: '/account', lang: 'ko', theme: 'auto', frame: 0,
                              cards: [], menu: [], sizes: [], look: { palette: [], corner: [], type: [], size: [], columns: [] } };

/** An image under the page: an address of this site or an https one, nothing that could leave the url("…"). */
export const IMAGE = /^(https:\/\/|\/(?!\/))[^\s"'()\\<>;{}]{1,500}$/;
const LOOK = 'look';  // this browser's copy of the tokens, for theme.js to put on before the first paint

/** The tokens the person's look redeclares, by theme: the palette's for each, the rest for both. */
export function lookTokens(look: Look, p: LookPrefs): { light: Record<string, string>; dark: Record<string, string>; both: Record<string, string> } {
  const pick = (k: LookKind) => look[k]?.find(c => c.id === p[k]);
  const pal = pick('palette');
  const both: Record<string, string> = { ...pick('corner')?.tokens, ...pick('type')?.tokens, ...pick('size')?.tokens };
  if (p.columns && look.columns.includes(p.columns)) both['home-grid'] = `repeat(${p.columns}, minmax(0, 1fr))`;
  if (p.image && IMAGE.test(p.image)) both['page-image'] = `url("${p.image}")`;
  return { light: { ...pal?.light }, dark: { ...pal?.dark }, both };
}

/** The look onto <html> as custom properties (the CSSOM, which the pages' CSP allows; an inline style outranks the
 * theme's selectors), the palette of the theme in force; and into this browser for the next first paint. */
export function applyLook(): void {
  const t = lookTokens(frame.look, prefs.look ?? {});
  try { localStorage.setItem(LOOK, JSON.stringify(t)); } catch { /* storage may be off */ }
  putLook(t);
}
function putLook(t: { light: Record<string, string>; dark: Record<string, string>; both: Record<string, string> }): void {
  const el = document.documentElement;
  for (const name of Array.from(el.style)) if (name.startsWith('--')) el.style.removeProperty(name);
  const set = el.getAttribute('data-theme');
  const dark = set ? set === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  for (const [k, v] of Object.entries({ ...(dark ? t.dark : t.light), ...t.both })) el.style.setProperty(`--${k}`, v);
}
let schemeWatched = false;
/** The size a placement has: its own, else its widget's; unknown ids fall back to the first declared size. */
export function sizeOf(id: string | undefined): Size {
  return frame.sizes.find(s => s.id === id) ?? frame.sizes[0] ?? { id: '1x1', cols: 1, rows: 1 };
}
export const prefs: Prefs = { ...DEFAULTS };

const STORE = '/apps/site/api/store/prefs';
const LOCAL = 'prefs';
const KNOWN = 'prefs-known';  // this browser has seen the account's settings in the store

/** The person's theme onto the document, and into the site cookie theme.js reads before the first paint. */
export function applyTheme(theme: string): void {
  const v: Theme = (THEMES as readonly string[]).includes(theme) ? (theme as Theme) : 'auto';
  if (v === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', v);
  document.cookie = `theme=${v}; path=/; max-age=31536000; samesite=lax`;
  frame.theme = v;
  applyLook();  // the palette follows the theme in force
  if (!schemeWatched) { schemeWatched = true; matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyLook()); }
}

/** What is kept from an older account: `hidden`/`order` (every app shown unless hidden) become `apps`
 * (nothing on unless turned on) — the apps that were shown, in their order. The stored data is not rewritten.
 * An account with nothing kept starts with the site's default apps; a kept `apps` is kept even when it is empty. */
function fromStored(raw: Record<string, unknown>, cards: Card[]): Prefs {
  const p: Prefs = { ...DEFAULTS, ...raw, apps: [...DEFAULTS.apps] } as Prefs;
  if ('apps' in raw) p.apps = Array.isArray(raw.apps) ? (raw.apps as string[]) : [];
  if (!Array.isArray(p.home)) p.home = [];
  if (!('apps' in raw) && (Array.isArray(raw.order) || Array.isArray(raw.hidden))) {
    const hidden = new Set((raw.hidden as string[]) ?? []);
    const order = (raw.order as string[]) ?? [];
    const ids = cards.filter(c => c.optional).map(c => c.id);
    const rank = (id: string) => { const i = order.indexOf(id); return i < 0 ? order.length + ids.indexOf(id) : i; };
    p.apps = ids.filter(id => !hidden.has(id)).sort((a, b) => rank(a) - rank(b));
  }
  if (!(THEMES as readonly string[]).includes(p.theme)) p.theme = 'auto';
  if (!p.look || typeof p.look !== 'object' || Array.isArray(p.look)) p.look = {};
  return p;
}

function remember(): void {
  try { localStorage.setItem(LOCAL, JSON.stringify(prefs)); } catch { /* storage may be off */ }
  document.cookie = `lang=${prefs.lang}; path=/; max-age=31536000; samesite=lax`;
  applyTheme(prefs.theme);
}

/** The frame and the person's settings, applied: call once, before drawing anything. Never throws for a
 * signed-out person or an unreachable store (what this browser last had, else the defaults). */
export async function load(): Promise<Frame> {
  try {
    const r = await fetch('/auth/api/v1/me', { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (r.ok) Object.assign(frame, await r.json());
  } catch { /* the frame stays as it is: a page still draws */ }
  // an answer from an older sign-in (or a test's) may lack the newer fields: every card is whole here
  frame.cards = (frame.cards ?? []).map(c => ({ description: '', about: '', tags: [], code: [], icon: '', href: '', optional: true, default: false, links: [], widgets: [], ...(c as Partial<Card>) } as Card))
    .map(c => typeof (c.code as unknown) === 'string' ? { ...c, code: (c.code as unknown as string) ? [{ label: '', value: c.code as unknown as string }] : [] } : c);
  frame.menu ??= [];
  frame.sizes = Array.isArray(frame.sizes) && frame.sizes.length ? frame.sizes : [{ id: '1x1', cols: 1, rows: 1 }];
  const given: Partial<Look> = frame.look ?? {};  // an older sign-in's answer has no look: theme.css as it is
  frame.look = { palette: given.palette ?? [], corner: given.corner ?? [], type: given.type ?? [], size: given.size ?? [], columns: given.columns ?? [] };
  DEFAULTS.apps = frame.cards.filter(c => c.default && c.optional).map(c => c.id);  // R13: the site file says which
  let raw: Record<string, unknown> = {};
  try { raw = JSON.parse(localStorage.getItem(LOCAL) ?? '{}'); } catch { /* none kept here */ }
  if (frame.uid) {
    try {
      // a key never saved answers 404, which the browser reports as an error: so a browser that has not
      // seen the account's settings yet asks the store's list first, and only once
      let known = localStorage.getItem(KNOWN) === '1';
      if (!known) {
        const r = await fetch(STORE.replace(/\/prefs$/, ''), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        known = r.ok && ((await r.json()) as { keys: { key: string }[] }).keys.some(k => k.key === 'prefs');
      }
      if (known) {
        const r = await fetch(STORE, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        if (r.ok) { raw = await r.json(); localStorage.setItem(KNOWN, '1'); }
        else if (r.status === 404) raw = {};  // deleted meanwhile: the defaults
      } else {
        raw = {};  // never saved: the defaults
      }
    } catch { /* the store is not reachable: what this browser had */ }
  }
  Object.assign(prefs, fromStored(raw, frame.cards));
  setLang(prefs.lang);
  remember();
  return frame;
}

/** Keep a change: with the account, and in this browser. Throws when the account did not take it. */
export async function savePrefs(change: Partial<Prefs>): Promise<void> {
  Object.assign(prefs, change);
  if ('lang' in change) setLang(prefs.lang);
  remember();
  if (!frame.uid) return;
  const r = await fetch(STORE, { method: 'PUT', credentials: 'same-origin', body: JSON.stringify(prefs),
                                 headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' } });
  if (!r.ok) throw new Error(`prefs: ${r.status}`);
  try { localStorage.setItem(KNOWN, '1'); } catch { /* storage may be off */ }
}

/** The apps the person has on, as cards, in their order (apps that cannot be turned off are not here:
 * they live in the person's own menu). */
export const onApps = (): Card[] =>
  prefs.apps.map(id => frame.cards.find(c => c.id === id && c.optional)).filter((c): c is Card => !!c);

/** The app of the page being shown, when the page is an app's (served under /apps/<id>/). */
export function ownCard(base: string = document.baseURI): Card | undefined {
  const m = /\/apps\/([^/]+)\//.exec(new URL(base).pathname);
  return m ? frame.cards.find(c => c.id === m[1]) : undefined;
}
