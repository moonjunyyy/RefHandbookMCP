// What every page starts from (docs/frame.md §1–§2): the frame (/auth/api/v1/me: who is signed in, the
// site's name, the apps and their widgets as this person may see them) and the person's own settings
// (/apps/site/api/store/prefs: language, theme, start page, the apps they turned on, their home). One
// load() for all of them; the language and the theme are applied at once and kept as site cookies so the
// server pages and the next first paint agree with the account.

import { setLang } from './i18n';

export interface Widget { id: string; title: string; href: string; size: '1x1' | '2x1' | '2x2' }
export interface Card { id: string; title: string; description: string; about: string; tags: string[]; code: string; icon: string;
                        href: string; optional: boolean; links: { label: string; href: string }[]; widgets: Widget[] }
export interface Frame { uid: string | null; title: string; signin: string; portal: string; lang: string;
                         theme: string; frame: number; cards: Card[]; menu: { label: string; href: string }[] }

export const THEMES = ['auto', 'light', 'dark'] as const;
export type Theme = (typeof THEMES)[number];

export interface Placement { app: string; widget: string }
export interface Prefs {
  lang: string;        // 'auto' (the browser's), or a language the site has
  theme: Theme;        // 'auto' (the OS's), 'light' or 'dark'
  start: string;       // '/' (the main page) or an address of the site to open after signing in
  apps: string[];      // the apps the person turned on, in their order; nothing is on until they do
  home: Placement[];   // the main page's widgets, in their order; [] = each app's first widget, as turned on
  seen: string[];      // app ids the person has been shown: any other is new to them
}

export const DEFAULTS: Prefs = { lang: 'auto', theme: 'auto', start: '/', apps: [], home: [], seen: [] };
export const frame: Frame = { uid: null, title: '', signin: '/auth', portal: '/account', lang: 'ko', theme: 'auto', frame: 0,
                              cards: [], menu: [] };
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
}

/** What is kept from an older account: `hidden`/`order` (every app shown unless hidden) become `apps`
 * (nothing on unless turned on) — the apps that were shown, in their order. The stored data is not rewritten. */
function fromStored(raw: Record<string, unknown>, cards: Card[]): Prefs {
  const p: Prefs = { ...DEFAULTS, ...raw } as Prefs;
  if (!Array.isArray(p.apps)) p.apps = [];
  if (!Array.isArray(p.home)) p.home = [];
  if (!('apps' in raw) && (Array.isArray(raw.order) || Array.isArray(raw.hidden))) {
    const hidden = new Set((raw.hidden as string[]) ?? []);
    const order = (raw.order as string[]) ?? [];
    const ids = cards.filter(c => c.optional).map(c => c.id);
    const rank = (id: string) => { const i = order.indexOf(id); return i < 0 ? order.length + ids.indexOf(id) : i; };
    p.apps = ids.filter(id => !hidden.has(id)).sort((a, b) => rank(a) - rank(b));
  }
  if (!(THEMES as readonly string[]).includes(p.theme)) p.theme = 'auto';
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
  frame.cards = (frame.cards ?? []).map(c => ({ description: '', about: '', tags: [], code: '', icon: '', href: '', optional: true, links: [], widgets: [], ...(c as Partial<Card>) } as Card));
  frame.menu ??= [];
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
